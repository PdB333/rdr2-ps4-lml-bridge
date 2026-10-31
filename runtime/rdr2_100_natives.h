#ifndef LML_RDR2_100_NATIVES_H
#define LML_RDR2_100_NATIVES_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* RAGE script-native invoker core for PS4 RDR2 1.00.
 *
 * inspect_rage_natives.py proves that each native's HANDLER address is static
 * in the EBOOT, so a known native resolves to (image_load_bias + handler_rva)
 * with no runtime walk of the registration list. This core turns that fact
 * into a call primitive, kept injectable and fail-closed:
 *
 *   - It builds a scrNativeCallContext (argument marshalling), resolves the
 *     handler address, and invokes it THROUGH a caller-supplied function
 *     pointer. The core never contains a hardcoded indirect call into game
 *     code, so it is testable off-console.
 *   - invoke() refuses unless the caller passes abi_verified = 1. The
 *     NativeContext layout below is the ScriptHook/PC candidate and is
 *     UNVERIFIED for PS4 1.00 until exercised on a running process.
 *
 * Only a tiny bring-up table of already-verified natives is embedded here;
 * the full hash->handler map stays in a local file produced by the Python
 * tool and is never compiled in or committed.
 */

#define RDR2_NATIVE_ABI_VERSION 1u
#define RDR2_NATIVE_MAX_ARGS 32u

enum Rdr2NativeStatus {
    RDR2_NATIVE_OK = 0,
    RDR2_NATIVE_BAD_ARGUMENT = -2,
    RDR2_NATIVE_UNKNOWN_HASH = -3,
    RDR2_NATIVE_RANGE = -4,          /* resolved address out of a sane range */
    RDR2_NATIVE_ABI_UNVERIFIED = -5, /* invoke before the ABI is confirmed   */
    RDR2_NATIVE_TOO_MANY_ARGS = -6
};

/* scrNativeCallContext candidate (UNVERIFIED on PS4 1.00). */
typedef struct Rdr2NativeContext {
    void* return_value;                     /* +0x00 */
    uint32_t arg_count;                     /* +0x08 */
    uint32_t data_count;                    /* +0x0C */
    uint64_t args[RDR2_NATIVE_MAX_ARGS];    /* +0x10 */
    uint64_t result_slot;                   /* backing store for return_value */
} Rdr2NativeContext;

/* The handler receives a pointer to the call context (classic RAGE ABI).
 * The caller provides the real one; the core only hands it the address. */
typedef void (*Rdr2NativeHandlerFn)(Rdr2NativeContext* ctx);
typedef void (*Rdr2NativeInvokerFn)(uint64_t handler_addr,
                                    Rdr2NativeContext* ctx);

#if defined(__GNUC__) || defined(__clang__)
#define RDR2_NATIVE_EXPORT __attribute__((visibility("default")))
#else
#define RDR2_NATIVE_EXPORT
#endif

/* Context marshalling (ScriptHook nativeInit / nativePush style). */
RDR2_NATIVE_EXPORT void rdr2_native_reset(Rdr2NativeContext* ctx);
RDR2_NATIVE_EXPORT int rdr2_native_push_u64(Rdr2NativeContext* ctx,
                                            uint64_t value);
RDR2_NATIVE_EXPORT int rdr2_native_push_ptr(Rdr2NativeContext* ctx,
                                            void* pointer);
RDR2_NATIVE_EXPORT uint64_t rdr2_native_result_u64(const Rdr2NativeContext* ctx);

/* Bring-up table of verified natives (hash -> handler RVA). */
RDR2_NATIVE_EXPORT int rdr2_native_lookup_known(uint64_t hash,
                                                uint64_t* out_rva);

/* handler_rva + image_load_bias with overflow / zero / range checks. */
RDR2_NATIVE_EXPORT int rdr2_native_resolve(uint64_t image_load_bias,
                                           uint64_t handler_rva,
                                           uint64_t* out_addr);

/* Invoke handler_addr(ctx) through `invoker`. Refuses unless abi_verified. */
RDR2_NATIVE_EXPORT int rdr2_native_invoke(uint64_t handler_addr,
                                          Rdr2NativeContext* ctx,
                                          Rdr2NativeInvokerFn invoker,
                                          int abi_verified);

#ifdef __cplusplus
}
#endif
#endif
