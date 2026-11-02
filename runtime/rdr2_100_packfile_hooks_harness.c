/* Offline integration harness for the fiPackfile8 Open/Read hook bodies.
 * Runs on a Windows host, links the clean-room VFS backend, and simulates the
 * game's ORIGINAL fiPackfile8::Open/Read through saved-original callbacks.
 * No game binary or PS4 hook is involved; the overlay bytes are real loose
 * files supplied on disk by the Python test.
 */
#include "rdr2_100_packfile_hooks.h"
#include "rage_vfs_redirect.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const char* REPL = "update:/common/data/ai/combatbehaviour.meta";
static const char* PASS = "update:/common/data/original.bin";
static const char ORIGINAL_BYTES[] = "ORIGINAL_CONTENT";  /* 16 bytes */
#define ORIGINAL_LEN (sizeof(ORIGINAL_BYTES) - 1)

/* --- Fake game packfile, the target of the hook's saved-original pointers. */
#define MAX_GF 128
typedef struct Game {
    int used[MAX_GF];
    uint64_t pos[MAX_GF];
    int opened;
    int reads;
} Game;
static Game g_game;

static uint64_t game_open(void* self, const char* path, int64_t read_only) {
    int i;
    (void)self;
    (void)read_only;
    if (!path) {
        return LML_RAGE_MISSING_HANDLE;
    }
    for (i = 0; i < MAX_GF; ++i) {
        if (!g_game.used[i]) {
            g_game.used[i] = 1;
            g_game.pos[i] = 0;
            g_game.opened++;
            return (uint64_t)(2000 + i);  /* a real, non-bridge game handle */
        }
    }
    return LML_RAGE_MISSING_HANDLE;
}

static int64_t game_read(void* self, uint64_t handle, void* buffer,
                         uint64_t size, int64_t extra) {
    int i = (int)(handle - 2000);
    uint64_t pos, remaining, n;
    (void)self;
    (void)extra;
    if (i < 0 || i >= MAX_GF || !g_game.used[i]) {
        return -1;
    }
    pos = g_game.pos[i];
    if (pos >= ORIGINAL_LEN) {
        return 0;
    }
    remaining = ORIGINAL_LEN - pos;
    n = size < remaining ? size : remaining;
    memcpy(buffer, ORIGINAL_BYTES + pos, (size_t)n);
    g_game.pos[i] += n;
    g_game.reads++;
    return (int64_t)n;
}

/* --- Minimal ORIGINAL fiDevice callbacks for the backend's overlay fallback. */
static const char* g_root;

static uint64_t backend_open(void* ctx, const char* path, uint32_t mode) {
    char physical[1024];
    FILE* file;
    (void)ctx;
    if (mode == 0 || !path) {
        return LML_RAGE_MISSING_HANDLE;
    }
    snprintf(physical, sizeof(physical), "%s/original.bin", g_root);
    file = fopen(physical, "rb");
    return file ? (uint64_t)(uintptr_t)file : LML_RAGE_MISSING_HANDLE;
}
static int64_t backend_read(void* ctx, uint64_t h, void* dst, size_t n) {
    (void)ctx;
    return (int64_t)fread(dst, 1, n, (FILE*)(uintptr_t)h);
}
static int64_t backend_seek(void* ctx, uint64_t h, int64_t off, int whence) {
    (void)ctx;
    if (fseek((FILE*)(uintptr_t)h, (long)off, whence)) {
        return -1;
    }
    return ftell((FILE*)(uintptr_t)h);
}
static int64_t backend_size(void* ctx, uint64_t h) {
    FILE* f = (FILE*)(uintptr_t)h;
    long pos = ftell(f), size;
    (void)ctx;
    if (pos < 0 || fseek(f, 0, SEEK_END)) {
        return -1;
    }
    size = ftell(f);
    if (fseek(f, pos, SEEK_SET)) {
        return -1;
    }
    return size;
}
static int backend_close(void* ctx, uint64_t h) {
    (void)ctx;
    return fclose((FILE*)(uintptr_t)h);
}
static int backend_stat(void* ctx, const char* path, LmlRageFileInfo* out) {
    (void)ctx;
    (void)path;
    out->size = ORIGINAL_LEN;
    out->unix_modification_time = 0;
    out->attributes = 1;
    out->reserved = 0;
    return 0;
}

#define ASSERT(cond) do { if (!(cond)) { \
    fprintf(stderr, "FAIL at line %d: %s\n", __LINE__, #cond); \
    return 3; } } while (0)

static int read_all(LmlPackfileHooks* h, uint64_t handle, char* out,
                    uint64_t cap) {
    int64_t n = lml_packfile_hook_read(h, NULL, handle, out, cap, 1);
    if (n < 0 || (uint64_t)n >= cap) {
        return -1;
    }
    out[n] = '\0';
    return (int)n;
}

int main(int argc, char** argv) {
    LmlPackfileHooks hooks;
    LmlRageOriginalVfs callbacks;
    uint64_t handle;
    char buffer[256];

    if (argc != 2) {
        fprintf(stderr, "usage: rdr2_100_packfile_hooks_harness <test-dir>\n");
        return 2;
    }
    g_root = argv[1];

    /* init rejects missing saved originals. */
    ASSERT(lml_packfile_hooks_init(NULL, game_open, game_read, 1, 1) ==
           LML_PACKFILE_BAD_ARGUMENT);
    ASSERT(lml_packfile_hooks_init(&hooks, NULL, game_read, 1, 1) ==
           LML_PACKFILE_BAD_ARGUMENT);

    /* Bind the clean-room backend + overlay so redirection has something to
     * serve. */
    callbacks.abi_version = LML_RAGE_ABI_VERSION;
    callbacks.context = NULL;
    callbacks.open = backend_open;
    callbacks.read = backend_read;
    callbacks.seek = backend_seek;
    callbacks.size = backend_size;
    callbacks.close = backend_close;
    callbacks.stat = backend_stat;
    ASSERT(lml_rage_clear() == 0);
    ASSERT(lml_rage_bind_game_io(&callbacks) == 0);
    {
        char map[1024];
        snprintf(map, sizeof(map), "%s/overlay.map", g_root);
        ASSERT(lml_rage_load_overlay(map, g_root) == 0);
    }

    /* (1) ABI verified but lifecycle NOT verified: never hand out a bridge
     * token -- a transparent pass-through, game behaviour preserved. */
    ASSERT(lml_packfile_hooks_init(&hooks, game_open, game_read, 1, 0) ==
           LML_PACKFILE_OK);
    memset(&g_game, 0, sizeof(g_game));
    handle = lml_packfile_hook_open(&hooks, NULL, REPL, LML_PACKFILE_READ_ONLY);
    ASSERT(!lml_packfile_is_bridge_token(&hooks, handle));
    ASSERT(handle >= 2000);                     /* a game handle, not a token */
    ASSERT(read_all(&hooks, handle, buffer, sizeof(buffer)) == (int)ORIGINAL_LEN);
    ASSERT(strcmp(buffer, ORIGINAL_BYTES) == 0);
    ASSERT(hooks.redirected_opens == 0 && hooks.passthrough_opens == 1);
    ASSERT(hooks.redirected_reads == 0 && hooks.passthrough_reads == 1);

    /* (2) Fully verified: a read-only open of a replaced path returns a bridge
     * token and the overlay bytes are served. */
    ASSERT(lml_packfile_hooks_init(&hooks, game_open, game_read, 1, 1) ==
           LML_PACKFILE_OK);
    memset(&g_game, 0, sizeof(g_game));
    handle = lml_packfile_hook_open(&hooks, NULL, REPL, LML_PACKFILE_READ_ONLY);
    ASSERT(lml_packfile_is_bridge_token(&hooks, handle));
    ASSERT(g_game.opened == 0);                 /* game Open was NOT called   */
    ASSERT(read_all(&hooks, handle, buffer, sizeof(buffer)) == 14);
    ASSERT(strcmp(buffer, "MODDED_CONTENT") == 0);
    ASSERT(hooks.redirected_opens == 1 && hooks.redirected_reads == 1);
    /* seek/size hook bodies serve the overlay stream for a bridge token. */
    {
        int64_t result = -1;
        ASSERT(lml_packfile_hook_size(&hooks, handle, &result) == LML_PACKFILE_OK);
        ASSERT(result == 14);                   /* "MODDED_CONTENT" is 14 bytes */
        ASSERT(lml_packfile_hook_seek(&hooks, handle, 5, SEEK_SET, &result) ==
               LML_PACKFILE_OK);
        ASSERT(result == 5);
        ASSERT(hooks.redirected_seeks == 1 && hooks.redirected_sizes == 1);
        /* NULL out_result is rejected without touching backend state. */
        ASSERT(lml_packfile_hook_size(&hooks, handle, NULL) ==
               LML_PACKFILE_BAD_ARGUMENT);
        ASSERT(lml_packfile_hook_seek(&hooks, handle, 0, SEEK_SET, NULL) ==
               LML_PACKFILE_BAD_ARGUMENT);
        ASSERT(hooks.redirected_seeks == 1 && hooks.redirected_sizes == 1);
    }
    /* close releases the bridge token; a second close is no longer a bridge. */
    ASSERT(lml_packfile_hook_close(&hooks, handle) == LML_PACKFILE_OK);
    ASSERT(!lml_packfile_is_bridge_token(&hooks, handle));
    ASSERT(lml_packfile_hook_close(&hooks, handle) == LML_PACKFILE_NOT_BRIDGE);

    /* (3) Fully verified but a path with no overlay entry: pass-through to the
     * game's own handle, original bytes. */
    memset(&g_game, 0, sizeof(g_game));
    handle = lml_packfile_hook_open(&hooks, NULL, PASS, LML_PACKFILE_READ_ONLY);
    ASSERT(!lml_packfile_is_bridge_token(&hooks, handle));
    ASSERT(g_game.opened == 1);
    ASSERT(read_all(&hooks, handle, buffer, sizeof(buffer)) == (int)ORIGINAL_LEN);
    ASSERT(strcmp(buffer, ORIGINAL_BYTES) == 0);
    /* seek/size on a real game handle forward to the original (NOT_BRIDGE),
     * leaving out_result untouched. */
    {
        int64_t result = 123;
        ASSERT(lml_packfile_hook_seek(&hooks, handle, 0, SEEK_SET, &result) ==
               LML_PACKFILE_NOT_BRIDGE);
        ASSERT(result == 123);
        ASSERT(lml_packfile_hook_size(&hooks, handle, &result) ==
               LML_PACKFILE_NOT_BRIDGE);
        ASSERT(result == 123);
    }
    ASSERT(lml_packfile_hook_close(&hooks, handle) == LML_PACKFILE_NOT_BRIDGE);

    /* (4) Fully verified but a non-read-only open is never overridden. */
    memset(&g_game, 0, sizeof(g_game));
    handle = lml_packfile_hook_open(&hooks, NULL, REPL, 2 /* not read-only */);
    ASSERT(!lml_packfile_is_bridge_token(&hooks, handle));
    ASSERT(g_game.opened == 1);
    ASSERT(lml_packfile_hook_close(&hooks, handle) == LML_PACKFILE_NOT_BRIDGE);

    /* (5) A read on an unknown real handle still forwards to the original. */
    memset(&g_game, 0, sizeof(g_game));
    handle = lml_packfile_hook_open(&hooks, NULL, PASS, LML_PACKFILE_READ_ONLY);
    ASSERT(lml_packfile_hook_read(&hooks, NULL, handle, buffer, 4, 1) == 4);

    ASSERT(lml_rage_clear() == 0);
    puts("RDR2_100_FIPACKFILE8_HOOKS_TESTS_PASSED");
    return 0;
}
