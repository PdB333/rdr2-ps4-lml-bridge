// Independent, C-callable front end to the portable LML overlay resolver.
// This module does not hook, patch, or inject into RDR2. It can be linked into
// a PS4 game plugin after a compatible PRX loader is verified for the target.
#include "../runtime/overlay_index.hpp"

#include <cstddef>
#include <cstring>
#include <string>

#if defined(__GNUC__) || defined(__clang__)
#define LML_EXPORT __attribute__((visibility("default")))
#else
#define LML_EXPORT
#endif

namespace {

rdr2_lml::OverlayIndex& index() {
    static rdr2_lml::OverlayIndex instance;
    return instance;
}

bool& initialized() {
    static bool ready = false;
    return ready;
}

std::string& last_error() {
    static std::string error;
    return error;
}

int copy_path(const std::string& source, char* output, std::size_t capacity) {
    if (!output || capacity == 0) return -2;
    if (source.size() + 1 > capacity) return -3;
    std::memcpy(output, source.data(), source.size());
    output[source.size()] = '\0';
    return 0;
}

int copy_lookup(bool found, const std::string& result, char* out,
                std::size_t capacity) {
    if (!initialized()) return -4;
    if (!found) return -1;
    return copy_path(result, out, capacity);
}
}  // namespace

// Error codes:
//    0  OK
//   -1  Key not found
//   -2  Bad argument
//   -3  Output buffer too short
//   -4  Index not ready or map rejected
extern "C" LML_EXPORT int lml_bridge_abi_version() {
    return 1;
}

extern "C" LML_EXPORT int lml_bridge_open(
    const char* map_path, const char* payload_root) {
    if (!map_path || !payload_root || !*map_path || !*payload_root) {
        initialized() = false;
        last_error() = "Map path and payload root are required";
        return -2;
    }
    initialized() = false;
    if (!index().load(map_path, payload_root, &last_error())) {
        return -4;
    }
    initialized() = true;
    return 0;
}

extern "C" LML_EXPORT int lml_bridge_lookup_replace(
    const char* game_resource, char* out, std::size_t capacity) {
    if (!game_resource || !out || capacity == 0) return -2;
    std::string resolved;
    const bool found = index().replacement(game_resource, &resolved);
    return copy_lookup(found, resolved, out, capacity);
}

extern "C" LML_EXPORT int lml_bridge_lookup_stream(
    const char* asset_name, char* out, std::size_t capacity) {
    if (!asset_name || !out || capacity == 0) return -2;
    std::string resolved;
    const bool found = index().stream(asset_name, &resolved);
    return copy_lookup(found, resolved, out, capacity);
}

extern "C" LML_EXPORT int lml_bridge_lookup_data(
    const char* data_type, const char* data_name, char* out,
    std::size_t capacity) {
    if (!data_type || !data_name || !out || capacity == 0) return -2;
    std::string resolved;
    const bool found = index().data(data_type, data_name, &resolved);
    return copy_lookup(found, resolved, out, capacity);
}

extern "C" LML_EXPORT int lml_bridge_get_counts(
    std::size_t* replacements, std::size_t* streams, std::size_t* data) {
    if (!replacements || !streams || !data) return -2;
    if (!initialized()) return -4;
    *replacements = index().replacement_count();
    *streams = index().stream_count();
    *data = index().data_count();
    return 0;
}

extern "C" LML_EXPORT int lml_bridge_get_last_error(
    char* out, std::size_t capacity) {
    return copy_path(last_error(), out, capacity);
}

// Startup and runtime process injection are handled by the host loader and
// OpenOrbis CRT. This library does not call any game-internal symbols.
