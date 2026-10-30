/* RDR2 PS4 1.00 fiPackfile8 read-only trace module for Orbis/PS5.
 * Shipping mode: PASSIVE. Does not inspect live memory, arm a hook or
 * patch a vtable on startup. A future verified game-lifecycle adapter can
 * call rdr2_100_pack_trace_attach_checked after all preflight checks.
 */
#include <stdint.h>
#include <orbis/libkernel.h>
#include "../runtime/rdr2_100_pack_trace.h"

#define EXPORT __attribute__((visibility("default"),used))
__attribute__((section(".data.sce_module_param"),aligned(8),used))
static const uint64_t lml_sce_module_parameter[3]={
    UINT64_C(0x18),UINT64_C(0x13C13F4BF),UINT64_C(0x1000051)
};
extern void (*__init_array_start[])(void);
extern void (*__init_array_end[])(void);
__attribute__((visibility("hidden"))) void* __dso_handle=0;
__attribute__((visibility("hidden"))) void* _sceLibc=0;
static int started=0;
static void log_line(const char* text) {
    (void)sceKernelDebugOutText(0,text);
}
EXPORT int _init(void) {return 0;}
EXPORT int _fini(void) {return 0;}
EXPORT int32_t module_start(int64_t argc,const void* argv) {
    void (**ctor)(void);
    (void)argc;(void)argv;
    if(started)return 0;
    started=1;
    for(ctor=__init_array_start;ctor!=__init_array_end;++ctor)
        if(*ctor)(*ctor)();
    log_line("[LML-100-TRACE] MODULE_ENTRY PS4-1.00; PASSIVE_NO_GAME_HOOK\n");
    return 0;
}
EXPORT int32_t module_stop(int64_t argc,const void* argv) {
    (void)argc;(void)argv;
    if(!rdr2_100_pack_trace_may_unload()){
        /* Even a detached vptr can have stale cached virtual functions.
         * Returning an error asks the loader to keep the module resident;
         * loader-specific behavior MUST still be verified on console. */
        log_line("[LML-100-TRACE] REFUSE_UNLOAD_AFTER_ATTACH\n");
        return -1;
    }
    log_line("[LML-100-TRACE] MODULE_STOP_SAFE\n");
    return 0;
}
EXPORT uint32_t lml_rdr2_100_trace_abi_version(void) {return 1u;}
EXPORT int lml_rdr2_100_trace_autohook_installed(void) {return 0;}
