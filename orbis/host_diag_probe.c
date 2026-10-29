// Portable host harness for the exact read-only diagnostics core.
#include "diag_probe_core.h"
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    FILE* file;
    int opens;
    int closes;
    int read_failure;
} Host;

static int host_open(void* user, const char* path) {
    Host* host = (Host*)user;
    host->file = fopen(path, "rb");
    if (!host->file) return -1;
    ++host->opens;
    return 1;
}
static int64_t host_read(void* user, int fd, void* data, size_t length) {
    Host* host = (Host*)user;
    size_t got;
    if (fd != 1 || !host->file || host->read_failure) return -1;
    got = fread(data, 1, length, host->file);
    if (ferror(host->file)) return -1;
    return (int64_t)got;
}
static void host_close(void* user, int fd) {
    Host* host = (Host*)user;
    if (fd == 1 && host->file) {
        fclose(host->file);
        host->file = NULL;
        ++host->closes;
    }
}
static void host_log(void* user, const char* text) {
    (void)user;
    fputs(text, stdout);
}

int main(int argc, char** argv) {
    Host host = {0};
    LmlDiagIo io;
    LmlDiagResult report;
    int status;
    if (argc < 2 || argc > 3) {
        fputs("usage: host_diag_probe <overlay.map> [--fail-read]\n", stderr);
        return 2;
    }
    if (argc == 3) {
        if (strcmp(argv[2], "--fail-read") != 0) return 2;
        host.read_failure = 1;
    }
    io.context = &host;
    io.open_read = host_open;
    io.read_file = host_read;
    io.close_file = host_close;
    io.log_line = host_log;
    status = lml_diag_scan(&io, argv[1], &report);
    if (status != report.code || host.opens != host.closes) {
        fputs("diagnostic core invariants failed\n", stderr);
        return 11;
    }
    printf("STATUS=%s CODE=%d R=%u S=%u D=%u LINES=%u BYTES=%llu OPEN=%d CLOSE=%d\n",
           lml_diag_label(status), status,
           report.replacements, report.streams, report.data_files,
           report.parsed_lines, (unsigned long long)report.read_bytes,
           host.opens, host.closes);
    return 0;  // The status field carries the probe result.
}
