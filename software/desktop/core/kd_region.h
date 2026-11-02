// SPDX-License-Identifier: Apache-2.0
// Fixed-capacity rectangle sets.
//
// kd_damage is the screen damage list: rects that must be recomposed. Adding
// merges a rect into an existing one when they overlap or share an edge and
// the bounding box wastes no area beyond the overlap; otherwise it is kept
// separate. When the list is full, the new rect is merged into the entry whose
// bounding box grows least. The union of the list always covers every rect
// ever added (since the last clear).
//
// kd_region is a set of disjoint rects used by the compositor to track which
// part of a damage rect is still uncovered while layers are drawn top-down.
#ifndef KD_REGION_H
#define KD_REGION_H

#include "kd_fb.h"

#define KD_DAMAGE_MAX 16
#define KD_REGION_MAX 48

typedef struct {
    kd_rect r[KD_DAMAGE_MAX];
    uint8_t n;
    uint32_t added, merged, forced;   // forced: merges caused by a full list
} kd_damage;

typedef struct {
    kd_rect r[KD_REGION_MAX];
    uint8_t n;
    bool overflow;   // a subtraction did not fit; the set is then a superset
} kd_region;

void kd_damage_clear(kd_damage *d);
// Clips to the screen; empty rects are ignored.
void kd_damage_add(kd_damage *d, kd_rect r);
int32_t kd_damage_area(const kd_damage *d);   // sum of rect areas
// Tiles touched by at least one damage rect (each tile counted once).
unsigned kd_damage_tiles(const kd_damage *d);

void kd_region_init(kd_region *g, kd_rect r);
// Removes cut from every rect. Each rect splits into at most four bands
// (top, bottom, left, right). If the result does not fit, the uncut rect is
// kept, overflow is set and the region stays a superset of the true answer.
void kd_region_subtract(kd_region *g, kd_rect cut);

#endif
