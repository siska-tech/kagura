// SPDX-License-Identifier: Apache-2.0
// Deterministic PC benchmark of the C desktop (see BENCHMARKS.md).
//
// Each sample: (untimed pre-step, render, export) -> timed op + render ->
// timed TILE4 export of the changed tiles into a 40-tile staging buffer and a
// RAM "VRAM" copy. Counts (pixels, damage, tiles, payload) are deterministic;
// times are host CPU times and say nothing direct about an RP2040.
//
//   kd_bench [--samples N] [--json FILE]
#if !defined(_WIN32)
#define _POSIX_C_SOURCE 199309L
#endif
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

#include "workloads.h"

static uint64_t now_ns(void) {
#ifdef _WIN32
    static LARGE_INTEGER freq;
    LARGE_INTEGER c;
    if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&c);
    return (uint64_t)(c.QuadPart * 1000000000.0 / (double)freq.QuadPart);
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec;
#endif
}


static int cmp_u64(const void *a, const void *b) {
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return x < y ? -1 : x > y;
}

static uint64_t pct(const uint64_t *v, int n, int p) { return v[(n - 1) * p / 100]; }

typedef struct {
    uint64_t med, p90, p99, max, export_med, total_med;
    double pixels, rects, area, damage_tiles, tiles, runs, bytes;
} result;

static result measure(const workload *w, int n, uint64_t *t_render, uint64_t *t_export, uint64_t *t_total) {
    result r;
    memset(&r, 0, sizeof r);
    w->setup();
    kd_tile4_stats st;
    kd_desktop_render(&S.desk);
    flush(&st);
    const int warm = 50;
    for (int i = -warm; i < n; i++) {
        if (w->pre) {
            w->pre(i);
            kd_desktop_render(&S.desk);
            flush(&st);
        }
        uint32_t pix0 = S.desk.fb.stats.pixels;
        uint64_t t0 = now_ns();
        w->op(i);
        bool drawn = kd_desktop_render(&S.desk);
        uint64_t t1 = now_ns();
        flush(&st);
        uint64_t t2 = now_ns();
        if (i < 0) continue;
        t_render[i] = t1 - t0;
        t_export[i] = t2 - t1;
        t_total[i] = t2 - t0;
        r.pixels += S.desk.fb.stats.pixels - pix0;
        if (drawn) {
            r.rects += S.desk.stats.last_rects;
            r.area += S.desk.stats.last_area;
            r.damage_tiles += S.desk.stats.last_damage_tiles;
        }
        r.tiles += st.tiles;
        r.runs += st.runs;
        r.bytes += st.bytes;
    }
    qsort(t_render, (size_t)n, sizeof *t_render, cmp_u64);
    qsort(t_export, (size_t)n, sizeof *t_export, cmp_u64);
    qsort(t_total, (size_t)n, sizeof *t_total, cmp_u64);
    r.med = pct(t_render, n, 50);
    r.p90 = pct(t_render, n, 90);
    r.p99 = pct(t_render, n, 99);
    r.max = t_render[n - 1];
    r.export_med = pct(t_export, n, 50);
    r.total_med = pct(t_total, n, 50);
    r.pixels /= n;
    r.rects /= n;
    r.area /= n;
    r.damage_tiles /= n;
    r.tiles /= n;
    r.runs /= n;
    r.bytes /= n;
    return r;
}

static void cpu_name(char *out, size_t n) {
    snprintf(out, n, "unknown");
    FILE *f = fopen("/proc/cpuinfo", "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof line, f)) {
        if (strncmp(line, "model name", 10) == 0) {
            char *p = strchr(line, ':');
            if (p) {
                snprintf(out, n, "%s", p + 2);
                out[strcspn(out, "\n")] = 0;
            }
            break;
        }
    }
    fclose(f);
}

int main(int argc, char **argv) {
    int n = 1001;
    const char *json = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--samples") == 0 && i + 1 < argc) n = atoi(argv[++i]);
        else if (strcmp(argv[i], "--json") == 0 && i + 1 < argc) json = argv[++i];
        else {
            fprintf(stderr, "usage: %s [--samples N] [--json FILE]\n", argv[0]);
            return 2;
        }
    }
    if (n < 11) n = 11;
    workloads_init();
    uint64_t *a = malloc(sizeof(uint64_t) * (size_t)n), *b = malloc(sizeof(uint64_t) * (size_t)n),
             *c = malloc(sizeof(uint64_t) * (size_t)n);
    if (!a || !b || !c) return 1;
    char cpu[128];
    cpu_name(cpu, sizeof cpu);
#ifdef __VERSION__
    const char *compiler = __VERSION__;
#else
    const char *compiler = "unknown";
#endif
    printf("# kd_bench: %d samples per workload, 50 warm-up\n", n);
    printf("# cpu: %s\n# compiler: %s\n", cpu, compiler);
    printf("# static sizes (bytes): kd_fb %zu, kd_desktop %zu, kd_shell %zu, kd_damage %zu, "
           "kd_region %zu (stack), kd_event %zu, staging %zu\n\n",
           sizeof(kd_fb), sizeof(kd_desktop), sizeof(kd_shell), sizeof(kd_damage), sizeof(kd_region),
           sizeof(kd_event), sizeof staging);
    printf("| workload | render med us | p90 | p99 | max | export med us | pixels | damage rects | damage px | "
           "damage tiles | changed tiles | runs | TILE4 bytes |\n");
    printf("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n");
    FILE *jf = json ? fopen(json, "w") : NULL;
    if (jf) fprintf(jf, "{\"samples\": %d, \"cpu\": \"%s\", \"compiler\": \"%s\", \"workloads\": [\n", n, cpu, compiler);
    unsigned nw = sizeof workloads / sizeof workloads[0];
    for (unsigned k = 0; k < nw; k++) {
        const workload *w = &workloads[k];
        result r = measure(w, n, a, b, c);
        printf("| %s | %.2f | %.2f | %.2f | %.2f | %.2f | %.0f | %.1f | %.0f | %.0f | %.0f | %.1f | %.0f |\n", w->name,
               r.med / 1e3, r.p90 / 1e3, r.p99 / 1e3, r.max / 1e3, r.export_med / 1e3, r.pixels, r.rects, r.area,
               r.damage_tiles, r.tiles, r.runs, r.bytes);
        if (jf)
            fprintf(jf,
                    "  {\"name\": \"%s\", \"what\": \"%s\", \"render_ns\": {\"p50\": %llu, \"p90\": %llu, \"p99\": %llu, "
                    "\"max\": %llu}, \"export_ns_p50\": %llu, \"total_ns_p50\": %llu, \"pixels\": %.1f, "
                    "\"damage_rects\": %.2f, \"damage_px\": %.1f, \"damage_tiles\": %.1f, \"changed_tiles\": %.1f, "
                    "\"runs\": %.2f, \"tile4_bytes\": %.1f}%s\n",
                    w->name, w->what, (unsigned long long)r.med, (unsigned long long)r.p90,
                    (unsigned long long)r.p99, (unsigned long long)r.max, (unsigned long long)r.export_med,
                    (unsigned long long)r.total_med, r.pixels, r.rects, r.area, r.damage_tiles, r.tiles, r.runs,
                    r.bytes, k + 1 < nw ? "," : "");
    }
    if (jf) {
        fprintf(jf, "], \"sizes\": {\"kd_fb\": %zu, \"kd_desktop\": %zu, \"kd_shell\": %zu, \"kd_region\": %zu, "
                    "\"staging\": %zu}}\n",
                sizeof(kd_fb), sizeof(kd_desktop), sizeof(kd_shell), sizeof(kd_region), sizeof staging);
        fclose(jf);
    }
    free(a);
    free(b);
    free(c);
    return 0;
}
