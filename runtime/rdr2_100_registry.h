#ifndef RDR2_100_PACKFILE_REGISTRY_H
#define RDR2_100_PACKFILE_REGISTRY_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* This is a read-only probe, not a game pointer scanner.
 * Candidate registry RVA was observed in the PS4 1.00 EBOOT destructor.
 * The caller supplies a validated, bounds-checking absolute-address reader;
 * no game pointers are dereferenced by this code.
 */
#define RDR2_100_REGISTRY_RVA UINT64_C(0x08053D40)
#define RDR2_100_PACK_VPTR_RVA UINT64_C(0x066B00F8)
#define RDR2_100_REGISTRY_BATCH_LIMIT 4096u
typedef int (*Rdr2_100ReadAbsolute)(void *context, uint64_t addr,
                                     void *out, size_t bytes);
enum Rdr2_100RegistryStatus {
    RDR2_100_REGISTRY_OK=0,
    RDR2_100_REGISTRY_UNSUPPORTED_VERSION=-1,
    RDR2_100_REGISTRY_BAD_ARGUMENT=-2,
    RDR2_100_REGISTRY_UNMAPPED=-3,
    RDR2_100_REGISTRY_TRUNCATED=-4
};
/* The indexed array has 16-bit indices in the observed destructor.
 * start and count are explicit to avoid a 65K-entry blocking scan on the
 * game's main thread. A failing individual object probe is safely skipped.
 * A registry-slot read failure stops the scan rather than inventing data.
 * out_count counts valid discovered instances even when capacity is small;
 * the function returns TRUNCATED if any result could not be copied.
 */
#if defined(__GNUC__) || defined(__clang__)
#define RDR2_100_REGISTRY_EXPORT __attribute__((visibility("default")))
#else
#define RDR2_100_REGISTRY_EXPORT
#endif
RDR2_100_REGISTRY_EXPORT int rdr2_100_find_pack_instances(Rdr2_100ReadAbsolute read, void *context,
    uint32_t major, uint32_t minor, uint64_t game_image_base,
    uint32_t start_index, uint32_t scan_count,
    uint64_t *out_instances, size_t capacity, size_t *out_count);
#ifdef __cplusplus
}
#endif
#endif
