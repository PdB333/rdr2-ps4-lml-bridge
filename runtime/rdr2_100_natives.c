/* RAGE script-native invoker core for PS4 RDR2 1.00. See header.
 * Pure and fail-closed: resolves static handler addresses and calls them only
 * through a caller-supplied invoker, and only once the ABI is declared verified.
 */
#include "rdr2_100_natives.h"
#include <string.h>

/* Verified against the 1.00 EBOOT by inspect_rage_natives.py. These are the
 * only handler RVAs confirmed by hand so far; the complete map is generated
 * locally and never compiled in. */
static const struct KnownNative {
    uint64_t hash;
    uint64_t handler_rva;
} kKnownNatives[] = {
    {UINT64_C(0x15D757606D170C3C), UINT64_C(0x01AAA210)}, /* GET_ENTITY_MAX_HEALTH */
    {UINT64_C(0x0F2A2175734926D8), UINT64_C(0x01A645D0)}, /* STOP_SOUND_FRONTEND   */
    {UINT64_C(0x67C540AA08E4A6F5), UINT64_C(0x01A643F0)}, /* PLAY_SOUND_FRONTEND   */
};

/* The game image is well under this; a resolved handler beyond it is a bug. */
#define RDR2_NATIVE_MAX_IMAGE_SPAN UINT64_C(0x10000000)
/* User-space canonical ceiling; reject obviously bogus bias/handler sums. */
#define RDR2_NATIVE_ADDR_CEILING (UINT64_C(1) << 47)

void rdr2_native_reset(Rdr2NativeContext* ctx) {
    if (!ctx) {
        return;
    }
    memset(ctx, 0, sizeof(*ctx));
    ctx->return_value = &ctx->result_slot;
}

int rdr2_native_push_u64(Rdr2NativeContext* ctx, uint64_t value) {
    if (!ctx) {
        return RDR2_NATIVE_BAD_ARGUMENT;
    }
    if (ctx->arg_count >= RDR2_NATIVE_MAX_ARGS) {
        return RDR2_NATIVE_TOO_MANY_ARGS;
    }
    ctx->args[ctx->arg_count++] = value;
    return RDR2_NATIVE_OK;
}

int rdr2_native_push_ptr(Rdr2NativeContext* ctx, void* pointer) {
    return rdr2_native_push_u64(ctx, (uint64_t)(uintptr_t)pointer);
}

uint64_t rdr2_native_result_u64(const Rdr2NativeContext* ctx) {
    if (!ctx) {
        return 0;
    }
    return ctx->result_slot;
}

int rdr2_native_lookup_known(uint64_t hash, uint64_t* out_rva) {
    size_t i;
    if (!out_rva) {
        return RDR2_NATIVE_BAD_ARGUMENT;
    }
    for (i = 0; i < sizeof(kKnownNatives) / sizeof(kKnownNatives[0]); ++i) {
        if (kKnownNatives[i].hash == hash) {
            *out_rva = kKnownNatives[i].handler_rva;
            return RDR2_NATIVE_OK;
        }
    }
    *out_rva = 0;
    return RDR2_NATIVE_UNKNOWN_HASH;
}

int rdr2_native_resolve(uint64_t image_load_bias, uint64_t handler_rva,
                        uint64_t* out_addr) {
    uint64_t addr;
    if (!out_addr) {
        return RDR2_NATIVE_BAD_ARGUMENT;
    }
    *out_addr = 0;
    if (handler_rva == 0 || handler_rva >= RDR2_NATIVE_MAX_IMAGE_SPAN) {
        return RDR2_NATIVE_RANGE;
    }
    if (image_load_bias > RDR2_NATIVE_ADDR_CEILING - handler_rva) {
        return RDR2_NATIVE_RANGE;   /* overflow / impossible bias */
    }
    addr = image_load_bias + handler_rva;
    if (addr == 0 || addr >= RDR2_NATIVE_ADDR_CEILING) {
        return RDR2_NATIVE_RANGE;
    }
    *out_addr = addr;
    return RDR2_NATIVE_OK;
}

int rdr2_native_invoke(uint64_t handler_addr, Rdr2NativeContext* ctx,
                       Rdr2NativeInvokerFn invoker, int abi_verified) {
    if (!ctx || !invoker || handler_addr == 0) {
        return RDR2_NATIVE_BAD_ARGUMENT;
    }
    if (abi_verified != 1) {
        /* Honour the owner's rule: no call into the game until the native
         * calling convention has been validated on a running 1.00 process. */
        return RDR2_NATIVE_ABI_UNVERIFIED;
    }
    if (ctx->return_value == NULL) {
        ctx->return_value = &ctx->result_slot;
    }
    invoker(handler_addr, ctx);
    return RDR2_NATIVE_OK;
}
