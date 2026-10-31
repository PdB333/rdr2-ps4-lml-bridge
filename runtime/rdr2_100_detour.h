#ifndef LML_RDR2_100_DETOUR_H
#define LML_RDR2_100_DETOUR_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* fiPackfile8 vtable-slot detour PLANNER for PS4 RDR2 1.00 ONLY.
 *
 * The detour redirects resource reads by swapping the fiPackfile8 vtable
 * SLOT POINTERS (Open, Read) for our trampolines, keeping the originals so the
 * hook body can read-through. It is a pointer swap in the class vtable, NOT an
 * inline code patch and NOT a guessed address.
 *
 * Fail-closed and injectable, exactly like lml_eboot_verify_profile:
 *   - build_plan() first calls lml_eboot_verify_profile; any non-OK result is
 *     forwarded and no plan is produced.
 *   - It then reads each target vtable slot and REQUIRES it to still hold the
 *     verified original (image_load_bias + open_rva / read_candidate_rva).
 *     A mismatch aborts: we never patch an address we did not confirm.
 *   - apply()/revert() write game memory and therefore refuse unless the plan
 *     is marked verified. The vtable lives in RELRO, so the caller's writer
 *     must handle page protection on console; this core only computes bytes.
 *
 * Nothing here executes on a game until a running 1.00 process is confirmed.
 */

#include "rage_eboot_profile.h"

/* The Open/Read handlers sit at these vtable slot indices (verified by RTTI
 * in inspect_rdr2_eboot: slot 2 = open_path, slot 13 = read). */
#define RDR2_100_VT_SLOT_OPEN 2u
#define RDR2_100_VT_SLOT_READ 13u

typedef int (*LmlDetourWriteRva)(void* ctx, uint64_t rva, const void* src,
                                 size_t size);

enum LmlDetourStatus {
    LML_DETOUR_OK = 0,
    LML_DETOUR_BAD_ARGUMENT = -2,
    LML_DETOUR_READ_FAILED = -3,
    LML_DETOUR_SITE_MISMATCH = -4,   /* slot no longer holds the verified ptr */
    LML_DETOUR_NOT_VERIFIED = -5,    /* apply/revert before a verified plan   */
    LML_DETOUR_WRITE_FAILED = -6
};

typedef struct LmlDetourSlot {
    uint64_t slot_rva;        /* vtable slot address (image-relative)         */
    uint64_t original_value;  /* absolute handler currently in the slot       */
    uint64_t trampoline;      /* absolute address we would install            */
} LmlDetourSlot;

typedef struct LmlDetourPlan {
    int verified;             /* 1 only after a clean build_plan              */
    uint64_t image_load_bias;
    LmlDetourSlot open_slot;
    LmlDetourSlot read_slot;
} LmlDetourPlan;

#if defined(__GNUC__) || defined(__clang__)
#define LML_DETOUR_EXPORT __attribute__((visibility("default")))
#else
#define LML_DETOUR_EXPORT
#endif

/* Verify the 1.00 profile, confirm the live vtable slots, and fill out_plan.
 * trampoline_* are the absolute addresses of the caller's hook functions
 * (0 is allowed only when building a dry-run plan with no apply intent). */
LML_DETOUR_EXPORT int lml_detour_build_plan(
    LmlEbootReadRva read_rva, void* ctx, uint64_t image_load_bias,
    uint32_t game_version_major, uint32_t game_version_minor,
    uint64_t trampoline_open, uint64_t trampoline_read,
    LmlDetourPlan* out_plan);

/* Install the slot swaps. Refuses unless out_plan->verified and both
 * trampolines are non-zero. Writes exactly two 8-byte pointers. */
LML_DETOUR_EXPORT int lml_detour_apply(LmlDetourWriteRva write_rva, void* ctx,
                                       const LmlDetourPlan* plan);

/* Restore the saved originals. Refuses unless the plan is verified. */
LML_DETOUR_EXPORT int lml_detour_revert(LmlDetourWriteRva write_rva, void* ctx,
                                        const LmlDetourPlan* plan);

#ifdef __cplusplus
}
#endif
#endif
