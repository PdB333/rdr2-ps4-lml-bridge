// End-to-end integration harness for the independent RAGE VFS read-through API.
// Runs on a Windows host. It simulates the ORIGINAL RDR2 RPF8/fiDevice backend;
// no actual game binary or PS4 hook is involved.
#include "rage_vfs_redirect.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <iostream>
#include <string>
#include <unordered_map>

struct Game {
    std::string root;
    std::uint64_t next = 1;
    std::unordered_map<std::uint64_t, FILE*> files;
    int opened = 0;
    int closed = 0;
    int statted = 0;
    bool fail_open = false;
};

static const char* replacement_key = "update:/common/data/ai/combatbehaviour.meta";
static const char* passthrough_key = "update:/common/data/original.bin";

static std::uint64_t game_open(void* ptr, const char* path, std::uint32_t mode) {
    Game& g = *static_cast<Game*>(ptr);
    if (g.fail_open || mode == 0 || (!std::strcmp(path, "") ||
        (std::strcmp(path, replacement_key) &&
         std::strcmp(path, passthrough_key) &&
         std::strcmp(path, "update:/common/data/ai/missing.meta"))))
        return LML_RAGE_MISSING_HANDLE;
    const std::string physical = g.root + "/original.bin";
    FILE* file = std::fopen(physical.c_str(), "rb");
    if (!file) return LML_RAGE_MISSING_HANDLE;
    const std::uint64_t handle = g.next++;
    g.files.emplace(handle, file);
    ++g.opened;
    return handle;
}
static std::int64_t game_read(void* ptr, std::uint64_t token,
                              void* buf, std::size_t n) {
    Game& g = *static_cast<Game*>(ptr);
    const auto it = g.files.find(token);
    return it == g.files.end() ? -1 : static_cast<std::int64_t>(
        std::fread(buf, 1, n, it->second));
}
static std::int64_t game_seek(void* ptr, std::uint64_t token,
                              std::int64_t offset, int whence) {
    Game& g = *static_cast<Game*>(ptr);
    const auto it = g.files.find(token);
    if (it == g.files.end() || std::fseek(it->second, static_cast<long>(offset),
                                         whence)) return -1;
    return std::ftell(it->second);
}
static std::int64_t game_size(void* ptr, std::uint64_t token) {
    Game& g = *static_cast<Game*>(ptr);
    const auto it = g.files.find(token);
    if (it == g.files.end()) return -1;
    const long pos = std::ftell(it->second);
    if (pos < 0 || std::fseek(it->second, 0, SEEK_END)) return -1;
    const long size = std::ftell(it->second);
    if (std::fseek(it->second, pos, SEEK_SET)) return -1;
    return size;
}
static int game_close(void* ptr, std::uint64_t token) {
    Game& g = *static_cast<Game*>(ptr);
    const auto it = g.files.find(token);
    if (it == g.files.end()) return -1;
    const int status = std::fclose(it->second);
    g.files.erase(it);
    ++g.closed;
    return status;
}
static int game_stat(void* ptr, const char* path, LmlRageFileInfo* out) {
    Game& g = *static_cast<Game*>(ptr);
    ++g.statted;
    if (std::strcmp(path, replacement_key) &&
        std::strcmp(path, passthrough_key)) return LML_RAGE_NOT_FOUND;
    out->size = 16;  // Original game resource is 16 bytes.
    out->unix_modification_time = 0;
    out->attributes = 1;
    out->reserved = 0;
    return 0;
}
struct LoaderProbe {
    std::string path;
    int calls = 0;
};

static std::int64_t fake_text_loader(void* ptr, const char* path, void* request) {
    LoaderProbe* probe = static_cast<LoaderProbe*>(ptr);
    if (!probe || !request) return -1;
    probe->path = path;
    ++probe->calls;
    return 77;
}

static void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "ASSERTION FAILED: " << message << "\n";
        std::exit(3);
    }
}
static std::string read_as_text(std::uint64_t token, std::size_t n) {
    char buffer[256] = {};
    require(n < sizeof(buffer), "buffer capacity");
    auto amount = lml_rage_read_file(token, buffer, n);
    require(amount >= 0 && amount < static_cast<std::int64_t>(sizeof(buffer)),
            "read succeeded");
    return std::string(buffer, static_cast<std::size_t>(amount));
}
int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: rage_vfs_harness <newly-generated-test-directory>\n";
        return 2;
    }
    const std::string root = argv[1];
    const std::string map = root + "/overlay.map";
    const std::string asset = root + "/payload/override.meta";
    const std::string backup = root + "/payload/override.meta.hidden";

    Game game;
    game.root = root;
    const LmlRageOriginalVfs callbacks = {
        LML_RAGE_ABI_VERSION, &game, game_open, game_read, game_seek,
        game_size, game_close, game_stat
    };
    require(lml_rage_abi_version() == 1, "ABI version");
    require(lml_rage_clear() == 0, "initial clear");
    std::uint64_t t = 0;
    std::uint32_t source = 99;
    require(lml_rage_open_file(replacement_key, 1, &t, &source) ==
            LML_RAGE_NO_BACKEND, "not attached at first");
    require(lml_rage_bind_game_io(&callbacks) == 0, "bind original trampolines");
    require(lml_rage_load_overlay(map.c_str(), root.c_str()) == 0, "load LML map");
    char resolved_loader_path[1024] = {};
    require(lml_rage_select_loader_path(
                replacement_key, resolved_loader_path,
                sizeof(resolved_loader_path)) == LML_RAGE_OK &&
            std::string(resolved_loader_path) == asset,
            "text loader can receive verified physical replacement path");
    require(lml_rage_select_loader_path(
                replacement_key, resolved_loader_path, 5) ==
            LML_RAGE_BAD_ARGUMENT, "caller-provided path buffer is bounded");
    require(lml_rage_select_loader_path(
                "update:/common/data/test.ytd", resolved_loader_path,
                sizeof(resolved_loader_path)) == LML_RAGE_NOT_FOUND,
            "binary resource path needs separate RAGE streamer hook");
    LoaderProbe text_loader;
    int text_request = 1;
    std::uint32_t did_redirect = 0;
    require(lml_rage_dispatch_text_loader(
                replacement_key, fake_text_loader, &text_loader,
                &text_request, &did_redirect) == 77 &&
            did_redirect == 1 && text_loader.path == asset &&
            text_loader.calls == 1, "text-loader detour body substitutes path once");
    require(lml_rage_dispatch_text_loader(
                "update:/common/data/foo.ytd", fake_text_loader,
                &text_loader, &text_request, &did_redirect) == 77 &&
            did_redirect == 0 && text_loader.path ==
            "update:/common/data/foo.ytd" && text_loader.calls == 2,
            "binary asset loader path must not be rewritten");
    LmlRageFileInfo attributes = {};
    require(lml_rage_stat_path(replacement_key, &attributes) == 0 &&
            attributes.size == 14, "replacement stat has overlay length");
    require(lml_rage_open_file("UPDATE:\\COMMON\\DATA\\AI\\COMBATBEHAVIOUR.META",
                               1, &t, &source) == 0 &&
            source == LML_RAGE_SOURCE_OVERLAY, "intercepted casefolded path");
    require(lml_rage_size_file(t) == 14, "replacement handle size");
    require(read_as_text(t, 20) == "MODDED_CONTENT", "replacement bytes delivered");
    char four[5] = {};
    require(lml_rage_read_at(t, 8, four, 3) == 3 &&
            std::string(four, 3) == "ONT", "read_at uses logical handle");
    require(lml_rage_seek_file(t, 0, SEEK_SET) == 0, "seek back");
    require(read_as_text(t, 6) == "MODDED", "read again");
    require(lml_rage_bind_game_io(nullptr) == LML_RAGE_BUSY,
            "original callbacks cannot change while open");
    require(lml_rage_clear() == LML_RAGE_BUSY,
            "map cannot be unloaded while a file is open");
    require(lml_rage_close_file(t) == 0, "close replaced file");
    require(lml_rage_close_file(t) == LML_RAGE_NOT_FOUND, "reject stale token");

    require(lml_rage_open_file(passthrough_key, 1, &t, &source) == 0 &&
            source == LML_RAGE_SOURCE_ORIGINAL, "miss falls through");
    require(read_as_text(t, 20) == "ORIGINAL_CONTENT", "original RPF data");
    require(lml_rage_size_file(t) == 16, "original handle length");
    require(lml_rage_close_file(t) == 0, "close original handle");

    require(lml_rage_open_file(replacement_key, 2, &t, &source) == 0 &&
            source == LML_RAGE_SOURCE_ORIGINAL, "non-read request never overridden");
    require(lml_rage_close_file(t) == 0, "close write-intent fallback");

    require(std::rename(asset.c_str(), backup.c_str()) == 0,
            "move replacement to simulate inaccessible asset");
    require(lml_rage_open_file(replacement_key, 1, &t, &source) == 0 &&
            source == LML_RAGE_SOURCE_ORIGINAL, "missing replacement uses game file");
    require(read_as_text(t, 20) == "ORIGINAL_CONTENT",
            "missing replacement original content");
    require(lml_rage_close_file(t) == 0, "close missing asset fallback");
    require(lml_rage_select_loader_path(replacement_key, resolved_loader_path,
                sizeof(resolved_loader_path)) == LML_RAGE_NOT_FOUND,
            "missing replacement never reaches the text loader");
    require(lml_rage_dispatch_text_loader(
                replacement_key, fake_text_loader,
                &text_loader, &text_request, &did_redirect) == 77 &&
            did_redirect == 0 && text_loader.path == replacement_key,
            "missing overlay uses original text loader path");
    require(std::rename(backup.c_str(), asset.c_str()) == 0, "restore replacement");

    // Mismatch in physical asset length after manifest load -> fallback.
    {
        FILE* file = std::fopen(asset.c_str(), "wb");
        require(file != nullptr, "can create temporary mismatched asset");
        require(std::fwrite("XX", 1, 2, file) == 2, "truncate asset");
        std::fclose(file);
    }
    require(lml_rage_open_file(replacement_key, 1, &t, &source) == 0 &&
            source == LML_RAGE_SOURCE_ORIGINAL, "size mismatch uses game file");
    require(lml_rage_close_file(t) == 0, "close size mismatch fallback");

    require(lml_rage_stat_path(replacement_key, &attributes) == 0 &&
            attributes.size == 16, "metadata also falls through to game file");
    require(lml_rage_select_loader_path(replacement_key, resolved_loader_path,
                sizeof(resolved_loader_path)) == LML_RAGE_NOT_FOUND,
            "tampered-sized asset never reaches text loader");

    require(lml_rage_open_file("update:/../../bad.meta", 1, &t, &source) ==
            LML_RAGE_NOT_FOUND, "path traversal cannot redirect");
    require(lml_rage_read_file(UINT64_C(42), four, 3) == LML_RAGE_NOT_FOUND,
            "reject unknown tokens");
    require(lml_rage_get_counters(nullptr) == LML_RAGE_BAD_ARGUMENT,
            "counter pointer is required");
    LmlRageCounters counters = {};
    require(lml_rage_get_counters(&counters) == 0, "get counters");
    require(counters.redirected_opens == 1 &&
            counters.original_opens >= 4 &&
            counters.overlay_fallbacks == 2 &&
            counters.active_tokens == 0, "correct statistics");
    require(game.opened == game.closed && game.files.empty(), "no leaked RPF handles");

    require(lml_rage_clear() == 0, "clean shutdown");
    std::cout << "RAGE_VFS_READTHROUGH_HOST_PASSED"
              << " redirected=" << counters.redirected_opens
              << " originals=" << counters.original_opens
              << " fallbacks=" << counters.overlay_fallbacks << "\n";
    return 0;
}
