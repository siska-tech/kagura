/* SPDX-License-Identifier: Apache-2.0 */
#ifndef KJ_TEXT_H
#define KJ_TEXT_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum { KJ_OK, KJ_ARGUMENT, KJ_OVERFLOW } kj_status;
typedef struct { uint32_t scalar; uint8_t consumed; bool valid; } kj_decoded;
/* Invalid sequence: U+FFFD, consume ONE byte. Empty/NULL: consumed=0.
   All nonempty input spans must refer to at least n readable bytes. */
kj_decoded kj_utf8_next(const uint8_t *s,size_t n);
size_t kj_utf8_prefix(const uint8_t *s,size_t n,size_t capacity);

typedef struct {
    const uint8_t *data;
    size_t bytes;
    uint16_t count;
    /* Optional 95*8 rows for legacy printable ASCII; width must be 4 or 8. */
    const uint8_t *ascii;
    size_t ascii_bytes;
    uint8_t ascii_width;
} kj_font;
/* Validate KJ8F v1 size, sorted unique BMP scalars and immutable backing.
   No copying/allocation. On failure out is zeroed. Backing must outlive font. */
bool kj_font_open(kj_font *out,const void *data,size_t bytes);
/* Set a bounded 95*8-byte ASCII override; failure leaves font unchanged.
   NULL/0/0 disables it. Only use validated fonts or kj_misaki8 as the base. */
bool kj_font_ascii(kj_font *font,const void *rows,size_t bytes,uint8_t width);
extern const kj_font kj_misaki8;
typedef struct { const uint8_t *rows; uint8_t width,advance; bool fallback; } kj_glyph;
kj_glyph kj_lookup(const kj_font *font,uint32_t scalar);

typedef struct { int32_t x,y,w,h; } kj_rect;
typedef struct {
    int32_t width,height,end_x,end_y; /* relative cursor, not origin-inclusive */
    size_t glyphs,invalid,fallbacks;
} kj_metrics;
/* LF advances 8 pixels and resets x; CR resets x. Other controls (including
   embedded NUL) use fallback. No wrapping/shaping/normalization. Empty: 0x0.
   Nonempty text ending in LF includes its final empty 8-pixel line. */
kj_status kj_measure(const kj_font *font,const uint8_t *text,size_t bytes,kj_metrics *out);
typedef struct {
    void *context;
    void (*pixel)(void *,int32_t x,int32_t y,uint8_t color);
    kj_rect clip; /* half-open; nonpositive extents are empty */
} kj_target;
/* Preflights measurement/arguments before touching pixels. No allocation.
   bg=-1 is transparent; otherwise fg/bg must be palette indices 0..15.
   Callback is synchronous and must not mutate font/input or reenter target. */
kj_status kj_draw(const kj_font *font,const uint8_t *text,size_t bytes,
                  int32_t x,int32_t y,uint8_t fg,int bg,const kj_target *target,kj_metrics *out);
typedef struct {
    uint8_t *pixels;
    size_t bytes,stride;
    int32_t width,height;
    kj_rect clip;
    void (*changed)(void *,int32_t x,int32_t y); /* only after changed pixels */
    void *context;
} kj_surface4;
/* Linear packed 4bpp, even x in high nibble. Odd-width padding preserved. */
kj_status kj_draw4(const kj_font *font,const uint8_t *text,size_t bytes,
                   int32_t x,int32_t y,uint8_t fg,int bg,kj_surface4 *surface,kj_metrics *out);
#endif
