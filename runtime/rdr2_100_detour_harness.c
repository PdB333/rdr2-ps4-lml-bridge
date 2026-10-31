/* Offline unit tests for the fiPackfile8 vtable-slot detour planner.
 * Serves the same synthetic 1.00 profile as the EBOOT guard harness, plus a
 * writable overlay for the two patched slots. No game binary is required.
 */
#include "rdr2_100_detour.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const unsigned char kType[] = "N4rage11fiPackfile8E";
static const struct Entry {
    uint64_t rva;
    unsigned char prefix[16];
} kEntries[] = {
    {0x0452A480ULL, {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,
                     0x41,0x55,0x41,0x54,0x53,0x48,0x83,0xec}},
    {0x0452A780ULL, {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,
                     0x41,0x54,0x53,0x49,0x89,0xd6,0x31,0xd2}},
    {0x0452B9D0ULL, {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,
                     0x41,0x55,0x41,0x54,0x53,0x50,0x48,0x89}},
    {0x0452BA60ULL, {0x48,0x8b,0x47,0x10,0x48,0x8b,0x77,0x20,
                     0x48,0x8b,0x38,0x4c,0x8b,0x4f,0x70,0x48}}
};
static const struct Slot {
    uint64_t rva;
    uint64_t value;
} kVtable[] = {
    {0x066B00F0ULL, 0x066B0480ULL},
    {0x066B00F8ULL, 0x0452A380ULL},
    {0x066B0100ULL, 0x0452A3F0ULL},
    {0x066B0108ULL, 0x0452A480ULL},  /* slot 2: Open  */
    {0x066B0128ULL, 0x0452A780ULL},
    {0x066B0160ULL, 0x0452B9D0ULL},  /* slot 13: Read */
    {0x066B0168ULL, 0x0452BA60ULL},
};

#define OPEN_SLOT_RVA 0x066B0108ULL
#define READ_SLOT_RVA 0x066B0160ULL

typedef struct Mem {
    int corrupt_open;        /* break the Open slot -> SITE_MISMATCH */
    int deny_write;
    uint64_t open_live;      /* writable overlay for the two slots   */
    uint64_t read_live;
    int have_overlay;
} Mem;

static int read_rva(void* user, uint64_t rva, void* out, size_t length) {
    Mem* m = (Mem*)user;
    unsigned char* bytes = (unsigned char*)out;
    size_t i, j;
    if (!m) return -1;
    if (m->have_overlay && length == 8 && rva == OPEN_SLOT_RVA) {
        for (j = 0; j < 8; ++j) bytes[j] = (unsigned char)(m->open_live >> (8*j));
        return 0;
    }
    if (m->have_overlay && length == 8 && rva == READ_SLOT_RVA) {
        for (j = 0; j < 8; ++j) bytes[j] = (unsigned char)(m->read_live >> (8*j));
        return 0;
    }
    if (rva == 0x05D7DE40ULL && length == sizeof(kType)) {
        memcpy(out, kType, sizeof(kType));
        return 0;
    }
    for (i = 0; i < sizeof(kEntries)/sizeof(kEntries[0]); ++i) {
        if (rva == kEntries[i].rva && length == 16) {
            memcpy(out, kEntries[i].prefix, 16);
            return 0;
        }
    }
    for (i = 0; i < sizeof(kVtable)/sizeof(kVtable[0]); ++i) {
        if (rva == kVtable[i].rva && length == 8) {
            uint64_t value = kVtable[i].value;
            if (m->corrupt_open && rva == OPEN_SLOT_RVA) ++value;
            for (j = 0; j < 8; ++j) bytes[j] = (unsigned char)(value >> (8*j));
            return 0;
        }
    }
    return -1;
}

static int write_rva(void* user, uint64_t rva, const void* src, size_t length) {
    Mem* m = (Mem*)user;
    const unsigned char* bytes = (const unsigned char*)src;
    uint64_t value = 0;
    size_t j;
    if (!m || length != 8) return -1;
    if (m->deny_write) return -1;
    for (j = 0; j < 8; ++j) value |= (uint64_t)bytes[j] << (8*j);
    if (rva == OPEN_SLOT_RVA) { m->open_live = value; m->have_overlay = 1; return 0; }
    if (rva == READ_SLOT_RVA) { m->read_live = value; m->have_overlay = 1; return 0; }
    return -1;
}

#define ASSERT(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL at line %d: %s\n", __LINE__, #condition); \
    return 3; } } while (0)

#define TRAMP_OPEN 0x0000000900001000ULL
#define TRAMP_READ 0x0000000900002000ULL

int main(void) {
    Mem m;
    LmlDetourPlan plan;

    /* Clean build: slots confirmed, plan verified with the right addresses. */
    memset(&m, 0, sizeof(m));
    ASSERT(lml_detour_build_plan(read_rva, &m, 0, 1, 0, TRAMP_OPEN, TRAMP_READ,
                                 &plan) == LML_DETOUR_OK);
    ASSERT(plan.verified == 1);
    ASSERT(plan.open_slot.slot_rva == OPEN_SLOT_RVA);
    ASSERT(plan.open_slot.original_value == 0x0452A480ULL);
    ASSERT(plan.open_slot.trampoline == TRAMP_OPEN);
    ASSERT(plan.read_slot.slot_rva == READ_SLOT_RVA);
    ASSERT(plan.read_slot.original_value == 0x0452B9D0ULL);

    /* Wrong version is forwarded and leaves no plan; never patch 1.32. */
    memset(&m, 0, sizeof(m));
    ASSERT(lml_detour_build_plan(read_rva, &m, 0, 1, 32, TRAMP_OPEN, TRAMP_READ,
                                 &plan) == LML_EBOOT_PROFILE_UNSUPPORTED_PATCH);
    ASSERT(plan.verified == 0);

    /* A slot that no longer holds the verified original aborts the plan. */
    memset(&m, 0, sizeof(m));
    m.corrupt_open = 1;
    ASSERT(lml_detour_build_plan(read_rva, &m, 0, 1, 0, TRAMP_OPEN, TRAMP_READ,
                                 &plan) == LML_DETOUR_SITE_MISMATCH);
    ASSERT(plan.verified == 0);

    /* apply/revert gating and round-trip on the writable overlay. */
    memset(&m, 0, sizeof(m));
    ASSERT(lml_detour_build_plan(read_rva, &m, 0, 1, 0, TRAMP_OPEN, TRAMP_READ,
                                 &plan) == LML_DETOUR_OK);
    {
        LmlDetourPlan unverified;
        memset(&unverified, 0, sizeof(unverified));
        ASSERT(lml_detour_apply(write_rva, &m, &unverified) ==
               LML_DETOUR_NOT_VERIFIED);
    }
    {
        LmlDetourPlan no_tramp = plan;
        no_tramp.open_slot.trampoline = 0;
        ASSERT(lml_detour_apply(write_rva, &m, &no_tramp) ==
               LML_DETOUR_BAD_ARGUMENT);
    }
    ASSERT(lml_detour_apply(write_rva, &m, &plan) == LML_DETOUR_OK);
    ASSERT(m.open_live == TRAMP_OPEN);
    ASSERT(m.read_live == TRAMP_READ);
    ASSERT(lml_detour_revert(write_rva, &m, &plan) == LML_DETOUR_OK);
    ASSERT(m.open_live == 0x0452A480ULL);
    ASSERT(m.read_live == 0x0452B9D0ULL);

    /* A write failure is reported, not swallowed. */
    memset(&m, 0, sizeof(m));
    ASSERT(lml_detour_build_plan(read_rva, &m, 0, 1, 0, TRAMP_OPEN, TRAMP_READ,
                                 &plan) == LML_DETOUR_OK);
    m.deny_write = 1;
    ASSERT(lml_detour_apply(write_rva, &m, &plan) == LML_DETOUR_WRITE_FAILED);

    ASSERT(lml_detour_build_plan(NULL, &m, 0, 1, 0, 0, 0, &plan) ==
           LML_DETOUR_BAD_ARGUMENT);

    puts("RDR2_100_FIPACKFILE8_DETOUR_TESTS_PASSED");
    return 0;
}
