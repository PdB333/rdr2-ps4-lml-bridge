#ifndef LML_RAGE_EBOOT_PROFILE_H
#define LML_RAGE_EBOOT_PROFILE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Fail-closed EBOOT identity check for this particular PS4 ELF. A caller
 * provides a READ-ONLY mapping of the loaded game's image and its load bias.
 * This function never writes to memory or installs an interception.
 *
 * Important: read_rva must reject unmapped regions. This code cannot recover
 * from arbitrary invalid pointers in an incorrectly implemented callback.
 */
typedef int (*LmlEbootReadRva)(void* ctx, uint64_t rva, void* dst, size_t size);

typedef struct LmlEbootVfsProfile {
    uint64_t packfile8_vtable_rva;
    uint64_t open_rva;
    uint64_t open_bulk_candidate_rva;
    uint64_t read_candidate_rva;
    uint64_t read_bulk_candidate_rva;
} LmlEbootVfsProfile;

enum LmlEbootVerification {
    LML_EBOOT_PROFILE_OK = 0,
    LML_EBOOT_PROFILE_BAD_ARGUMENT = -2,
    LML_EBOOT_PROFILE_READ_FAILED = -3,
    LML_EBOOT_PROFILE_MISMATCH = -4
};

#if defined(__GNUC__) || defined(__clang__)
#define LML_EBOOT_EXPORT __attribute__((visibility("default")))
#else
#define LML_EBOOT_EXPORT
#endif

LML_EBOOT_EXPORT int lml_eboot_verify_profile(
    LmlEbootReadRva read_rva, void* ctx, uint64_t image_load_bias,
    LmlEbootVfsProfile* verified);

#ifdef __cplusplus
}
#endif
#endif
