#ifndef LML_RAGE_VFS_REDIRECT_H
#define LML_RAGE_VFS_REDIRECT_H

/* Clean-room, portable RAGE VFS READ-THROUGH bridge for RDR2 PS4.
 *
 * These exports are called by a version-specific game VFS adapter AFTER it
 * intercepts the game's virtual-file device. They do not install an inline
 * hook or guess the game ABI. No encrypted RPF8 parsing/repacking is needed
 * when the engine requests an individual named file through its VFS.
 *
 * The game adapter MUST intercept all read/seek/size/close and metadata
 * methods for any token returned by lml_rage_open_file: bridge tokens are NOT
 * native RAGE fiDevice handles. Bypassing that invariant would crash a game.
 */
#include <stddef.h>
#include <stdint.h>

#if defined(__cplusplus)
extern "C" {
#endif

#if defined(__GNUC__) || defined(__clang__)
# define LML_RAGE_EXPORT __attribute__((visibility("default")))
#else
# define LML_RAGE_EXPORT
#endif

#define LML_RAGE_ABI_VERSION 1u
#define LML_RAGE_READ_ONLY 1u
#define LML_RAGE_SOURCE_ORIGINAL 0u
#define LML_RAGE_SOURCE_OVERLAY 1u
#define LML_RAGE_MISSING_HANDLE UINT64_MAX

enum LmlRageCode {
    LML_RAGE_OK = 0,
    LML_RAGE_NOT_FOUND = -1,
    LML_RAGE_BAD_ARGUMENT = -2,
    LML_RAGE_IO_ERROR = -3,
    LML_RAGE_NO_BACKEND = -4,
    LML_RAGE_BUSY = -5
};

typedef struct LmlRageFileInfo {
    uint64_t size;
    uint64_t unix_modification_time;
    uint32_t attributes;  /* 1=exists, 2=directory; console host translates. */
    uint32_t reserved;
} LmlRageFileInfo;

/* Original callbacks MUST invoke the unhooked RAGE VFS routines, NOT the
 * intercepted entrypoint. They are specific to the Title ID and patch.
 * The callback context must stay alive while the bridge is bound.
 *
 * On failure, open() returns LML_RAGE_MISSING_HANDLE.
 * Other callbacks use negative return values on failure.
 * All callbacks are read-only: the bridge will not authorize writes.
 */
typedef struct LmlRageOriginalVfs {
    uint32_t abi_version;
    void* context;
    uint64_t (*open)(void* ctx, const char* virtual_path, uint32_t mode);
    int64_t (*read)(void* ctx, uint64_t original, void* dst, size_t bytes);
    int64_t (*seek)(void* ctx, uint64_t original, int64_t offset, int whence);
    int64_t (*size)(void* ctx, uint64_t original);
    int (*close)(void* ctx, uint64_t original);
    int (*stat)(void* ctx, const char* virtual_path, LmlRageFileInfo* out);
} LmlRageOriginalVfs;

typedef struct LmlRageCounters {
    uint64_t redirected_opens;
    uint64_t original_opens;
    uint64_t overlay_fallbacks;
    uint64_t failed_opens;
    uint64_t active_tokens;
} LmlRageCounters;

LML_RAGE_EXPORT uint32_t lml_rage_abi_version(void);

/* Load an overlay.map already compiled from install.xml and copied to disk.
 * Only FileReplacement entries (R) are usable here. Does NOT auto-hook RAGE.
 * Any open tokens prevent replacing the active map.
 */
LML_RAGE_EXPORT int lml_rage_load_overlay(const char* overlay_map,
                                           const char* payload_root);

/* Original callbacks can be installed only when no files are open. Pass NULL
 * to detach. In a game this step MUST be implemented by a title-specific
 * VFS adapter with verified RDR2 PS4 calling conventions and addresses.
 */
LML_RAGE_EXPORT int lml_rage_bind_game_io(const LmlRageOriginalVfs* backend);

/* The game adapter should invoke this at the RAGE virtual-file-open boundary.
 * mode==LML_RAGE_READ_ONLY permits loose replacement, any other mode uses
 * the original backend. Returns an OPAQUE BRIDGE TOKEN in out_token.
 */
LML_RAGE_EXPORT int lml_rage_open_file(const char* virtual_path, uint32_t mode,
                                       uint64_t* out_token, uint32_t* out_source);
LML_RAGE_EXPORT int64_t lml_rage_read_file(uint64_t token, void* dst, size_t length);
LML_RAGE_EXPORT int64_t lml_rage_seek_file(uint64_t token, int64_t offset, int whence);
LML_RAGE_EXPORT int64_t lml_rage_read_at(uint64_t token, uint64_t offset,
                                         void* dst, size_t length);
LML_RAGE_EXPORT int64_t lml_rage_size_file(uint64_t token);
LML_RAGE_EXPORT int lml_rage_close_file(uint64_t token);

/* Called from the game's GetFileSize/GetAttributes/GetFileTime equivalents.
 * A size may be overridden only when the same replacement file is readable.
 */
LML_RAGE_EXPORT int lml_rage_stat_path(const char* virtual_path,
                                        LmlRageFileInfo* out_info);

/* Alternative hook boundary for RAGE XML/META/OMT/DAT loaders that accept
 * a file path argument: return the readable loose-file path, or NOT_FOUND
 * to call the original loader with its original virtual path.
 * Deliberately excludes binary RAGE resources (.ymt/.ytd/.ymap/.ytyp/etc.)
 * whose loaders need engine-specific registration/serialization.
 * Copies into a caller-owned buffer, never changes the game's input string.
 */
LML_RAGE_EXPORT int lml_rage_select_loader_path(const char* virtual_path,
                                                 char* out_path, size_t capacity);

/* Generic synchronous XML/META loader interceptor. The version-specific
 * RDR2 1.32 thunk translates the REAL game's function signature into this
 * callback and must supply an unhooked/original loader function. This helper
 * never patches code; it is the hook BODY once called by a verified detour.
 * The original callback must consume/copy the path synchronously.
 */
typedef int64_t (*LmlRageTextLoaderFn)(void* context, const char* path,
                                      void* opaque_request);
LML_RAGE_EXPORT int64_t lml_rage_dispatch_text_loader(
    const char* virtual_path, LmlRageTextLoaderFn unhooked_original,
    void* context, void* opaque_request, uint32_t* redirected);

LML_RAGE_EXPORT int lml_rage_get_counters(LmlRageCounters* out);
LML_RAGE_EXPORT int lml_rage_clear(void);

#if defined(__cplusplus)
}
#endif
#endif
