#ifndef LML_RDR2_100_PACKFILE_HOOKS_H
#define LML_RDR2_100_PACKFILE_HOOKS_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* fiPackfile8 Open/Read hook BODIES for PS4 RDR2 1.00.
 *
 * These are the functions a version-specific detour trampoline calls once the
 * vtable slots (Open @2, Read @13) have been swapped on the running game
 * (see tools/ps5debug_ng_rdr2_100_detour.py + runtime/rdr2_100_detour.{h,c}).
 * This core is the glue between those slots and the clean-room read-through
 * backend in rage_vfs_redirect.h: a loose overlay file is served in place of
 * the packfile entry, the original handler is used otherwise.
 *
 * Design rules, mirroring rdr2_100_natives:
 *   - PURE / INJECTABLE: the bodies NEVER call a hardcoded game address. The
 *     original Open/Read are reached only through caller-supplied function
 *     pointers (the trampoline's saved originals), so the whole thing is
 *     testable off-console.
 *   - FAIL-CLOSED: redirection happens only when the caller declares
 *     abi_verified = 1. Until then every call is a transparent pass-through to
 *     the original handler, so the game's behaviour is preserved verbatim.
 *   - NO GUESSED ABI. Open/Read/Close/Seek/Size hook bodies all exist, but the
 *     close/seek/size slots (19 / 17,18 / 22,23) are identified statically only
 *     (orbis/LIVE_DETOUR_100.md) and not yet validated live. A bridge token MUST
 *     be closeable/seekable/sizeable through our hooks, so a bridge token is
 *     handed back to the game ONLY when the caller declares
 *     lifecycle_verified = 1 (the full method set is hooked AND verified live).
 *     With lifecycle_verified = 0 the Open hook still consults the overlay but
 *     falls through to the original handle, so a mismatched handle can never
 *     reach an un-hooked native close/seek and crash the engine.
 */

#define LML_PACKFILE_ABI_VERSION 1u
#define LML_PACKFILE_MAX_TOKENS 64u
/* Mode value the detour passes through from fiPackfile8::Open's read_only arg. */
#define LML_PACKFILE_READ_ONLY 1

enum LmlPackfileStatus {
    LML_PACKFILE_OK = 0,
    LML_PACKFILE_BAD_ARGUMENT = -2,
    LML_PACKFILE_ABI_UNVERIFIED = -5, /* a redirect was attempted too early  */
    LML_PACKFILE_NO_SLOT = -7,        /* token registry is full              */
    LML_PACKFILE_NOT_BRIDGE = -8      /* handle is a real game handle         */
};

/* Statically-recovered fiPackfile8 handler signatures (SysV, 1.00). The engine
 * handle type is opaque; we move it as a uint64_t and never interpret it. */
typedef uint64_t (*LmlPackfileOpenFn)(void* self, const char* path,
                                      int64_t read_only);
typedef int64_t (*LmlPackfileReadFn)(void* self, uint64_t handle, void* buffer,
                                     uint64_t size, int64_t extra);

typedef struct LmlPackfileHooks {
    uint32_t abi_version;        /* must equal LML_PACKFILE_ABI_VERSION      */
    int abi_verified;            /* 1 => Open/Read ABI confirmed live        */
    int lifecycle_verified;      /* 1 => close/seek/size also hooked+verified */
    LmlPackfileOpenFn original_open;   /* trampoline's saved original Open   */
    LmlPackfileReadFn original_read;   /* trampoline's saved original Read   */

    /* Active bridge tokens we handed back to the game, so Read/Close can tell
     * a bridge token from a real game handle without trusting bit patterns to
     * survive the engine's handle plumbing. */
    uint64_t tokens[LML_PACKFILE_MAX_TOKENS];
    uint32_t token_count;

    /* Observability (read by tests / the status probe). */
    uint64_t redirected_opens;
    uint64_t passthrough_opens;
    uint64_t redirected_reads;
    uint64_t passthrough_reads;
    uint64_t redirected_seeks;   /* bridge-token seeks served by the backend  */
    uint64_t redirected_sizes;   /* bridge-token sizes served by the backend  */
} LmlPackfileHooks;

#if defined(__GNUC__) || defined(__clang__)
#define LML_PACKFILE_EXPORT __attribute__((visibility("default")))
#else
#define LML_PACKFILE_EXPORT
#endif

/* Prepare the hook state. original_open/original_read are mandatory (the hook
 * cannot preserve the game without them). Redirection stays disabled unless
 * abi_verified == 1; bridge tokens are handed out only when, in addition,
 * lifecycle_verified == 1. */
LML_PACKFILE_EXPORT int lml_packfile_hooks_init(LmlPackfileHooks* hooks,
                                                LmlPackfileOpenFn original_open,
                                                LmlPackfileReadFn original_read,
                                                int abi_verified,
                                                int lifecycle_verified);

/* The Open hook body: consult the overlay for `path`, otherwise the original.
 * Returns the handle the game will keep (a bridge token or an original one). */
LML_PACKFILE_EXPORT uint64_t lml_packfile_hook_open(LmlPackfileHooks* hooks,
                                                    void* self,
                                                    const char* path,
                                                    int64_t read_only);

/* The Read hook body: serve overlay bytes for a bridge token, else forward to
 * the original Read unchanged. Returns bytes read, or a negative status. */
LML_PACKFILE_EXPORT int64_t lml_packfile_hook_read(LmlPackfileHooks* hooks,
                                                   void* self, uint64_t handle,
                                                   void* buffer, uint64_t size,
                                                   int64_t extra);

/* Close hook body: if `handle` is one of our bridge tokens, release it in the
 * backend and drop it from the registry (returns LML_PACKFILE_OK). If it is a
 * real game handle, returns LML_PACKFILE_NOT_BRIDGE so the caller forwards it
 * to the original close handler. Call this from a hooked close slot once the
 * lifecycle ABI is verified. */
LML_PACKFILE_EXPORT int lml_packfile_hook_close(LmlPackfileHooks* hooks,
                                                uint64_t handle);

/* Seek hook body: if `handle` is one of our bridge tokens, seek the overlay
 * stream and write the resulting absolute offset to *out_result (returns
 * LML_PACKFILE_OK). If it is a real game handle, returns LML_PACKFILE_NOT_BRIDGE
 * and leaves *out_result untouched, so the caller forwards to the original seek.
 *
 * Both engine seek slots (17 = 32-bit offset, 18 = 64-bit) route here; the
 * trampoline sign-extends the 32-bit offset into `offset`. `whence` is passed
 * through to the backend verbatim: the engine's whence encoding is ASSUMED to
 * match the backend's (POSIX SEEK_SET/CUR/END) and MUST be confirmed live before
 * lifecycle_verified is set to 1. This body never runs for a real handle, and a
 * bridge token is only ever handed out once lifecycle_verified == 1. */
LML_PACKFILE_EXPORT int lml_packfile_hook_seek(LmlPackfileHooks* hooks,
                                               uint64_t handle, int64_t offset,
                                               int whence, int64_t* out_result);

/* Size hook body: if `handle` is one of our bridge tokens, write the overlay
 * file size to *out_result (returns LML_PACKFILE_OK). If it is a real game
 * handle, returns LML_PACKFILE_NOT_BRIDGE and leaves *out_result untouched, so
 * the caller forwards to the original size handler. Both size slots (22/23)
 * route here. */
LML_PACKFILE_EXPORT int lml_packfile_hook_size(LmlPackfileHooks* hooks,
                                               uint64_t handle,
                                               int64_t* out_result);

/* True (1) when `handle` is a live bridge token this core handed out. */
LML_PACKFILE_EXPORT int lml_packfile_is_bridge_token(const LmlPackfileHooks* h,
                                                     uint64_t handle);

#ifdef __cplusplus
}
#endif
#endif
