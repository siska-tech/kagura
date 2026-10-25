// SPDX-License-Identifier: Apache-2.0
#ifndef KAGURA_SPECTACULAR_DEMO_H
#define KAGURA_SPECTACULAR_DEMO_H

#include <stdint.h>
#include "kagura_host.h"

// Run the Pico-generated audio/visual showcase. A duration of zero runs until
// a character is received over USB CDC.
kh_status kagura_spectacular_demo(uint32_t seconds);

#endif
