/* Offline unit tests for the RAGE native invoker core (no game, no console). */
#include "rdr2_100_natives.h"
#include <stdint.h>
#include <stdio.h>

static int g_invoked;

static void fake_invoker(uint64_t handler_addr, Rdr2NativeContext* ctx) {
    g_invoked = 1;
    /* Prove the context and address reach the callee and a result returns. */
    ctx->result_slot = ctx->args[0] + handler_addr;
}

#define ASSERT(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL at line %d: %s\n", __LINE__, #condition); \
    return 3; } } while (0)

int main(void) {
    Rdr2NativeContext ctx;
    uint64_t rva = 0, addr = 0;
    uint32_t i;

    /* reset + marshalling */
    rdr2_native_reset(&ctx);
    ASSERT(ctx.arg_count == 0);
    ASSERT(ctx.return_value == &ctx.result_slot);
    ASSERT(rdr2_native_push_u64(&ctx, 0x1111) == RDR2_NATIVE_OK);
    ASSERT(rdr2_native_push_ptr(&ctx, &ctx) == RDR2_NATIVE_OK);
    ASSERT(ctx.arg_count == 2);
    ASSERT(ctx.args[0] == 0x1111);
    ASSERT(ctx.args[1] == (uint64_t)(uintptr_t)&ctx);
    ASSERT(rdr2_native_push_u64(NULL, 0) == RDR2_NATIVE_BAD_ARGUMENT);

    /* overflow past the fixed argument capacity */
    rdr2_native_reset(&ctx);
    for (i = 0; i < RDR2_NATIVE_MAX_ARGS; ++i) {
        ASSERT(rdr2_native_push_u64(&ctx, i) == RDR2_NATIVE_OK);
    }
    ASSERT(rdr2_native_push_u64(&ctx, 999) == RDR2_NATIVE_TOO_MANY_ARGS);

    /* known-native bring-up table */
    ASSERT(rdr2_native_lookup_known(UINT64_C(0x15D757606D170C3C), &rva) ==
           RDR2_NATIVE_OK && rva == UINT64_C(0x01AAA210));
    ASSERT(rdr2_native_lookup_known(UINT64_C(0x67C540AA08E4A6F5), &rva) ==
           RDR2_NATIVE_OK && rva == UINT64_C(0x01A643F0));
    ASSERT(rdr2_native_lookup_known(UINT64_C(0xDEADBEEFDEADBEEF), &rva) ==
           RDR2_NATIVE_UNKNOWN_HASH && rva == 0);

    /* static resolution = bias + rva, with range guards */
    ASSERT(rdr2_native_resolve(UINT64_C(0x400000), UINT64_C(0x01AAA210),
                               &addr) == RDR2_NATIVE_OK);
    ASSERT(addr == UINT64_C(0x400000) + UINT64_C(0x01AAA210));
    ASSERT(rdr2_native_resolve(0, 0, &addr) == RDR2_NATIVE_RANGE);
    ASSERT(rdr2_native_resolve(0, UINT64_C(0x20000000), &addr) ==
           RDR2_NATIVE_RANGE);
    ASSERT(rdr2_native_resolve(UINT64_MAX, UINT64_C(0x1000), &addr) ==
           RDR2_NATIVE_RANGE);

    /* invoke is fail-closed until the ABI is declared verified */
    rdr2_native_reset(&ctx);
    (void)rdr2_native_push_u64(&ctx, 0x20);
    g_invoked = 0;
    ASSERT(rdr2_native_invoke(0x500000, &ctx, fake_invoker, 0) ==
           RDR2_NATIVE_ABI_UNVERIFIED);
    ASSERT(g_invoked == 0);  /* no call into "game code" when unverified */
    ASSERT(rdr2_native_invoke(0x500000, &ctx, NULL, 1) ==
           RDR2_NATIVE_BAD_ARGUMENT);
    ASSERT(rdr2_native_invoke(0, &ctx, fake_invoker, 1) ==
           RDR2_NATIVE_BAD_ARGUMENT);

    /* verified path actually dispatches and returns a result */
    g_invoked = 0;
    ASSERT(rdr2_native_invoke(0x500000, &ctx, fake_invoker, 1) ==
           RDR2_NATIVE_OK);
    ASSERT(g_invoked == 1);
    ASSERT(rdr2_native_result_u64(&ctx) == 0x20 + 0x500000);

    puts("RDR2_100_NATIVE_INVOKER_TESTS_PASSED");
    return 0;
}
