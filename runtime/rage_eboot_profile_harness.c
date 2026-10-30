/* Offline unit tests for the RDR2/Orbis fiPackfile8 identity guard.
 * Synthesizes only a few short memory ranges; no game binary is required.
 */
#include "rage_eboot_profile.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct Input {
    int corrupt_entry;
    int corrupt_vtable;
    int corrupt_type;
    int deny_read;
    int read_calls;
} Input;

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
    {0x066B0108ULL, 0x0452A480ULL},
    {0x066B0128ULL, 0x0452A780ULL},
    {0x066B0160ULL, 0x0452B9D0ULL},
    {0x066B0168ULL, 0x0452BA60ULL},
};

static int read_rva(void* user, uint64_t rva, void* output, size_t length) {
    Input* in = (Input*)user;
    unsigned char* bytes = (unsigned char*)output;
    size_t i, j;
    if (!in) return -1;
    ++in->read_calls;
    if (in->deny_read) return -1;
    if (rva == 0x05D7DE40ULL && length == sizeof(kType)) {
        memcpy(output, kType, sizeof(kType));
        if (in->corrupt_type) bytes[0] ^= 1;
        return 0;
    }
    for (i = 0; i < sizeof(kEntries)/sizeof(kEntries[0]); ++i) {
        if (rva == kEntries[i].rva && length == 16) {
            memcpy(output, kEntries[i].prefix, 16);
            if (in->corrupt_entry && i == 0) bytes[0] ^= 1;
            return 0;
        }
    }
    for (i = 0; i < sizeof(kVtable)/sizeof(kVtable[0]); ++i) {
        if (rva == kVtable[i].rva && length == 8) {
            uint64_t value = kVtable[i].value;
            if (in->corrupt_vtable && i == 3) ++value;
            for (j = 0; j < 8; ++j) bytes[j] = (unsigned char)(value >> (8*j));
            return 0;
        }
    }
    return -1;
}

#define ASSERT(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL at line %d: %s\n", __LINE__, #condition); \
    return 3; } } while (0)

int main(void) {
    Input in = {0};
    LmlEbootVfsProfile out = {0};
    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0, 1, 0, &out) == 0);
    ASSERT(out.packfile8_vtable_rva == 0x066B00F8ULL);
    ASSERT(out.open_rva == 0x0452A480ULL);
    ASSERT(out.read_candidate_rva == 0x0452B9D0ULL);

    /* Reject 1.32 before using any address from this 1.00 profile. */
    in.read_calls = 0;
    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0, 1, 32, &out) ==
           LML_EBOOT_PROFILE_UNSUPPORTED_PATCH && out.open_rva == 0);
    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0, 2, 0, &out) ==
           LML_EBOOT_PROFILE_UNSUPPORTED_PATCH && out.open_rva == 0);
    ASSERT(in.read_calls == 0); /* wrong version never touches game memory */

    in.corrupt_entry = 1;
    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0, 1, 0, &out) ==
           LML_EBOOT_PROFILE_MISMATCH && out.open_rva == 0);
    in.corrupt_entry = 0;

    in.corrupt_vtable = 1;
    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0, 1, 0, &out) ==
           LML_EBOOT_PROFILE_MISMATCH && out.open_rva == 0);
    in.corrupt_vtable = 0;

    in.corrupt_type = 1;
    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0, 1, 0, &out) ==
           LML_EBOOT_PROFILE_MISMATCH && out.open_rva == 0);
    in.corrupt_type = 0;

    in.deny_read = 1;
    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0, 1, 0, &out) ==
           LML_EBOOT_PROFILE_READ_FAILED && out.open_rva == 0);
    in.deny_read = 0;

    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0x100000ULL, 1, 0, &out) ==
           LML_EBOOT_PROFILE_MISMATCH);
    ASSERT(lml_eboot_verify_profile(read_rva, &in, UINT64_MAX, 1, 0, &out) ==
           LML_EBOOT_PROFILE_BAD_ARGUMENT);
    ASSERT(lml_eboot_verify_profile(NULL, &in, 0, 1, 0, &out) ==
           LML_EBOOT_PROFILE_BAD_ARGUMENT);
    ASSERT(lml_eboot_verify_profile(read_rva, &in, 0, 1, 0, NULL) ==
           LML_EBOOT_PROFILE_BAD_ARGUMENT);

    puts("RDR2_EBOOT_RPF8_PROFILE_GUARD_TESTS_PASSED");
    return 0;
}
