#ifndef RDR2_100_PACK_TRACE_H
#define RDR2_100_PACK_TRACE_H
#include <stddef.h>
#include <stdint.h>
#include "rage_eboot_profile.h"
#include "rdr2_100_registry.h"
#ifdef __cplusplus
extern "C" {
#endif

/* RDR2 PS4 base version 1.00 ONLY. This is a per-object READ-ONLY TRACE
 * of virtual Open; it calls the ORIGINAL once and never substitutes
 * a RAGE handle. No game code page or global vtable is modified.
 * The user/loader must keep the device ALIVE and quiesce engine threads
 * for attach/detach; a checked EBOOT is not a substitute for that lock.
 */
#define RDR2_100_PACK_VTABLE_RVA UINT64_C(0x066B00F8)
#define RDR2_100_PACK_OPEN_RVA UINT64_C(0x0452A480)
#define RDR2_100_PACK_OPEN_SLOT 2u
#define RDR2_100_PACK_VTABLE_SLOTS 112u
#define RDR2_100_PACK_VTABLE_FNV64 UINT64_C(0x8EAECB696678DAD0)
typedef uint64_t (*Rdr2_100PackOpenFn)(void *self, const char *path,
                                       uint8_t read_flag);
typedef void (*Rdr2_100PackTraceFn)(void *context, const char *path,
                                    uint8_t read_flag);
typedef struct Rdr2_100PackPreflight {
    uint64_t expected_vptr;
    uint64_t expected_open;
    uint64_t vtable_fingerprint;
    uint32_t vtable_methods;
    uint32_t reserved;
} Rdr2_100PackPreflight;

enum Rdr2_100TraceStatus {
    RDR2_100_TRACE_OK = 0,
    RDR2_100_TRACE_BAD_ARGUMENT = -2,
    RDR2_100_TRACE_UNSUPPORTED_PATCH = -3,
    RDR2_100_TRACE_PROFILE_MISMATCH = -4,
    RDR2_100_TRACE_BUSY = -5,
    RDR2_100_TRACE_STALE_INSTANCE = -6,
    RDR2_100_TRACE_UNMAPPED = -7,
    RDR2_100_TRACE_ALREADY_USED = -8,
    RDR2_100_TRACE_NOT_ATTACHED = -9
};

#if defined(__GNUC__) || defined(__clang__)
#define RDR2_100_EXPORT __attribute__((visibility("default")))
#else
#define RDR2_100_EXPORT
#endif

/* Static EBOOT identity and ALL 112 virtual method pointers.
 * read_rva must reject unmapped game-memory ranges. No writes performed;
 * wrong version is refused before the FIRST read.
 */
RDR2_100_EXPORT int rdr2_100_pack_preflight(
    Rdr2_100ReadAbsolute read_rva, void *reader_context,
    uint32_t game_major, uint32_t game_minor, uint64_t image_base,
    Rdr2_100PackPreflight *out);

/* Call from a game-lifecycle-safe point, with the device pinned/alive.
 * read_absolute must validate the object's readable address; this verifies
 * the live object vptr before doing the single atomic pointer swap.
 * At most ONE attachment per PRX lifetime (even after detaching) so a stale
 * cached game call cannot reference a reused shadow vtable. To unload the
 * module after attach, the caller must additionally ensure there are no
 * stale virtual function pointers, which cannot be proven by this bridge.
 */
RDR2_100_EXPORT int rdr2_100_pack_trace_attach_checked(
    void *live_device, uint32_t game_major, uint32_t game_minor,
    uint64_t image_base, Rdr2_100ReadAbsolute read_rva,
    Rdr2_100ReadAbsolute read_absolute, void *reader_context,
    Rdr2_100PackTraceFn trace_callback, void *trace_context);

RDR2_100_EXPORT int rdr2_100_pack_trace_detach(void *live_device);
RDR2_100_EXPORT int rdr2_100_pack_trace_is_attached(void *live_device);
RDR2_100_EXPORT uint64_t rdr2_100_pack_trace_open_calls(void);
RDR2_100_EXPORT uint32_t rdr2_100_pack_trace_active_calls(void);
/* Returns false forever after the first successful attach because a game
 * caller may retain a pointer to the former method. Keep PRX resident. */
RDR2_100_EXPORT int rdr2_100_pack_trace_may_unload(void);

#ifdef RDR2_100_HOST_TEST
/* ONLY in host-test binary. Not present in Orbis PRX.
 * Bypasses game EBOOT validation to exercise the shadow table using
 * synthetic vtables and fake original functions.
 */
int rdr2_100_pack_trace_host_fixture_attach(
    void *synthetic_device, void *expected_vptr,
    Rdr2_100PackOpenFn original_open,
    Rdr2_100PackTraceFn callback, void *callback_context);
#endif
#ifdef __cplusplus
}
#endif
#endif
