#define _POSIX_C_SOURCE 200809L
#include "experiment.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
uint64_t experiment_time_us(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000 + t.tv_nsec / 1000;
}
void experiment_tick(void) {}
int main(int argc, char **argv) {
    size_t budget = argc > 1 ? strtoul(argv[1], NULL, 10) : 128 * 1024;
    unsigned cycles = argc > 2 ? (unsigned)strtoul(argv[2], NULL, 10) : 1;
    if (!budget || !cycles) return 2;
    printf("INFO host pointer_bytes=%zu budget=%zu cycles=%u\n", sizeof(void *), budget, cycles);
    if (argc > 3 && !strcmp(argv[3], "oom-recovery")) {
        if (experiment(4096, 1, 0) != 1) return 2;
    }
    return experiment_named(budget, cycles, argc > 3 && strcmp(argv[3], "plain"), argc > 4 ? argv[4] : NULL);
}
