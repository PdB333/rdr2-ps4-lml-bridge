// Minimal PS4/Orbis loader smoke probe, independent of LML proprietary code.
// No RDR2 API, no hooks, no C++ runtime. OpenOrbis CRT supplies module_start.
__attribute__((visibility("default"), used))
const char* lml_probe_identity(void) {
    return "RDR2_PS4_132_PS5_1360_LML_LOADER_SMOKE_V1";
}
__attribute__((visibility("default"), used))
int lml_probe_abi_version(void) {
    return 1;
}
