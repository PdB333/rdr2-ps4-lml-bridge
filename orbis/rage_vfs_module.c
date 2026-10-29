// RDR2 PS4/Orbis RAGE VFS adapter module.
//
// Provides a fully linked, read-only replacement byte stream API with
// passthrough to the caller's ORIGINAL fiDevice/RPF8 callbacks.
// Does NOT install a game detour: the exact RDR2 PS4 1.32 VFS callsite,
// trampoline and ABI must be verified against the game's own eboot first.
#include <orbis/libkernel.h>
#include <stdint.h>
#include <stddef.h>
#include "../runtime/rage_vfs_redirect.h"

#ifndef LML_VFS_MAP_PATH
#define LML_VFS_MAP_PATH "/data/etaHEN/lml_bridge/overlay.map"
#endif
#ifndef LML_VFS_PAYLOAD_ROOT
#define LML_VFS_PAYLOAD_ROOT "/data/etaHEN/lml_bridge"
#endif

#define EXPORT __attribute__((visibility("default"), used))

__attribute__((section(".data.sce_module_param"), aligned(8), used))
static const uint64_t lml_rage_module_parameter[3] = {
    0x18u, 0x13C13F4BFULL, 0x1000051u
};

extern void (*__init_array_start[])(void);
extern void (*__init_array_end[])(void);

/* Required runtime anchors for OpenOrbis libc++ static initialization. */
__attribute__((visibility("hidden"))) void* __dso_handle = 0;
__attribute__((visibility("hidden"))) void* _sceLibc = 0;

static volatile int initialized = 0;
static int last_index_status = LML_RAGE_NO_BACKEND;

static void trace(const char* message) {
    (void)sceKernelDebugOutText(0, message);
}

EXPORT int _init(void) {
    return 0;
}

EXPORT int32_t module_start(int64_t args, const void* argp) {
    void (**constructor)(void);
    (void)args;
    (void)argp;
    if (initialized) return 0;
    initialized = 1;
    trace("[LML-RAGE-VFS] MODULE_ENTRY RDR2-PS4-1.32\n");
    for (constructor = __init_array_start;
         constructor != __init_array_end; ++constructor) {
        if (*constructor) (*constructor)();
    }
    if (lml_rage_abi_version() != LML_RAGE_ABI_VERSION) {
        trace("[LML-RAGE-VFS] ABI_MISMATCH; GAME_UNMODIFIED\n");
        return 0;
    }
    last_index_status = lml_rage_load_overlay(
        LML_VFS_MAP_PATH, LML_VFS_PAYLOAD_ROOT);
    if (last_index_status == LML_RAGE_OK) {
        trace("[LML-RAGE-VFS] MAP_READY; GAME_HOOK_NOT_INSTALLED\n");
    } else {
        trace("[LML-RAGE-VFS] MAP_MISSING_OR_INVALID; GAME_UNMODIFIED\n");
    }
    /* Intentionally NO detour installation here: PS4 game fiDevice
     * addresses and calling convention have not been verified.
     */
    return 0;
}

EXPORT int32_t module_stop(int64_t args, const void* argp) {
    (void)args;
    (void)argp;
    (void)lml_rage_clear();
    trace("[LML-RAGE-VFS] MODULE_STOP\n");
    return 0;
}

EXPORT int lml_rage_module_index_status(void) {
    return last_index_status;
}

/* This stays zero until a title-verified fiDevice adapter is written.
 * Never claim successful resource replacement from merely loading a PRX. */
EXPORT int lml_rage_game_hook_installed(void) {
    return 0;
}

EXPORT int _fini(void) {
    return 0;
}
