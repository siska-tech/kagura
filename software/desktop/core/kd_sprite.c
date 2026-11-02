// SPDX-License-Identifier: Apache-2.0
#include "kd_sprite.h"

#include "kd_fault.h"

static unsigned offset(int x, int y) {
    return (unsigned)(((y >> 3) * 2 + (x >> 3)) * 32 + (y & 7) * 4 + ((x & 7) >> 1));
}

int kd_sprite_get(const kd_sprite *s, int x, int y) {
    if (x < 0 || y < 0 || x >= KD_SPRITE_W || y >= KD_SPRITE_H) return -1;
    uint8_t b = s->data[offset(x, y)];
    return (x & 1) ? (b & 15) : (b >> 4);
}

bool kd_sprite_set(kd_sprite *s, int x, int y, int color) {
    if (x < 0 || y < 0 || x >= KD_SPRITE_W || y >= KD_SPRITE_H || color < 0 || color > 15)
        return false;
    uint8_t *p = &s->data[offset(x, y)];
    bool low = (x & 1) != 0;
    if (KD_FAULTY(KD_FAULT_SPRITE_NIBBLE)) low = !low;
    uint8_t v = low ? (uint8_t)((*p & 0xF0) | color) : (uint8_t)((*p & 0x0F) | (color << 4));
    if (v == *p) return false;
    *p = v;
    return true;
}

void kd_sprite_export_hex(const kd_sprite *s, char out[KD_SPRITE_HEX + 1]) {
    static const char digits[] = "0123456789abcdef";
    for (int i = 0; i < KD_SPRITE_BYTES; i++) {
        out[2 * i] = digits[s->data[i] >> 4];
        out[2 * i + 1] = digits[s->data[i] & 15];
    }
    out[KD_SPRITE_HEX] = 0;
}

static int nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool kd_sprite_import_hex(kd_sprite *s, const char *hex, int *changed) {
    uint8_t next[KD_SPRITE_BYTES];
    for (int i = 0; i < KD_SPRITE_BYTES; i++) {
        int hi = nibble(hex[2 * i]);
        int lo = hi < 0 ? -1 : nibble(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) return false;
        next[i] = (uint8_t)(hi << 4 | lo);
    }
    if (hex[KD_SPRITE_HEX] != 0) return false;
    int n = 0;
    for (int i = 0; i < KD_SPRITE_BYTES; i++) {
        uint8_t d = s->data[i] ^ next[i];
        n += ((d >> 4) != 0) + ((d & 15) != 0);
        s->data[i] = next[i];
    }
    if (changed) *changed = n;
    return true;
}
