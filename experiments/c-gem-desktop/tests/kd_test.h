// SPDX-License-Identifier: Apache-2.0
// Minimal test harness: CHECK records a failure and returns from the test.
#ifndef KD_TEST_H
#define KD_TEST_H

#include <stdint.h>
#include <stdio.h>

typedef struct {
    const char *name;
    void (*fn)(void);
} kd_test_case;

extern int kd_test_failed;   // failures in the current test
extern int kd_test_quiet;

void kd_test_fail(const char *file, int line, const char *what);

#define CHECK(cond)                                         \
    do {                                                    \
        if (!(cond)) {                                      \
            kd_test_fail(__FILE__, __LINE__, #cond);        \
            return;                                         \
        }                                                   \
    } while (0)

#define CHECK_EQ(a, b)                                                       \
    do {                                                                     \
        long long kd_a_ = (long long)(a), kd_b_ = (long long)(b);            \
        if (kd_a_ != kd_b_) {                                                \
            char kd_msg_[160];                                               \
            snprintf(kd_msg_, sizeof kd_msg_, "%s == %s (%lld != %lld)", #a, \
                     #b, kd_a_, kd_b_);                                      \
            kd_test_fail(__FILE__, __LINE__, kd_msg_);                       \
            return;                                                          \
        }                                                                    \
    } while (0)

// Deterministic generator (numerical recipes LCG, upper bits).
static inline uint32_t kd_rand(uint32_t *s) {
    *s = *s * 1664525u + 1013904223u;
    return *s >> 8;
}
static inline int kd_rand_range(uint32_t *s, int lo, int hi) {   // inclusive
    return lo + (int)(kd_rand(s) % (uint32_t)(hi - lo + 1));
}

extern const kd_test_case kd_raster_tests[];
extern const kd_test_case kd_desktop_tests[];

#endif
