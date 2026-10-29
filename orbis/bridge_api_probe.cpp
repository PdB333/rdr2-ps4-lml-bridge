// Host-side smoke test of the ABI that will be exported from the Orbis PRX.
#include <cstdio>
#include <cstring>
#include <string>

extern "C" int lml_bridge_abi_version();
extern "C" int lml_bridge_open(const char*, const char*);
extern "C" int lml_bridge_lookup_replace(const char*, char*, std::size_t);
extern "C" int lml_bridge_lookup_stream(const char*, char*, std::size_t);
extern "C" int lml_bridge_lookup_data(const char*, const char*, char*, std::size_t);
extern "C" int lml_bridge_get_counts(std::size_t*, std::size_t*, std::size_t*);

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string stage(argv[1]);
    const std::string map = stage + "/overlay.map";
    if (lml_bridge_abi_version() != 1) return 3;
    if (lml_bridge_open(map.c_str(), stage.c_str()) != 0) return 4;
    std::size_t r = 0, s = 0, d = 0;
    if (lml_bridge_get_counts(&r, &s, &d) != 0 || r != 8 || s != 2 || d != 4)
        return 5;
    char path[2048] = {};
    if (lml_bridge_lookup_replace(
            "UPDATE:\\COMMON\\DATA\\AI\\COMBATBEHAVIOUR.META",
            path, sizeof(path)) != 0 ||
        std::strstr(path, "combatbehaviour.meta") == nullptr)
        return 6;
    if (lml_bridge_lookup_stream("DAVID_HEAD_MERGE.YTD",
                                 path, sizeof(path)) != 0 ||
        std::strstr(path, "david_head_merge.ytd") == nullptr)
        return 7;
    if (lml_bridge_lookup_data("PED_METADATA_FILE", "metapeds_david.ymt",
                               path, sizeof(path)) != 0)
        return 8;
    if (lml_bridge_lookup_replace("update:/does/not/exist.meta",
                                  path, sizeof(path)) != -1)
        return 9;
    if (lml_bridge_lookup_replace("update:/common/data/ai/combatbehaviour.meta",
                                  path, 3) != -3)
        return 10;
    std::puts("LML_BRIDGE_C_ABI_HOST_TEST_PASSED");
    return 0;
}
