#include "overlay_index.hpp"

#include <cctype>
#include <fstream>
#include <sstream>
#include <utility>
#include <vector>

namespace rdr2_lml {
namespace {

bool failure(std::string* error, const std::string& message) {
    if (error) *error = message;
    return false;
}

std::string ascii_lower(std::string value) {
    for (char& c : value) {
        unsigned char uc = static_cast<unsigned char>(c);
        if (uc >= 'A' && uc <= 'Z') c = char(uc + ('a' - 'A'));
    }
    return value;
}

std::string slash(std::string value) {
    for (char& c : value) if (c == '\\') c = '/';
    return value;
}

bool clean_components(const std::string& value) {
    if (value.empty() || value.front() == '/' || value.back() == '/') return false;
    std::size_t begin = 0;
    while (begin < value.size()) {
        const std::size_t next = value.find('/', begin);
        const std::string part = value.substr(begin, next == std::string::npos
                                                            ? std::string::npos : next - begin);
        if (part.empty() || part == "." || part == ".." || part.find(':') != std::string::npos) {
            return false;
        }
        for (unsigned char byte : part) if (byte < 0x20 || byte == 0x7f) return false;
        if (next == std::string::npos) return true;
        begin = next + 1;
    }
    return false;
}

bool clean_key(char kind, std::string raw, std::string* out) {
    raw = ascii_lower(slash(std::move(raw)));
    if (kind == 'R') {
        const std::size_t colon = raw.find(":/");
        if (colon == std::string::npos || colon < 2) return false;
        for (std::size_t i = 0; i < colon; ++i) {
            const char c = raw[i];
            if (!(c >= 'a' && c <= 'z') && !(i > 0 && c >= '0' && c <= '9')
                && c != '_' && c != '.' && c != '-') return false;
        }
        const std::string path = raw.substr(colon + 2);
        if (!clean_components(path)) return false;
    } else if (kind == 'S') {
        if (!clean_components(raw)) return false;
    } else if (kind == 'D') {
        const std::size_t slashpos = raw.find('/');
        if (slashpos == std::string::npos || slashpos == 0) return false;
        for (std::size_t i = 0; i < slashpos; ++i) {
            const char c = raw[i];
            if (!(c >= 'a' && c <= 'z') && !(i > 0 && c >= '0' && c <= '9')
                && c != '_') return false;
        }
        if (!clean_components(raw.substr(slashpos + 1))) return false;
    } else {
        return false;
    }
    *out = raw;
    return true;
}

bool clean_payload_path(const std::string& input) {
    const std::string normal = slash(input);
    if (!clean_components(normal)) return false;
    return true;
}

std::vector<std::string> split_tabs(const std::string& line) {
    std::vector<std::string> parts;
    std::size_t first = 0;
    do {
        const auto next = line.find('\t', first);
        parts.push_back(line.substr(first, next == std::string::npos
                                               ? std::string::npos : next - first));
        if (next == std::string::npos) break;
        first = next + 1;
    } while (true);
    return parts;
}

bool valid_hex_sha256(const std::string& value) {
    if (value.size() != 64) return false;
    for (unsigned char ch : value) {
        if (!std::isxdigit(ch)) return false;
    }
    return true;
}

std::string join_path(const std::string& base, const std::string& relative) {
    return base + (base.empty() || base.back() == '/' || base.back() == '\\' ? "" : "/")
                + relative;
}

}  // namespace

bool OverlayIndex::load(const std::string& map, const std::string& root, std::string* error) {
    std::ifstream input(map.c_str(), std::ios::binary);
    if (!input) return failure(error, "Could not open overlay map");
    std::string first;
    if (!std::getline(input, first)) {
        return failure(error, "Missing overlay map header");
    }
    if (!first.empty() && first.back() == '\r') first.pop_back();
    if (first != "LML_OVERLAY_V1") {
        return failure(error, "Unsupported overlay map format");
    }
    std::unordered_map<std::string, Entry> replaces, streams, data;
    std::string line;
    std::size_t line_number = 1;
    while (std::getline(input, line)) {
        ++line_number;
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty() || line.front() == '#') continue;
        const auto parts = split_tabs(line);
        if (parts.size() != 5 || parts[0].size() != 1) {
            return failure(error, "Bad map columns at line " + std::to_string(line_number));
        }
        const char kind = parts[0][0];
        std::string key;
        if (!clean_key(kind, parts[1], &key) || !clean_payload_path(parts[2])
            || !valid_hex_sha256(parts[3])) {
            return failure(error, "Invalid map key, payload or digest at line "
                                   + std::to_string(line_number));
        }
        std::size_t consumed = 0;
        std::uint64_t bytes = 0;
        try {
            bytes = std::stoull(parts[4], &consumed, 10);
        } catch (...) {
            return failure(error, "Invalid payload size at line " + std::to_string(line_number));
        }
        if (consumed != parts[4].size()) {
            return failure(error, "Invalid numeric payload size at line " + std::to_string(line_number));
        }
        const std::string fullpath = join_path(root, slash(parts[2]));
        std::ifstream resource(fullpath.c_str(), std::ios::binary | std::ios::ate);
        if (!resource || resource.tellg() < 0
            || static_cast<std::uint64_t>(resource.tellg()) != bytes) {
            return failure(error, "Payload missing or size mismatch at line "
                                   + std::to_string(line_number) + " : " + fullpath);
        }
        Entry entry{key, parts[2], parts[3], bytes};
        auto* table = kind == 'R' ? &replaces : kind == 'S' ? &streams : &data;
        if (!table->emplace(key, std::move(entry)).second) {
            return failure(error, "Duplicate overlay key at line " + std::to_string(line_number));
        }
    }
    base_ = root;
    replacements_.swap(replaces);
    streams_.swap(streams);
    data_files_.swap(data);
    if (error) error->clear();
    return true;
}

bool OverlayIndex::find(const std::unordered_map<std::string, Entry>& entries,
                        const std::string& virtual_path,
                        std::string* file) const {
    const auto it = entries.find(virtual_path);
    if (it == entries.end()) return false;
    if (file) *file = join_path(base_, slash(it->second.relative_payload));
    return true;
}

bool OverlayIndex::replacement(const std::string& key, std::string* file) const {
    std::string normalized;
    return clean_key('R', key, &normalized) && find(replacements_, normalized, file);
}

bool OverlayIndex::replacement_metadata(const std::string& path,
                                        std::string* file, Entry* metadata) const {
    std::string normalized;
    if (!clean_key('R', path, &normalized)) return false;
    const auto it = replacements_.find(normalized);
    if (it == replacements_.end()) return false;
    if (metadata) *metadata = it->second;
    if (file) *file = join_path(base_, slash(it->second.relative_payload));
    return true;
}

bool OverlayIndex::stream(const std::string& key, std::string* file) const {
    std::string normalized;
    return clean_key('S', key, &normalized) && find(streams_, normalized, file);
}

bool OverlayIndex::data(const std::string& type, const std::string& name,
                        std::string* file) const {
    std::string normalized;
    return clean_key('D', type + "/" + name, &normalized) && find(data_files_, normalized, file);
}

}  // namespace rdr2_lml
