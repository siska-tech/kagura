// SPDX-License-Identifier: Apache-2.0
#include <string.h>

#include "kd_test.h"

int kd_test_failed;
int kd_test_quiet;

void kd_test_fail(const char *file, int line, const char *what) {
    kd_test_failed++;
    if (!kd_test_quiet) fprintf(stderr, "  FAIL %s:%d: %s\n", file, line, what);
}

int main(int argc, char **argv) {
    const char *only = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--quiet") == 0) kd_test_quiet = 1;
        else only = argv[i];
    }
    const kd_test_case *suites[] = {kd_raster_tests, kd_desktop_tests};
    int run = 0, failed = 0;
    for (unsigned s = 0; s < sizeof suites / sizeof suites[0]; s++) {
        for (const kd_test_case *t = suites[s]; t->name; t++) {
            if (only && !strstr(t->name, only)) continue;
            kd_test_failed = 0;
            t->fn();
            run++;
            if (kd_test_failed) failed++;
            if (!kd_test_quiet) printf("%-4s %s\n", kd_test_failed ? "FAIL" : "ok", t->name);
        }
    }
    printf("%d tests, %d failed\n", run, failed);
    return failed ? 1 : 0;
}
