// Minimal independent Orbis PRX that reports entrypoint execution and
// inspects a single overlay.map in READ-ONLY mode. No hooks, no game writes.
#include "diag_probe_core.h"
#include <orbis/libkernel.h>
#include <stdint.h>
#include <stddef.h>

#ifndef LML_DIAG_MAP_PATH
#define LML_DIAG_MAP_PATH "/data/etaHEN/lml_bridge/overlay.map"
#endif

#define PROBE_EXPORT __attribute__((visibility("default"), used))

// Minimal module metadata as documented in the OpenOrbis CRT.
__attribute__((section(".data.sce_module_param"), aligned(8), used))
static const uint64_t lml_sce_module_param[] = {
    0x18u, 0x13C13F4BFULL, 0x1000051u
};

static volatile int probe_ran = 0;
static LmlDiagResult last_result;

static int open_read(void* user, const char* path) {
    (void)user;
    return sceKernelOpen(path, 0, 0);  // O_RDONLY, no create or write flags
}

static int64_t read_file(void* user, int fd, void* buf, size_t size) {
    (void)user;
    // The OpenOrbis SDK declares sceKernelRead as size_t; negative syscalls
    // are sign-extended errors, so reinterpret on x86-64.
    return (int64_t)sceKernelRead(fd, buf, size);
}

static void close_file(void* user, int fd) {
    (void)user;
    (void)sceKernelClose(fd);
}

static void log_line(void* user, const char* text) {
    (void)user;
    (void)sceKernelDebugOutText(0, text);
}

static size_t append_text(char* dst, size_t pos, size_t cap, const char* text) {
    while (*text && pos + 1 < cap) dst[pos++] = *text++;
    dst[pos] = 0;
    return pos;
}

static size_t append_uint(char* dst, size_t pos, size_t cap, uint32_t number) {
    char digits[10];
    size_t used = 0;
    do {
        digits[used++] = (char)('0' + (number % 10));
        number /= 10;
    } while (number && used < sizeof(digits));
    while (used && pos + 1 < cap) dst[pos++] = digits[--used];
    dst[pos] = 0;
    return pos;
}

static void report_scan(const LmlDiagResult* result) {
    char line[192] = {0};
    size_t cursor = 0;
    cursor = append_text(line, cursor, sizeof(line), "[LML-ORBI-DIAG] ");
    cursor = append_text(line, cursor, sizeof(line), lml_diag_label(result->code));
    cursor = append_text(line, cursor, sizeof(line), " R=");
    cursor = append_uint(line, cursor, sizeof(line), result->replacements);
    cursor = append_text(line, cursor, sizeof(line), " S=");
    cursor = append_uint(line, cursor, sizeof(line), result->streams);
    cursor = append_text(line, cursor, sizeof(line), " D=");
    cursor = append_uint(line, cursor, sizeof(line), result->data_files);
    (void)append_text(line, cursor, sizeof(line), "\n");
    log_line(0, line);
}

static int start_once(void) {
    LmlDiagIo io;
    if (probe_ran) return 0;
    probe_ran = 1;
    log_line(0, "[LML-ORBI-DIAG] MODULE_ENTRY RDR2-PS4-1.32 PS5-13.60\n");
    io.context = 0;
    io.open_read = open_read;
    io.read_file = read_file;
    io.close_file = close_file;
    io.log_line = log_line;
    (void)lml_diag_scan(&io, LML_DIAG_MAP_PATH, &last_result);
    report_scan(&last_result);
    // Fail-open: a missing map MUST NOT stop game startup.
    return 0;
}

PROBE_EXPORT const char* lml_diag_identity(void) {
    return "RDR2_PS4_132_LML_READONLY_DIAG_V1";
}

PROBE_EXPORT int lml_diag_abi_version(void) {
    return 1;
}

PROBE_EXPORT int lml_diag_last_status(void) {
    return last_result.code;
}

PROBE_EXPORT int32_t module_start(int64_t args, const void* argp) {
    (void)args;
    (void)argp;
    return start_once();
}

PROBE_EXPORT int32_t module_stop(int64_t args, const void* argp) {
    (void)args;
    (void)argp;
    log_line(0, "[LML-ORBI-DIAG] MODULE_STOP\n");
    return 0;
}

// Different loaders start at _init or call exported module_start; both
// converge on exactly one read-only diagnostic run.
PROBE_EXPORT int _init(void) { return start_once(); }
PROBE_EXPORT int _fini(void) { return 0; }
