#include "overlay_index.hpp"

#include <iostream>
#include <string>

// Host-side test harness only. Never inject this executable into a game.
int main(int argc, char** argv) {
    if (argc < 3 || (std::string(argv[2]) != "stats" && argc < 4)) {
        std::cerr << "Usage: overlay_probe <staging-dir> <replace|stream|data|stats> "
                     "[virtual-path] [data-type]\n";
        return 2;
    }
    const std::string root = argv[1], action = argv[2];
    rdr2_lml::OverlayIndex overlays;
    std::string error;
    if (!overlays.load(root + "/overlay.map", root, &error)) {
        std::cerr << error << "\n";
        return 2;
    }
    if (action == "stats") {
        std::cout << "replacements=" << overlays.replacement_count()
                  << " streaming=" << overlays.stream_count()
                  << " data=" << overlays.data_count() << "\n";
        return 0;
    }
    const std::string key = argv[3];
    std::string result;
    bool exists = false;
    if (action == "replace") exists = overlays.replacement(key, &result);
    else if (action == "stream") exists = overlays.stream(key, &result);
    else if (action == "data" && argc >= 5) exists = overlays.data(argv[4], key, &result);
    else {
        std::cerr << "Unknown action or missing data type\n";
        return 2;
    }
    if (!exists) {
        std::cout << "NOT_FOUND\n";
        return 3;
    }
    std::cout << result << "\n";
    return 0;
}
