// OpenOrbis PS4/Orbis module entrypoint for the independent LML resolver.
// Explicitly exports module_start (unlike the stock hidden CRT), initializes
// the constructors used by C++17, and attempts to read a map on startup.
// No game symbol resolution, process patching, or RAGE/RPF interception.
#include <orbis/libkernel.h>
#include <stdint.h>
#include <stddef.h>

#ifndef LML_RUNTIME_MAP_PATH
#define LML_RUNTIME_MAP_PATH "/data/etaHEN/lml_bridge/overlay.map"
#endif
#ifndef LML_RUNTIME_PAYLOAD_ROOT
#define LML_RUNTIME_PAYLOAD_ROOT "/data/etaHEN/lml_bridge"
#endif

#define LML_EXPORT __attribute__((visibility("default"), used))

// PS4 module metadata equivalent to the public OpenOrbis CRT declaration.
__attribute__((section(".data.sce_module_param"), aligned(8), used))
static const uint64_t lml_module_param[3] = {
    0x18u, 0x13C13F4BFULL, 0x1000051u
};

// OpenOrbis's linker script supplies these labels at init_array boundaries.
extern void (*__init_array_start[])(void);
extern void (*__init_array_end[])(void);

// Required by C++ destructor/RTTI runtime used by OpenOrbis libc++.
__attribute__((visibility("hidden"))) void* __dso_handle = 0;
__attribute__((visibility("hidden"))) void* _sceLibc = 0;

extern int lml_bridge_open(const char* map, const char* root);
extern int lml_bridge_get_counts(size_t* replacements,
                                 size_t* streams, size_t* data);
extern int lml_bridge_abi_version(void);

static volatile int lml_initialized = 0;
static int lml_last_result = -4;

static void log_status(const char* line) {
    (void)sceKernelDebugOutText(0, line);
}

static size_t append_text(char* out, size_t pos, size_t cap, const char* text) {
    while (*text && pos + 1 < cap) out[pos++] = *text++;
    out[pos] = 0;
    return pos;
}

static size_t append_uint(char* out, size_t pos, size_t cap, size_t number) {
    char reverse[24];
    size_t used = 0;
    do {
        reverse[used++] = (char)('0' + (number % 10));
        number /= 10;
    } while (number && used < sizeof(reverse));
    while (used && pos + 1 < cap) out[pos++] = reverse[--used];
    out[pos] = 0;
    return pos;
}

static void log_counts(size_t r, size_t s, size_t d) {
    char text[128];
    size_t pos = 0;
    pos = append_text(text, pos, sizeof(text), "[LML-ORBI-RUNTIME] MAP_LOADED R=");
    pos = append_uint(text, pos, sizeof(text), r);
    pos = append_text(text, pos, sizeof(text), " S=");
    pos = append_uint(text, pos, sizeof(text), s);
    pos = append_text(text, pos, sizeof(text), " D=");
    pos = append_uint(text, pos, sizeof(text), d);
    (void)append_text(text, pos, sizeof(text), "\n");
    log_status(text);
}

LML_EXPORT int _init(void) {
    // The module loader can run this entrypoint before calling module_start.
    // Constructors and disk IO happen only in module_start below.
    return 0;
}

LML_EXPORT int32_t module_start(int64_t args, const void* argp) {
    void (**constructor)(void);
    size_t r = 0, s = 0, d = 0;
    (void)args;
    (void)argp;
    if (lml_initialized) return 0;
    lml_initialized = 1;
    log_status("[LML-ORBI-RUNTIME] MODULE_ENTRY RDR2-PS4-1.32\n");

    for (constructor = __init_array_start;
         constructor != __init_array_end; ++constructor) {
        if (*constructor) (*constructor)();
    }

    if (lml_bridge_abi_version() != 1) {
        log_status("[LML-ORBI-RUNTIME] ABI_MISMATCH\n");
        return 0;
    }

    lml_last_result = lml_bridge_open(LML_RUNTIME_MAP_PATH,
                                      LML_RUNTIME_PAYLOAD_ROOT);
    if (lml_last_result == 0 &&
        lml_bridge_get_counts(&r, &s, &d) == 0) {
        log_counts(r, s, d);
    } else {
        log_status("[LML-ORBI-RUNTIME] MAP_UNAVAILABLE_OR_INVALID\n");
    }
    // Missing data is never fatal to game startup.
    return 0;
}

LML_EXPORT int32_t module_stop(int64_t args, const void* argp) {
    (void)args;
    (void)argp;
    log_status("[LML-ORBI-RUNTIME] MODULE_STOP\n");
    return 0;
}

LML_EXPORT int lml_runtime_last_init_result(void) {
    return lml_last_result;
}

LML_EXPORT int _fini(void) { return 0; }
