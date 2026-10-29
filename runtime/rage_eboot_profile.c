/* Per-EBOOT static fingerprints from an uploaded RDR2 PS4 ELF, read only.
 * SHA-256: e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff
 * Size: 121670745 bytes. Exact game patch and CUSA not yet confirmed.
 * Only 64 bytes of code-entry fingerprints (not proprietary game routines)
 * are recorded here. The actual eboot.bin is NEVER published.
 *
 * These are CANDIDATE vtable methods, not installed game hooks.
 */
#include "rage_eboot_profile.h"

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

static const struct MethodSlot {
    uint64_t pointer_rva;
    uint64_t expected_method_rva;
} kMethods[] = {
    {0x066B00F8ULL, 0x0452A380ULL}, /* destructor candidate */
    {0x066B0100ULL, 0x0452A3F0ULL}, /* deleting destructor candidate */
    {0x066B0108ULL, 0x0452A480ULL}, /* Open: (this, path, flag) */
    {0x066B0128ULL, 0x0452A780ULL}, /* OpenBulk candidate */
    {0x066B0160ULL, 0x0452B9D0ULL}, /* Read candidate */
    {0x066B0168ULL, 0x0452BA60ULL}  /* ReadBulk candidate */
};

static int equal_bytes(const unsigned char* lhs,
                       const unsigned char* rhs, size_t size) {
    size_t i;
    for (i = 0; i < size; ++i)
        if (lhs[i] != rhs[i]) return 0;
    return 1;
}

static uint64_t read_le64(const unsigned char* bytes) {
    uint64_t result = 0;
    unsigned i;
    for (i = 0; i < 8; ++i)
        result |= ((uint64_t)bytes[i]) << (8u * i);
    return result;
}

int lml_eboot_verify_profile(LmlEbootReadRva read_rva, void* ctx,
                            uint64_t image_load_bias,
                            LmlEbootVfsProfile* verified) {
    static const unsigned char type_name[] = "N4rage11fiPackfile8E";
    unsigned char buffer[32];
    size_t i;

    if (verified) {
        verified->packfile8_vtable_rva = 0;
        verified->open_rva = 0;
        verified->open_bulk_candidate_rva = 0;
        verified->read_candidate_rva = 0;
        verified->read_bulk_candidate_rva = 0;
    }
    if (!read_rva || !verified) return LML_EBOOT_PROFILE_BAD_ARGUMENT;
    if (image_load_bias > UINT64_MAX - 0x066B0480ULL)
        return LML_EBOOT_PROFILE_BAD_ARGUMENT;

    if (read_rva(ctx, 0x05D7DE40ULL, buffer, sizeof(type_name)) != 0)
        return LML_EBOOT_PROFILE_READ_FAILED;
    if (!equal_bytes(buffer, type_name, sizeof(type_name)))
        return LML_EBOOT_PROFILE_MISMATCH;

    /* Itanium C++ RTTI descriptor referenced immediately before vtable. */
    if (read_rva(ctx, 0x066B00F0ULL, buffer, 8) != 0)
        return LML_EBOOT_PROFILE_READ_FAILED;
    if (read_le64(buffer) != image_load_bias + 0x066B0480ULL)
        return LML_EBOOT_PROFILE_MISMATCH;

    for (i = 0; i < sizeof(kMethods)/sizeof(kMethods[0]); ++i) {
        if (read_rva(ctx, kMethods[i].pointer_rva, buffer, 8) != 0)
            return LML_EBOOT_PROFILE_READ_FAILED;
        if (read_le64(buffer) != image_load_bias +
                                 kMethods[i].expected_method_rva)
            return LML_EBOOT_PROFILE_MISMATCH;
    }
    for (i = 0; i < sizeof(kEntries)/sizeof(kEntries[0]); ++i) {
        if (read_rva(ctx, kEntries[i].rva, buffer, 16) != 0)
            return LML_EBOOT_PROFILE_READ_FAILED;
        if (!equal_bytes(buffer, kEntries[i].prefix, 16))
            return LML_EBOOT_PROFILE_MISMATCH;
    }
    verified->packfile8_vtable_rva = 0x066B00F8ULL;
    verified->open_rva = 0x0452A480ULL;
    verified->open_bulk_candidate_rva = 0x0452A780ULL;
    verified->read_candidate_rva = 0x0452B9D0ULL;
    verified->read_bulk_candidate_rva = 0x0452BA60ULL;
    return LML_EBOOT_PROFILE_OK;
}
