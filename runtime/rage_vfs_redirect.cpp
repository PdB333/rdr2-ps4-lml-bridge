#include "rage_vfs_redirect.h"
#include "overlay_index.hpp"

#include <climits>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>

#include <sys/stat.h>

namespace {
static constexpr std::uint64_t kTokenBase = UINT64_C(0x4C4D4C0000000000);
static constexpr std::uint64_t kTokenMask = UINT64_C(0x000000FFFFFFFFFF);
static constexpr std::size_t kMaxOpenFiles = 256;
static constexpr std::size_t kMaxVirtualPath = 1024;

enum class Source { Overlay, Original };

struct Stream {
    Source source = Source::Overlay;
    FILE* file = nullptr;
    std::uint64_t original = LML_RAGE_MISSING_HANDLE;
    LmlRageOriginalVfs backend = {};
    std::uint64_t expected_size = 0;
    bool closed = false;
    std::mutex mutex;
};

struct State {
    std::mutex mutex;
    rdr2_lml::OverlayIndex index;
    bool enabled = false;
    LmlRageOriginalVfs game = {};
    std::uint64_t next_id = 1;
    LmlRageCounters stats = {};
    std::unordered_map<std::uint64_t, std::shared_ptr<Stream>> open;
};

State& state() {
    static State instance;
    return instance;
}

bool valid_path(const char* path) {
    if (!path || !path[0]) return false;
    for (std::size_t i = 0; i <= kMaxVirtualPath; ++i) {
        if (path[i] == '\0') return i > 0;
        if (static_cast<unsigned char>(path[i]) < 32u) return false;
    }
    return false;
}

bool physical_length(FILE* file, std::uint64_t* bytes) {
    if (std::fseek(file, 0, SEEK_END) != 0) return false;
    long length = std::ftell(file);
    if (length < 0 || std::fseek(file, 0, SEEK_SET) != 0) return false;
    *bytes = static_cast<std::uint64_t>(length);
    return true;
}

/* open() and stat() must see the same bytes. If an asset disappears or its
 * length changes, use the game's original behavior instead.
 *
 * Manifest hashes are verified during off-console staging, but this layer
 * verifies length at EACH open. SHA-256 is intentionally not recalculated on
 * the RAGE streaming thread (it would stall game I/O).
 */
FILE* open_verified_file(const std::string& path,
                         const rdr2_lml::Entry& manifest) {
    FILE* file = std::fopen(path.c_str(), "rb");
    if (!file) return nullptr;
    std::uint64_t size = 0;
    if (!physical_length(file, &size) || size != manifest.byte_length) {
        std::fclose(file);
        return nullptr;
    }
    return file;
}

std::shared_ptr<Stream> get_stream(std::uint64_t token) {
    State& s = state();
    std::lock_guard<std::mutex> guard(s.mutex);
    auto it = s.open.find(token);
    if (it == s.open.end()) return {};
    return it->second;
}

int register_stream(std::shared_ptr<Stream> stream,
                    std::uint64_t* out_token, std::uint32_t* source) {
    State& s = state();
    std::lock_guard<std::mutex> lock(s.mutex);
    if (s.open.size() >= kMaxOpenFiles || s.next_id == 0
        || s.next_id > kTokenMask) {
        return LML_RAGE_BUSY;
    }
    const std::uint64_t token = kTokenBase | s.next_id++;
    if (!s.open.emplace(token, stream).second) return LML_RAGE_BUSY;
    ++(stream->source == Source::Overlay ?
       s.stats.redirected_opens : s.stats.original_opens);
    s.stats.active_tokens = s.open.size();
    *out_token = token;
    if (source) *source = stream->source == Source::Overlay ?
                               LML_RAGE_SOURCE_OVERLAY : LML_RAGE_SOURCE_ORIGINAL;
    return LML_RAGE_OK;
}

int open_impl(const char* path, std::uint32_t mode,
              std::uint64_t* token, std::uint32_t* source) {
    if (!valid_path(path) || !token) return LML_RAGE_BAD_ARGUMENT;
    *token = LML_RAGE_MISSING_HANDLE;
    if (source) *source = LML_RAGE_SOURCE_ORIGINAL;

    State& s = state();
    rdr2_lml::Entry info;
    std::string replacement;
    bool found = false;
    LmlRageOriginalVfs cb = {};
    {
        std::lock_guard<std::mutex> lock(s.mutex);
        cb = s.game;
        if (s.open.size() >= kMaxOpenFiles) return LML_RAGE_BUSY;
        if (mode == LML_RAGE_READ_ONLY && s.enabled) {
            found = s.index.replacement_metadata(path, &replacement, &info);
        }
    }

    if (found) {
        FILE* file = open_verified_file(replacement, info);
        if (file) {
            // Guard the physical handle even when allocation/map insertion
            // throws: exceptions must not leak file descriptors in RDR2.
            try {
                auto stream = std::make_shared<Stream>();
                stream->source = Source::Overlay;
                stream->file = file;
                stream->expected_size = info.byte_length;
                int result = register_stream(stream, token, source);
                if (result != LML_RAGE_OK) std::fclose(file);
                return result;
            } catch (...) {
                std::fclose(file);
                throw;
            }
        }
        // Replacement is not usable: never block the original game file.
        std::lock_guard<std::mutex> guard(s.mutex);
        ++s.stats.overlay_fallbacks;
    }

    if (!cb.open) return LML_RAGE_NO_BACKEND;
    // Callback MUST point to a verified ORIGINAL RAGE trampoline, never a hook.
    const std::uint64_t original = cb.open(cb.context, path, mode);
    if (original == LML_RAGE_MISSING_HANDLE) {
        std::lock_guard<std::mutex> guard(s.mutex);
        ++s.stats.failed_opens;
        return LML_RAGE_NOT_FOUND;
    }
    try {
        auto stream = std::make_shared<Stream>();
        stream->source = Source::Original;
        stream->original = original;
        stream->backend = cb;
        const int result = register_stream(stream, token, source);
        if (result != LML_RAGE_OK && cb.close) cb.close(cb.context, original);
        return result;
    } catch (...) {
        if (cb.close) cb.close(cb.context, original);
        throw;
    }
}

int64_t seek_locked(Stream& f, std::int64_t offset, int origin) {
    if (origin != SEEK_SET && origin != SEEK_CUR && origin != SEEK_END)
        return LML_RAGE_BAD_ARGUMENT;
    if (f.source == Source::Original) {
        if (!f.backend.seek) return LML_RAGE_NO_BACKEND;
        return f.backend.seek(f.backend.context, f.original, offset, origin);
    }
    if (offset < static_cast<std::int64_t>(LONG_MIN)
        || offset > static_cast<std::int64_t>(LONG_MAX)) return LML_RAGE_BAD_ARGUMENT;
    if (std::fseek(f.file, static_cast<long>(offset), origin) != 0)
        return LML_RAGE_IO_ERROR;
    long pos = std::ftell(f.file);
    return pos < 0 ? static_cast<int64_t>(LML_RAGE_IO_ERROR) : static_cast<int64_t>(pos);
}

int64_t read_locked(Stream& f, void* target, std::size_t length) {
    if (f.source == Source::Original) {
        if (!f.backend.read) return LML_RAGE_NO_BACKEND;
        return f.backend.read(f.backend.context, f.original, target, length);
    }
    const std::size_t got = std::fread(target, 1, length, f.file);
    if (got < length && std::ferror(f.file)) return LML_RAGE_IO_ERROR;
    return static_cast<std::int64_t>(got);
}

int stat_impl(const char* path, LmlRageFileInfo* out) {
    if (!valid_path(path) || !out) return LML_RAGE_BAD_ARGUMENT;
    State& s = state();
    rdr2_lml::Entry info;
    std::string replacement;
    bool found = false;
    LmlRageOriginalVfs cb = {};
    {
        std::lock_guard<std::mutex> lock(s.mutex);
        cb = s.game;
        if (s.enabled) {
            found = s.index.replacement_metadata(path, &replacement, &info);
        }
    }
    if (found) {
        FILE* f = open_verified_file(replacement, info);
        if (f) {
            std::fclose(f);
            struct stat details {};
            std::uint64_t modified = 0;
            if (::stat(replacement.c_str(), &details) == 0)
                modified = static_cast<std::uint64_t>(details.st_mtime);
            out->size = info.byte_length;
            out->unix_modification_time = modified;
            out->attributes = 1u;
            out->reserved = 0;
            return LML_RAGE_OK;
        }
    }
    if (!cb.stat) return LML_RAGE_NO_BACKEND;
    return cb.stat(cb.context, path, out);
}

int close_impl(std::uint64_t token) {
    State& s = state();
    std::shared_ptr<Stream> file;
    {
        std::lock_guard<std::mutex> guard(s.mutex);
        auto it = s.open.find(token);
        if (it == s.open.end()) return LML_RAGE_NOT_FOUND;
        file = it->second;
        s.open.erase(it);
        s.stats.active_tokens = s.open.size();
    }
    std::lock_guard<std::mutex> guard(file->mutex);
    if (file->closed) return LML_RAGE_NOT_FOUND;
    file->closed = true;
    if (file->source == Source::Original) {
        return file->backend.close ?
            file->backend.close(file->backend.context, file->original) :
            LML_RAGE_NO_BACKEND;
    }
    return std::fclose(file->file) == 0 ?
                       LML_RAGE_OK : LML_RAGE_IO_ERROR;
}
} // namespace

extern "C" {

LML_RAGE_EXPORT std::uint32_t lml_rage_abi_version(void) {
    return LML_RAGE_ABI_VERSION;
}

LML_RAGE_EXPORT int lml_rage_load_overlay(const char* map, const char* root) {
    if (!map || !*map || !root || !*root) return LML_RAGE_BAD_ARGUMENT;
    try {
        State& s = state();
        std::lock_guard<std::mutex> guard(s.mutex);
        if (!s.open.empty()) return LML_RAGE_BUSY;
        s.enabled = false;
        std::string error;
        if (!s.index.load(map, root, &error)) return LML_RAGE_IO_ERROR;
        s.enabled = true;
        return LML_RAGE_OK;
    } catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT int lml_rage_bind_game_io(const LmlRageOriginalVfs* backend) {
    State& s = state();
    std::lock_guard<std::mutex> guard(s.mutex);
    if (!s.open.empty()) return LML_RAGE_BUSY;
    if (!backend) {
        s.game = {};
        return LML_RAGE_OK;
    }
    if (backend->abi_version != LML_RAGE_ABI_VERSION || !backend->open ||
        !backend->read || !backend->seek || !backend->size || !backend->close ||
        !backend->stat) return LML_RAGE_BAD_ARGUMENT;
    s.game = *backend;
    return LML_RAGE_OK;
}

LML_RAGE_EXPORT int lml_rage_open_file(const char* virtual_path, std::uint32_t mode,
                                      std::uint64_t* out_token,
                                      std::uint32_t* out_source) {
    try {
        return open_impl(virtual_path, mode, out_token, out_source);
    } catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT std::int64_t lml_rage_read_file(std::uint64_t token, void* dst,
                                                std::size_t count) {
    if ((!dst && count) || count > static_cast<std::size_t>(INT64_MAX))
        return LML_RAGE_BAD_ARGUMENT;
    try {
        auto f = get_stream(token);
        if (!f) return LML_RAGE_NOT_FOUND;
        std::lock_guard<std::mutex> guard(f->mutex);
        if (f->closed) return LML_RAGE_NOT_FOUND;
        return count ? read_locked(*f, dst, count) : 0;
    } catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT std::int64_t lml_rage_seek_file(std::uint64_t token,
                                                std::int64_t offset, int origin) {
    try {
        auto f = get_stream(token);
        if (!f) return LML_RAGE_NOT_FOUND;
        std::lock_guard<std::mutex> guard(f->mutex);
        return f->closed ? static_cast<int64_t>(LML_RAGE_NOT_FOUND) : seek_locked(*f, offset, origin);
    } catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT std::int64_t lml_rage_read_at(std::uint64_t token,
                                              std::uint64_t offset,
                                              void* dst, std::size_t count) {
    if ((!dst && count) || offset > static_cast<std::uint64_t>(INT64_MAX) ||
        count > static_cast<std::size_t>(INT64_MAX))
        return LML_RAGE_BAD_ARGUMENT;
    try {
        auto f = get_stream(token);
        if (!f) return LML_RAGE_NOT_FOUND;
        std::lock_guard<std::mutex> guard(f->mutex);
        if (f->closed) return LML_RAGE_NOT_FOUND;
        if (seek_locked(*f, static_cast<int64_t>(offset), SEEK_SET) < 0)
            return LML_RAGE_IO_ERROR;
        return count ? read_locked(*f, dst, count) : 0;
    } catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT std::int64_t lml_rage_size_file(std::uint64_t token) {
    try {
        auto f = get_stream(token);
        if (!f) return LML_RAGE_NOT_FOUND;
        std::lock_guard<std::mutex> guard(f->mutex);
        if (f->closed) return LML_RAGE_NOT_FOUND;
        if (f->source == Source::Overlay)
            return static_cast<std::int64_t>(f->expected_size);
        if (!f->backend.size) return LML_RAGE_NO_BACKEND;
        return f->backend.size(f->backend.context, f->original);
    } catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT int lml_rage_close_file(std::uint64_t token) {
    try { return close_impl(token); }
    catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT int lml_rage_stat_path(const char* path,
                                      LmlRageFileInfo* out) {
    try { return stat_impl(path, out); }
    catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT int lml_rage_select_loader_path(const char* virtual_path,
                                                char* out_path, std::size_t capacity) {
    if (!valid_path(virtual_path) || !out_path || capacity == 0)
        return LML_RAGE_BAD_ARGUMENT;
    out_path[0] = 0;
    // This branch is for text loaders, NOT for binary RAGE resource streamers.
    std::string lower(virtual_path);
    for (char& c : lower) {
        const unsigned char uc = static_cast<unsigned char>(c);
        if (uc >= 'A' && uc <= 'Z') c = static_cast<char>(uc + ('a' - 'A'));
    }
    const auto dot = lower.rfind('.');
    if (dot == std::string::npos || (
        lower.compare(dot, std::string::npos, ".xml") != 0 &&
        lower.compare(dot, std::string::npos, ".meta") != 0 &&
        lower.compare(dot, std::string::npos, ".omt") != 0 &&
        lower.compare(dot, std::string::npos, ".dat") != 0))
        return LML_RAGE_NOT_FOUND;
    try {
        rdr2_lml::Entry info;
        std::string physical;
        State& s = state();
        {
            std::lock_guard<std::mutex> guard(s.mutex);
            if (!s.enabled ||
                !s.index.replacement_metadata(virtual_path, &physical, &info))
                return LML_RAGE_NOT_FOUND;
        }
        FILE* file = open_verified_file(physical, info);
        if (!file) return LML_RAGE_NOT_FOUND;
        std::fclose(file);
        if (physical.size() + 1 > capacity) return LML_RAGE_BAD_ARGUMENT;
        std::memcpy(out_path, physical.c_str(), physical.size() + 1);
        return LML_RAGE_OK;
    } catch (...) { return LML_RAGE_IO_ERROR; }
}

LML_RAGE_EXPORT std::int64_t lml_rage_dispatch_text_loader(
    const char* virtual_path, LmlRageTextLoaderFn unhooked_original,
    void* context, void* opaque_request, std::uint32_t* redirected) {
    if (redirected) *redirected = 0;
    if (!valid_path(virtual_path) || !unhooked_original)
        return LML_RAGE_BAD_ARGUMENT;
    char physical[2048] = {};
    const int selected = lml_rage_select_loader_path(
        virtual_path, physical, sizeof(physical));
    const char* final_path = virtual_path;
    if (selected == LML_RAGE_OK) {
        final_path = physical;
        if (redirected) *redirected = 1u;
    }
    // The version-verified thunk MUST pass the ORIGINAL loader trampoline.
    // The adapter performs one call only; retrying a partially executed
    // RAGE loader might corrupt state. It never stores the physical pointer.
    try {
        return unhooked_original(context, final_path, opaque_request);
    } catch (...) {
        return LML_RAGE_IO_ERROR;
    }
}

LML_RAGE_EXPORT int lml_rage_get_counters(LmlRageCounters* out) {
    if (!out) return LML_RAGE_BAD_ARGUMENT;
    State& s = state();
    std::lock_guard<std::mutex> guard(s.mutex);
    *out = s.stats;
    return LML_RAGE_OK;
}

LML_RAGE_EXPORT int lml_rage_clear(void) {
    State& s = state();
    std::lock_guard<std::mutex> guard(s.mutex);
    if (!s.open.empty()) return LML_RAGE_BUSY;
    s.index = rdr2_lml::OverlayIndex();
    s.enabled = false;
    s.game = {};
    s.stats = {};
    return LML_RAGE_OK;
}

} // extern "C"
