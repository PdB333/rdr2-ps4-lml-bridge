#include "diag_probe_core.h"

#define LML_LINE_CAP 2048u
#define LML_CHUNK_CAP 4096u
#define LML_BYTE_CAP (2u * 1024u * 1024u)
#define LML_RECORD_CAP 4096u

typedef struct Scan {
    char line[LML_LINE_CAP];
    unsigned length;
    unsigned line_no;
    unsigned count;
    LmlDiagResult* report;
} Scan;

static int ascii_digit(char c) { return c >= '0' && c <= '9'; }
static int ascii_hex(char c) {
    return ascii_digit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}
static int equal_str(const char* a, const char* b) {
    while (*a && *b) {
        if (*a != *b) return 0;
        ++a;
        ++b;
    }
    return *a == 0 && *b == 0;
}
static int safe_relative(const char* s) {
    unsigned component = 0;
    const char* p = s;
    if (!*p || *p == '/' || *p == '\\') return 0;
    while (*p) {
        const char c = *p;
        if ((unsigned char)c < 32u || c == ':' || c == '\\') return 0;
        if (c == '/') {
            if (component == 0) return 0;
            component = 0;
        } else {
            ++component;
        }
        ++p;
    }
    if (!component) return 0;
    p = s;
    while (*p) {
        const char* begin = p;
        while (*p && *p != '/') ++p;
        if (p - begin == 1 && begin[0] == '.') return 0;
        if (p - begin == 2 && begin[0] == '.' && begin[1] == '.') return 0;
        if (*p == '/') ++p;
    }
    return 1;
}
static int accept_line(Scan* scan) {
    unsigned length = scan->length;
    char* text = scan->line;
    unsigned fields = 1;
    char* parts[5];
    unsigned i;
    ++scan->line_no;
    scan->report->parsed_lines = scan->line_no;
    if (length > 0 && text[length - 1] == '\r') --length;
    text[length] = 0;
    scan->length = 0;

    if (scan->line_no == 1) {
        return equal_str(text, "LML_OVERLAY_V1") ? 0 : LML_DIAG_BAD_HEADER;
    }
    if (!length || text[0] == '#') return 0;
    if (++scan->count > LML_RECORD_CAP) return LML_DIAG_LIMIT;

    parts[0] = text;
    for (i = 0; i < length; ++i) {
        if (text[i] != '\t') continue;
        if (fields >= 5) return LML_DIAG_BAD_RECORD;
        text[i] = 0;
        parts[fields++] = &text[i + 1];
    }
    if (fields != 5) return LML_DIAG_BAD_RECORD;
    if (parts[0][0] == 0 || parts[0][1] != 0 || !parts[1][0]) {
        return LML_DIAG_BAD_RECORD;
    }
    if (!safe_relative(parts[2])) return LML_DIAG_BAD_RECORD;
    for (i = 0; i < 64u; ++i) {
        if (!parts[3][i] || !ascii_hex(parts[3][i])) return LML_DIAG_BAD_RECORD;
    }
    if (parts[3][64] != 0 || !parts[4][0]) return LML_DIAG_BAD_RECORD;
    for (i = 0; parts[4][i]; ++i) {
        if (!ascii_digit(parts[4][i]) || i > 20u) return LML_DIAG_BAD_RECORD;
    }
    switch (parts[0][0]) {
        case 'R': ++scan->report->replacements; break;
        case 'S': ++scan->report->streams; break;
        case 'D': ++scan->report->data_files; break;
        default: return LML_DIAG_BAD_RECORD;
    }
    return 0;
}

const char* lml_diag_label(int code) {
    switch (code) {
        case LML_DIAG_OK: return "MAP_OK";
        case LML_DIAG_UNAVAILABLE: return "MAP_UNAVAILABLE";
        case LML_DIAG_READ_FAILED: return "MAP_READ_FAILED";
        case LML_DIAG_BAD_HEADER: return "MAP_BAD_HEADER";
        case LML_DIAG_BAD_RECORD: return "MAP_BAD_RECORD";
        case LML_DIAG_LIMIT: return "MAP_LIMIT";
        default: return "MAP_BAD_ARGUMENT";
    }
}

int lml_diag_scan(const LmlDiagIo* io, const char* path, LmlDiagResult* result) {
    Scan scan;
    unsigned char chunk[LML_CHUNK_CAP];
    int descriptor;
    int status = LML_DIAG_OK;
    unsigned i;
    if (result) {
        result->code = LML_DIAG_BAD_ARGUMENT;
        result->replacements = 0;
        result->streams = 0;
        result->data_files = 0;
        result->parsed_lines = 0;
        result->read_bytes = 0;
    }
    if (!result || !io || !io->open_read || !io->read_file
        || !io->close_file || !path || !*path) return LML_DIAG_BAD_ARGUMENT;
    scan.length = 0;
    scan.line_no = 0;
    scan.count = 0;
    scan.report = result;
    descriptor = io->open_read(io->context, path);
    if (descriptor < 0) {
        result->code = LML_DIAG_UNAVAILABLE;
        return result->code;
    }
    for (;;) {
        const int64_t n = io->read_file(io->context, descriptor, chunk, sizeof(chunk));
        if (n < 0 || n > (int64_t)sizeof(chunk)) {
            status = LML_DIAG_READ_FAILED;
            break;
        }
        if (n == 0) {
            if (scan.length) status = accept_line(&scan);
            if (!scan.line_no && !status) status = LML_DIAG_BAD_HEADER;
            break;
        }
        result->read_bytes += (uint64_t)n;
        if (result->read_bytes > LML_BYTE_CAP) {
            status = LML_DIAG_LIMIT;
            break;
        }
        for (i = 0; i < (unsigned)n; ++i) {
            const unsigned char c = chunk[i];
            if (c == '\n') {
                status = accept_line(&scan);
                if (status != 0) break;
            } else {
                if (c == 0 || scan.length + 1u >= sizeof(scan.line)) {
                    status = LML_DIAG_LIMIT;
                    break;
                }
                scan.line[scan.length++] = (char)c;
            }
        }
        if (status != 0) break;
    }
    io->close_file(io->context, descriptor);
    result->code = status;
    return status;
}
