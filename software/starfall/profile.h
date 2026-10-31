// SPDX-License-Identifier: Apache-2.0
#ifndef SF_PROFILE_H
#define SF_PROFILE_H
#include <stdint.h>
typedef struct { uint32_t samples[256],count,max;uint64_t sum; } SfProfile;
void sf_profile_add(SfProfile *p,uint32_t microseconds);
uint32_t sf_profile_p95(const SfProfile *p);
#endif
