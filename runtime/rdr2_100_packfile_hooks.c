/* fiPackfile8 Open/Read hook bodies for PS4 RDR2 1.00. See header.
 *
 * Pure and fail-closed: redirection is wired to the clean-room read-through
 * backend (rage_vfs_redirect.h), and the original handler is reached only
 * through caller-supplied function pointers. No game address is hardcoded.
 */
#include "rdr2_100_packfile_hooks.h"
#include "rage_vfs_redirect.h"
#include <string.h>

static int register_token(LmlPackfileHooks* h, uint64_t token) {
    if (h->token_count >= LML_PACKFILE_MAX_TOKENS) {
        return LML_PACKFILE_NO_SLOT;
    }
    h->tokens[h->token_count++] = token;
    return LML_PACKFILE_OK;
}

static int unregister_token(LmlPackfileHooks* h, uint64_t token) {
    uint32_t i;
    for (i = 0; i < h->token_count; ++i) {
        if (h->tokens[i] == token) {
            h->tokens[i] = h->tokens[h->token_count - 1];
            h->token_count--;
            return LML_PACKFILE_OK;
        }
    }
    return LML_PACKFILE_NOT_BRIDGE;
}

int lml_packfile_is_bridge_token(const LmlPackfileHooks* h, uint64_t handle) {
    uint32_t i;
    if (!h) {
        return 0;
    }
    for (i = 0; i < h->token_count; ++i) {
        if (h->tokens[i] == handle) {
            return 1;
        }
    }
    return 0;
}

int lml_packfile_hooks_init(LmlPackfileHooks* hooks,
                            LmlPackfileOpenFn original_open,
                            LmlPackfileReadFn original_read,
                            int abi_verified, int lifecycle_verified) {
    if (!hooks || !original_open || !original_read) {
        return LML_PACKFILE_BAD_ARGUMENT;
    }
    memset(hooks, 0, sizeof(*hooks));
    hooks->abi_version = LML_PACKFILE_ABI_VERSION;
    /* Normalise to 0/1 so a stray non-1 truthy value never enables redirect. */
    hooks->abi_verified = (abi_verified == 1) ? 1 : 0;
    hooks->lifecycle_verified = (lifecycle_verified == 1) ? 1 : 0;
    hooks->original_open = original_open;
    hooks->original_read = original_read;
    return LML_PACKFILE_OK;
}

uint64_t lml_packfile_hook_open(LmlPackfileHooks* hooks, void* self,
                                const char* path, int64_t read_only) {
    /* Without a saved original there is nothing safe to return; refuse to
     * fabricate a handle. */
    if (!hooks || !hooks->original_open) {
        return LML_RAGE_MISSING_HANDLE;
    }
    /* Redirect only once BOTH the Open/Read ABI and the full handle lifecycle
     * (close/seek/size) are verified, and only for read-only opens: a bridge
     * token handed to an un-hooked native close/seek would crash the engine. */
    if (hooks->abi_verified && hooks->lifecycle_verified && path &&
        read_only == LML_PACKFILE_READ_ONLY) {
        uint64_t token = 0;
        uint32_t source = LML_RAGE_SOURCE_ORIGINAL;
        int rc = lml_rage_open_file(path, LML_RAGE_READ_ONLY, &token, &source);
        if (rc == LML_RAGE_OK && source == LML_RAGE_SOURCE_OVERLAY) {
            if (register_token(hooks, token) == LML_PACKFILE_OK) {
                hooks->redirected_opens++;
                return token;
            }
            /* Registry full: drop the bridge stream and fall through. */
            lml_rage_close_file(token);
        } else if (rc == LML_RAGE_OK) {
            /* Not an overlay entry: let the engine open its own native handle
             * so its seek/size/close stay natively correct. */
            lml_rage_close_file(token);
        }
    }
    hooks->passthrough_opens++;
    return hooks->original_open(self, path, read_only);
}

int64_t lml_packfile_hook_read(LmlPackfileHooks* hooks, void* self,
                               uint64_t handle, void* buffer, uint64_t size,
                               int64_t extra) {
    if (!hooks) {
        return LML_PACKFILE_BAD_ARGUMENT;
    }
    if (lml_packfile_is_bridge_token(hooks, handle)) {
        /* Bridge tokens are only ever handed out after abi/lifecycle checks. */
        hooks->redirected_reads++;
        return lml_rage_read_file(handle, buffer, (size_t)size);
    }
    if (!hooks->original_read) {
        return LML_PACKFILE_BAD_ARGUMENT;
    }
    hooks->passthrough_reads++;
    return hooks->original_read(self, handle, buffer, size, extra);
}

int lml_packfile_hook_close(LmlPackfileHooks* hooks, uint64_t handle) {
    if (!hooks) {
        return LML_PACKFILE_BAD_ARGUMENT;
    }
    if (!lml_packfile_is_bridge_token(hooks, handle)) {
        return LML_PACKFILE_NOT_BRIDGE;
    }
    lml_rage_close_file(handle);
    unregister_token(hooks, handle);
    return LML_PACKFILE_OK;
}

int lml_packfile_hook_seek(LmlPackfileHooks* hooks, uint64_t handle,
                           int64_t offset, int whence, int64_t* out_result) {
    if (!hooks || !out_result) {
        return LML_PACKFILE_BAD_ARGUMENT;
    }
    if (!lml_packfile_is_bridge_token(hooks, handle)) {
        return LML_PACKFILE_NOT_BRIDGE;
    }
    /* Bridge tokens are only handed out after abi/lifecycle checks. */
    *out_result = lml_rage_seek_file(handle, offset, whence);
    hooks->redirected_seeks++;
    return LML_PACKFILE_OK;
}

int lml_packfile_hook_size(LmlPackfileHooks* hooks, uint64_t handle,
                           int64_t* out_result) {
    if (!hooks || !out_result) {
        return LML_PACKFILE_BAD_ARGUMENT;
    }
    if (!lml_packfile_is_bridge_token(hooks, handle)) {
        return LML_PACKFILE_NOT_BRIDGE;
    }
    *out_result = lml_rage_size_file(handle);
    hooks->redirected_sizes++;
    return LML_PACKFILE_OK;
}
