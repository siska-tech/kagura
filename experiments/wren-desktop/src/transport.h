#ifndef WD_TRANSPORT_H
#define WD_TRANSPORT_H
#include "kd_tile4.h"
#include "kagura_host.h"
typedef struct {
    bool ready, faulted;
    kh_status error;
    unsigned acknowledged_runs, acknowledged_tiles;
} wd_transport;
bool wd_transport_init(wd_transport *t, uint8_t scratch[1280]);
bool wd_transport_sink(void *ctx, unsigned first, unsigned count, const uint8_t *data);
#endif
