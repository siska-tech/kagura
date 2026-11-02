// SPDX-License-Identifier: Apache-2.0
#include "image.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "kd_gfx.h"
#include "kd_tile4.h"

uint32_t kd_crc32(const uint8_t *data, size_t n) {
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++) {
        c ^= data[i];
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1)));
    }
    return ~c;
}

static void put32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

static bool chunk(FILE *f, const char *type, const uint8_t *data, size_t n) {
    uint8_t head[8];
    put32(head, (uint32_t)n);
    memcpy(head + 4, type, 4);
    uint8_t *crcbuf = malloc(n + 4);
    if (!crcbuf) return false;
    memcpy(crcbuf, type, 4);
    if (n) memcpy(crcbuf + 4, data, n);
    uint8_t tail[4];
    put32(tail, kd_crc32(crcbuf, n + 4));
    free(crcbuf);
    return fwrite(head, 1, 8, f) == 8 && (n == 0 || fwrite(data, 1, n, f) == n) && fwrite(tail, 1, 4, f) == 4;
}

bool kd_write_png_indexed(const char *path, const uint8_t *idx, int w, int h) {
    size_t raw_n = (size_t)h * (size_t)(w + 1);
    uint8_t *raw = malloc(raw_n);
    size_t blocks = raw_n / 65535 + 1;
    uint8_t *z = malloc(2 + raw_n + blocks * 5 + 4);
    if (!raw || !z) {
        free(raw);
        free(z);
        return false;
    }
    for (int y = 0; y < h; y++) {
        raw[(size_t)y * (w + 1)] = 0;   // filter: none
        memcpy(raw + (size_t)y * (w + 1) + 1, idx + (size_t)y * w, (size_t)w);
    }
    size_t zn = 0;
    z[zn++] = 0x78;
    z[zn++] = 0x01;
    uint32_t a = 1, b = 0;
    for (size_t off = 0; off < raw_n;) {
        size_t len = raw_n - off > 65535 ? 65535 : raw_n - off;
        z[zn++] = off + len == raw_n ? 1 : 0;
        z[zn++] = (uint8_t)len;
        z[zn++] = (uint8_t)(len >> 8);
        z[zn++] = (uint8_t)~len;
        z[zn++] = (uint8_t)(~len >> 8);
        memcpy(z + zn, raw + off, len);
        zn += len;
        for (size_t i = 0; i < len; i++) {
            a = (a + raw[off + i]) % 65521;
            b = (b + a) % 65521;
        }
        off += len;
    }
    put32(z + zn, (b << 16) | a);
    zn += 4;
    uint8_t ihdr[13];
    put32(ihdr, (uint32_t)w);
    put32(ihdr + 4, (uint32_t)h);
    ihdr[8] = 8;    // bit depth
    ihdr[9] = 3;    // indexed colour
    ihdr[10] = ihdr[11] = ihdr[12] = 0;
    uint8_t plte[16 * 3];
    for (int i = 0; i < 16; i++) {
        uint16_t c = kd_palette_rgb444[i];
        plte[i * 3] = (uint8_t)(((c >> 8) & 15) * 17);
        plte[i * 3 + 1] = (uint8_t)(((c >> 4) & 15) * 17);
        plte[i * 3 + 2] = (uint8_t)((c & 15) * 17);
    }
    static const uint8_t sig[8] = {0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A};
    FILE *f = fopen(path, "wb");
    bool ok = f && fwrite(sig, 1, 8, f) == 8 && chunk(f, "IHDR", ihdr, 13) && chunk(f, "PLTE", plte, sizeof plte) &&
              chunk(f, "IDAT", z, zn) && chunk(f, "IEND", NULL, 0);
    if (f) ok = fclose(f) == 0 && ok;
    free(raw);
    free(z);
    return ok;
}

bool kd_write_fb_png(const char *path, const kd_fb *fb, int scale, bool kagura240) {
    int lines = kagura240 ? 240 : KD_H;
    int w = KD_W * scale, h = lines * scale;
    uint8_t *idx = malloc((size_t)w * (size_t)h);
    if (!idx) return false;
    for (int y = 0; y < h; y++) {
        int line = y / scale;
        int dy = kagura240 ? kd_kagura_line_to_desktop(KD_PLACE_CENTER, line) : line;
        for (int x = 0; x < w; x++) idx[(size_t)y * w + x] = dy < 0 ? 0 : (uint8_t)kd_fb_get(fb, x / scale, dy);
    }
    bool ok = kd_write_png_indexed(path, idx, w, h);
    free(idx);
    return ok;
}
