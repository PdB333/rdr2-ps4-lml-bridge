/* fiPackfile8 vtable-slot detour planner for PS4 RDR2 1.00. See header.
 * Pure, fail-closed, no game pointer is dereferenced except through the
 * caller-supplied reader/writer callbacks.
 */
#include "rdr2_100_detour.h"
#include <string.h>

static int read_u64(LmlEbootReadRva read_rva, void* ctx, uint64_t rva,
                    uint64_t* out) {
    unsigned char bytes[8];
    int i;
    if (read_rva(ctx, rva, bytes, sizeof(bytes)) != 0) {
        return LML_DETOUR_READ_FAILED;
    }
    *out = 0;
    for (i = 0; i < 8; ++i) {
        *out |= (uint64_t)bytes[i] << (8 * i);
    }
    return LML_DETOUR_OK;
}

static int write_u64(LmlDetourWriteRva write_rva, void* ctx, uint64_t rva,
                     uint64_t value) {
    unsigned char bytes[8];
    int i;
    for (i = 0; i < 8; ++i) {
        bytes[i] = (unsigned char)(value >> (8 * i));
    }
    if (write_rva(ctx, rva, bytes, sizeof(bytes)) != 0) {
        return LML_DETOUR_WRITE_FAILED;
    }
    return LML_DETOUR_OK;
}

/* Confirm one slot holds (image_load_bias + expected_rva) and record it. */
static int confirm_slot(LmlEbootReadRva read_rva, void* ctx,
                        uint64_t image_load_bias, uint64_t vtable_rva,
                        uint32_t slot_index, uint64_t expected_rva,
                        uint64_t trampoline, LmlDetourSlot* out) {
    uint64_t slot_rva = vtable_rva + (uint64_t)slot_index * 8u;
    uint64_t live_value = 0;
    uint64_t expected_abs;
    int status = read_u64(read_rva, ctx, slot_rva, &live_value);
    if (status != LML_DETOUR_OK) {
        return status;
    }
    expected_abs = image_load_bias + expected_rva;
    if (live_value != expected_abs) {
        return LML_DETOUR_SITE_MISMATCH;
    }
    out->slot_rva = slot_rva;
    out->original_value = live_value;
    out->trampoline = trampoline;
    return LML_DETOUR_OK;
}

int lml_detour_build_plan(LmlEbootReadRva read_rva, void* ctx,
                          uint64_t image_load_bias,
                          uint32_t game_version_major,
                          uint32_t game_version_minor,
                          uint64_t trampoline_open, uint64_t trampoline_read,
                          LmlDetourPlan* out_plan) {
    LmlEbootVfsProfile profile;
    int status;
    if (!read_rva || !out_plan) {
        return LML_DETOUR_BAD_ARGUMENT;
    }
    memset(out_plan, 0, sizeof(*out_plan));
    memset(&profile, 0, sizeof(profile));

    /* Fail-closed identity + version gate (reuses the shared guard). */
    status = lml_eboot_verify_profile(read_rva, ctx, image_load_bias,
                                      game_version_major, game_version_minor,
                                      &profile);
    if (status != LML_EBOOT_PROFILE_OK) {
        return status;   /* forward the profile error verbatim */
    }

    status = confirm_slot(read_rva, ctx, image_load_bias,
                          profile.packfile8_vtable_rva, RDR2_100_VT_SLOT_OPEN,
                          profile.open_rva, trampoline_open,
                          &out_plan->open_slot);
    if (status != LML_DETOUR_OK) {
        memset(out_plan, 0, sizeof(*out_plan));
        return status;
    }
    status = confirm_slot(read_rva, ctx, image_load_bias,
                          profile.packfile8_vtable_rva, RDR2_100_VT_SLOT_READ,
                          profile.read_candidate_rva, trampoline_read,
                          &out_plan->read_slot);
    if (status != LML_DETOUR_OK) {
        memset(out_plan, 0, sizeof(*out_plan));
        return status;
    }
    out_plan->image_load_bias = image_load_bias;
    out_plan->verified = 1;
    return LML_DETOUR_OK;
}

int lml_detour_apply(LmlDetourWriteRva write_rva, void* ctx,
                     const LmlDetourPlan* plan) {
    int status;
    if (!write_rva || !plan) {
        return LML_DETOUR_BAD_ARGUMENT;
    }
    if (!plan->verified) {
        return LML_DETOUR_NOT_VERIFIED;
    }
    if (plan->open_slot.trampoline == 0 || plan->read_slot.trampoline == 0) {
        return LML_DETOUR_BAD_ARGUMENT;
    }
    status = write_u64(write_rva, ctx, plan->open_slot.slot_rva,
                       plan->open_slot.trampoline);
    if (status != LML_DETOUR_OK) {
        return status;
    }
    status = write_u64(write_rva, ctx, plan->read_slot.slot_rva,
                       plan->read_slot.trampoline);
    if (status != LML_DETOUR_OK) {
        /* best-effort rollback of the first slot */
        (void)write_u64(write_rva, ctx, plan->open_slot.slot_rva,
                        plan->open_slot.original_value);
        return status;
    }
    return LML_DETOUR_OK;
}

int lml_detour_revert(LmlDetourWriteRva write_rva, void* ctx,
                      const LmlDetourPlan* plan) {
    int status;
    if (!write_rva || !plan) {
        return LML_DETOUR_BAD_ARGUMENT;
    }
    if (!plan->verified) {
        return LML_DETOUR_NOT_VERIFIED;
    }
    status = write_u64(write_rva, ctx, plan->open_slot.slot_rva,
                       plan->open_slot.original_value);
    if (status != LML_DETOUR_OK) {
        return status;
    }
    return write_u64(write_rva, ctx, plan->read_slot.slot_rva,
                     plan->read_slot.original_value);
}
