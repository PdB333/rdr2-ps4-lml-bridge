#ifndef LML_DIAG_PROBE_CORE_H
#define LML_DIAG_PROBE_CORE_H

/* Independent read-only map probe. Host callbacks isolate game/OS APIs.
 * No RDR2 symbols, no patches, no heap, and no external LML source. */
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum LmlDiagCode {
    LML_DIAG_OK = 0,
    LML_DIAG_UNAVAILABLE = -1,
    LML_DIAG_READ_FAILED = -2,
    LML_DIAG_BAD_HEADER = -3,
    LML_DIAG_BAD_RECORD = -4,
    LML_DIAG_LIMIT = -5,
    LML_DIAG_BAD_ARGUMENT = -6
};

typedef struct LmlDiagIo {
    void* context;
    int (*open_read)(void* context, const char* path);
    int64_t (*read_file)(void* context, int descriptor, void* data, size_t length);
    void (*close_file)(void* context, int descriptor);
    void (*log_line)(void* context, const char* line);
} LmlDiagIo;

typedef struct LmlDiagResult {
    int code;
    uint32_t replacements;
    uint32_t streams;
    uint32_t data_files;
    uint32_t parsed_lines;
    uint64_t read_bytes;
} LmlDiagResult;

/* Always closes the resource if it was successfully opened. Errors do not
 * change the target files. Reports are initialized before any OS operation. */
int lml_diag_scan(const LmlDiagIo* io, const char* map_path,
                  LmlDiagResult* result);

const char* lml_diag_label(int code);

#ifdef __cplusplus
}
#endif
#endif
