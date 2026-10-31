// SPDX-License-Identifier: Apache-2.0
#ifndef SF_BACKEND_H
#define SF_BACKEND_H
#include "starfall.h"
#include "kagura_host.h"
kh_status sf_backend_init(unsigned *height);
kh_status sf_backend_present(const SfGame *g, const SfFrame *f);
extern uint32_t sf_transfer_us, sf_blank_overruns;
extern uint32_t sf_commit_wait_us;
extern uint64_t sf_payload_bytes;
extern uint64_t sf_map_payload_bytes;
kh_status sf_audio_init(uint8_t caps);
kh_status sf_audio_update(const SfGame *g);
void sf_backend_set_idle(void (*callback)(void));
void sf_input_init(void);
unsigned sf_input_poll(void);
#endif
