// SPDX-License-Identifier: Apache-2.0
#include "kd_region.h"

#include "kd_fault.h"

void kd_damage_clear(kd_damage *d) {
    d->n = 0;
}

// Overlapping, or touching along an edge (not just at a corner).
static bool touches(kd_rect a, kd_rect b) {
    bool xo = a.x < b.x + b.w && b.x < a.x + a.w;
    bool yo = a.y < b.y + b.h && b.y < a.y + a.h;
    bool xt = a.x <= b.x + b.w && b.x <= a.x + a.w;
    bool yt = a.y <= b.y + b.h && b.y <= a.y + a.h;
    return (xo && yt) || (yo && xt);
}

static bool cheap_merge(kd_rect a, kd_rect b) {
    int32_t box = kd_rect_area(kd_rect_union(a, b));
    int32_t cover = kd_rect_area(a) + kd_rect_area(b) - kd_rect_area(kd_rect_intersect(a, b));
    return touches(a, b) && box <= cover;
}

void kd_damage_add(kd_damage *d, kd_rect r) {
    r = kd_rect_intersect(r, kd_rect_make(0, 0, KD_W, KD_H));
    if (kd_rect_empty(r)) return;
    d->added++;
    // Merging can make the grown rect absorb others, so repeat until stable.
    for (;;) {
        int hit = -1;
        for (int i = 0; i < d->n; i++) {
            if (kd_rect_contains(d->r[i], r)) return;
            if (cheap_merge(d->r[i], r)) { hit = i; break; }
        }
        if (hit < 0) break;
        r = kd_rect_union(r, d->r[hit]);
        d->r[hit] = d->r[--d->n];
        d->merged++;
    }
    if (d->n < KD_DAMAGE_MAX) {
        d->r[d->n++] = r;
        return;
    }
    if (KD_FAULTY(KD_FAULT_DAMAGE_DROP)) return;
    int best = 0;
    int32_t best_growth = INT32_MAX;
    for (int i = 0; i < d->n; i++) {
        int32_t g = kd_rect_area(kd_rect_union(d->r[i], r)) - kd_rect_area(d->r[i]);
        if (g < best_growth) { best_growth = g; best = i; }
    }
    kd_rect merged = kd_rect_union(d->r[best], r);
    d->r[best] = d->r[--d->n];
    d->forced++;
    kd_damage_add(d, merged);   // re-merge; the list has a free slot now
    d->added--;                 // the recursive call counted it again
}

int32_t kd_damage_area(const kd_damage *d) {
    int32_t a = 0;
    for (int i = 0; i < d->n; i++) a += kd_rect_area(d->r[i]);
    return a;
}

unsigned kd_damage_tiles(const kd_damage *d) {
    uint8_t seen[(KD_TILES + 7) / 8] = {0};
    unsigned n = 0;
    for (int i = 0; i < d->n; i++) {
        kd_rect r = d->r[i];
        for (int ty = r.y >> 3; ty <= (r.y + r.h - 1) >> 3; ty++)
            for (int tx = r.x >> 3; tx <= (r.x + r.w - 1) >> 3; tx++) {
                unsigned t = (unsigned)(ty * KD_TILE_COLS + tx);
                if (!(seen[t >> 3] & (1u << (t & 7)))) {
                    seen[t >> 3] |= (uint8_t)(1u << (t & 7));
                    n++;
                }
            }
    }
    return n;
}

void kd_region_init(kd_region *g, kd_rect r) {
    g->n = 0;
    g->overflow = false;
    if (!kd_rect_empty(r)) g->r[g->n++] = r;
}

void kd_region_subtract(kd_region *g, kd_rect cut) {
    if (kd_rect_empty(cut)) return;
    for (int i = 0; i < g->n; i++) {
        kd_rect r = g->r[i];
        kd_rect c = kd_rect_intersect(r, cut);
        if (kd_rect_empty(c)) continue;
        kd_rect parts[4];
        int np = 0;
        if (c.y > r.y) parts[np++] = kd_rect_make(r.x, r.y, r.w, c.y - r.y);
        if (c.y + c.h < r.y + r.h) parts[np++] = kd_rect_make(r.x, c.y + c.h, r.w, r.y + r.h - c.y - c.h);
        if (c.x > r.x) parts[np++] = kd_rect_make(r.x, c.y, c.x - r.x, c.h);
        if (c.x + c.w < r.x + r.w) parts[np++] = kd_rect_make(c.x + c.w, c.y, r.x + r.w - c.x - c.w, c.h);
        if (g->n - 1 + np > KD_REGION_MAX) {
            g->overflow = true;
            continue;
        }
        // Replace r by the last rect, append the parts, and revisit index i
        // (now the old last rect, which has not been cut yet).
        g->r[i] = g->r[--g->n];
        for (int k = 0; k < np; k++) g->r[g->n++] = parts[k];
        // Appended parts are disjoint from cut; they may be revisited harmlessly.
        i--;
    }
}
