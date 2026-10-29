#pragma once

// Clean-room portable LML overlay lookup table.
// Does not hook RDR2, parse RPF archives, or install a PS4 PRX.
#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>

namespace rdr2_lml {

struct Entry {
    std::string key;
    std::string relative_payload;
    std::string sha256;
    std::uint64_t byte_length = 0;
};

class OverlayIndex {
public:
    // Reads an offline-compiled overlay.map and checks payload file sizes.
    // The caller owns all paths. No game process memory is accessed.
    bool load(const std::string& overlay_map,
              const std::string& payload_root,
              std::string* error = nullptr);

    // A replacement is a fully qualified RDR2 archive path, e.g.
    // "update:/common/data/ai/combatbehaviour.meta".
    bool replacement(const std::string& game_path, std::string* file) const;
    // Returns the precise manifest size and path for safe read-through.
    // Caller must check the current physical file size again before use.
    bool replacement_metadata(const std::string& game_path,
                              std::string* file, Entry* metadata) const;

    // Stream and data names are registration requests, not replacements.
    // A game-specific host must still register their contents with RDR2.
    bool stream(const std::string& asset_name, std::string* file) const;
    bool data(const std::string& data_type,
              const std::string& asset_name, std::string* file) const;

    std::size_t replacement_count() const { return replacements_.size(); }
    std::size_t stream_count() const { return streams_.size(); }
    std::size_t data_count() const { return data_files_.size(); }

private:
    std::string base_;
    std::unordered_map<std::string, Entry> replacements_;
    std::unordered_map<std::string, Entry> streams_;
    std::unordered_map<std::string, Entry> data_files_;
    bool find(const std::unordered_map<std::string, Entry>& table,
              const std::string& key, std::string* file) const;
};

}  // namespace rdr2_lml
