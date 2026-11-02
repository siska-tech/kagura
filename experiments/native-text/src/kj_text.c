/* SPDX-License-Identifier: Apache-2.0 */
#include "kj_text.h"
#include <limits.h>
#include <string.h>

kj_decoded kj_utf8_next(const uint8_t *s,size_t n) {
    kj_decoded r={0xfffd,0,false};
    if (!s || !n) return r;
    r.consumed=1;
    uint8_t a=s[0];
    if (a<0x80) { r.scalar=a; r.valid=true; return r; }
    unsigned len; uint32_t cp;
    if (a>=0xc2 && a<=0xdf) { len=2; cp=a&31u; }
    else if (a>=0xe0 && a<=0xef) { len=3; cp=a&15u; }
    else if (a>=0xf0 && a<=0xf4) { len=4; cp=a&7u; }
    else return r;
    if (n<len) return r;
    for (unsigned i=1;i<len;i++) {
        if ((s[i]&0xc0u)!=0x80u) return r;
        cp=(cp<<6)|(s[i]&63u);
    }
    if ((len==2 && cp<0x80) || (len==3 && cp<0x800) ||
        (len==4 && cp<0x10000) || (cp>=0xd800 && cp<=0xdfff) || cp>0x10ffff) return r;
    r.scalar=cp; r.consumed=(uint8_t)len; r.valid=true; return r;
}
size_t kj_utf8_prefix(const uint8_t *s,size_t n,size_t capacity) {
    size_t used=0;
    if (!s) return 0;
    while (used<n && used<capacity) {
        kj_decoded d=kj_utf8_next(s+used,n-used);
        if (d.consumed>capacity-used) break;
        used+=d.consumed;
    }
    return used;
}
static unsigned le16(const uint8_t *p) { return p[0]|((unsigned)p[1]<<8); }
bool kj_font_open(kj_font *out,const void *data,size_t bytes) {
    if (!out) return false;
    memset(out,0,sizeof *out);
    const uint8_t *p=data;
    if (!p || bytes<8 || memcmp(p,"KJ8F\1\0",6)) return false;
    unsigned count=le16(p+6);
    if (!count || (bytes-8)/10!=count || (bytes-8)%10) return false;
    unsigned previous=0;
    for (unsigned i=0;i<count;i++) {
        unsigned cp=le16(p+8+(size_t)i*10);
        if ((i && cp<=previous) || (cp>=0xd800 && cp<=0xdfff)) return false;
        previous=cp;
    }
    out->data=p; out->bytes=bytes; out->count=(uint16_t)count; return true;
}
static bool valid_font(const kj_font *f) {
    return f && f->data && f->bytes>=8 && f->count &&
        (f->bytes-8)/10==f->count && (f->bytes-8)%10==0 &&
        (!f->ascii || (f->ascii_bytes>=95u*8u && (f->ascii_width==4 || f->ascii_width==8)));
}
bool kj_font_ascii(kj_font *f,const void *rows,size_t bytes,uint8_t width) {
    if (!valid_font(f)) return false;
    if (rows) { if (bytes<95u*8u || (width!=4 && width!=8)) return false; }
    else if (bytes || width) return false;
    f->ascii=rows; f->ascii_bytes=bytes; f->ascii_width=width; return true;
}
static const uint8_t *find(const kj_font *f,uint32_t cp) {
    if (cp>0xffff || (cp>=0xd800 && cp<=0xdfff)) return NULL;
    size_t lo=0,hi=f->count;
    while (lo<hi) {
        size_t mid=lo+(hi-lo)/2; const uint8_t *p=f->data+8+mid*10;
        unsigned code=le16(p);
        if (code==cp) return p+2;
        if (code<cp) lo=mid+1; else hi=mid;
    }
    return NULL;
}
kj_glyph kj_lookup(const kj_font *f,uint32_t cp) {
    static const uint8_t box[8]={0xff,0x81,0xa5,0x99,0x99,0xa5,0x81,0xff};
    kj_glyph g={box,8,8,true};
    if (!valid_font(f)) return g;
    if (f->ascii && cp>=32 && cp<=126) {
        g.rows=f->ascii+(cp-32)*8; g.width=g.advance=f->ascii_width; g.fallback=false; return g;
    }
    if (cp>=32 && cp!=127) {
        const uint8_t *rows=find(f,cp);
        if (rows) { g.rows=rows; g.fallback=false; return g; }
    }
    g.rows=find(f,0xfffd);
    if (!g.rows) g.rows=find(f,'?');
    if (!g.rows) g.rows=box;
    return g;
}
kj_status kj_measure(const kj_font *f,const uint8_t *s,size_t n,kj_metrics *out) {
    if (!out || !valid_font(f) || (!s && n)) return KJ_ARGUMENT;
    kj_metrics m={0}; int32_t x=0,y=0;
    for (size_t pos=0;pos<n;) {
        kj_decoded d=kj_utf8_next(s+pos,n-pos); pos+=d.consumed;
        if (!d.valid) m.invalid++;
        if (d.scalar=='\n') { if (y>INT32_MAX-16) return KJ_OVERFLOW; y+=8; x=0; continue; }
        if (d.scalar=='\r') { x=0; continue; }
        kj_glyph g=kj_lookup(f,d.scalar);
        if (x>INT32_MAX-g.advance) return KJ_OVERFLOW;
        x+=g.advance; if (x>m.width) m.width=x;
        m.glyphs++; if (g.fallback) m.fallbacks++;
    }
    m.end_x=x; m.end_y=y; m.height=n?y+8:0; *out=m; return KJ_OK;
}
kj_status kj_draw(const kj_font *f,const uint8_t *s,size_t n,int32_t x,int32_t y,
                  uint8_t fg,int bg,const kj_target *t,kj_metrics *out) {
    if (!t || !t->pixel || fg>15 || bg < -1 || bg>15) return KJ_ARGUMENT;
    kj_metrics m; kj_status status=kj_measure(f,s,n,&m); if (status!=KJ_OK) return status;
    int64_t px=x,py=y,left=t->clip.x,top=t->clip.y;
    int64_t right=left+(t->clip.w>0?t->clip.w:0),bottom=top+(t->clip.h>0?t->clip.h:0);
    if (right>(int64_t)INT32_MAX+1) right=(int64_t)INT32_MAX+1;
    if (bottom>(int64_t)INT32_MAX+1) bottom=(int64_t)INT32_MAX+1;
    for (size_t pos=0;pos<n;) {
        kj_decoded d=kj_utf8_next(s+pos,n-pos); pos+=d.consumed;
        if (d.scalar=='\n') { px=x; py+=8; continue; }
        if (d.scalar=='\r') { px=x; continue; }
        kj_glyph g=kj_lookup(f,d.scalar);
        if (px<right && px+g.width>left && py<bottom && py+8>top) {
            for (unsigned row=0;row<8;row++) for (unsigned col=0;col<g.width;col++) {
                int64_t xx=px+col,yy=py+row;
                if (xx<left || xx>=right || yy<top || yy>=bottom) continue;
                bool ink=(g.rows[row]&(0x80u>>col))!=0;
                if (ink || bg!=-1) t->pixel(t->context,(int32_t)xx,(int32_t)yy,ink?fg:(uint8_t)bg);
            }
        }
        px+=g.advance;
    }
    if (out) *out=m;
    return KJ_OK;
}
static void put4(void *context,int32_t x,int32_t y,uint8_t color) {
    kj_surface4 *s=context; uint8_t *p=s->pixels+(size_t)y*s->stride+(unsigned)x/2;
    uint8_t next=(uint8_t)((x&1)?((*p&0xf0u)|color):((*p&15u)|((unsigned)color<<4)));
    if (next!=*p) { *p=next; if (s->changed) s->changed(s->context,x,y); }
}
kj_status kj_draw4(const kj_font *f,const uint8_t *s,size_t n,int32_t x,int32_t y,
                   uint8_t fg,int bg,kj_surface4 *surface,kj_metrics *out) {
    if (!surface || !surface->pixels || surface->width<=0 || surface->height<=0) return KJ_ARGUMENT;
    size_t rowbytes=(size_t)surface->width/2+((unsigned)surface->width&1u);
    if (surface->stride<rowbytes || surface->bytes<rowbytes ||
        (size_t)(surface->height-1)>(surface->bytes-rowbytes)/surface->stride) return KJ_ARGUMENT;
    kj_rect c=surface->clip;
    int64_t right=(int64_t)c.x+(c.w>0?c.w:0),bottom=(int64_t)c.y+(c.h>0?c.h:0);
    int32_t left=c.x>0?c.x:0,top=c.y>0?c.y:0;
    if (right>surface->width) right=surface->width;
    if (bottom>surface->height) bottom=surface->height;
    kj_target target={surface,put4,{left,top,right>left?(int32_t)(right-left):0,bottom>top?(int32_t)(bottom-top):0}};
    return kj_draw(f,s,n,x,y,fg,bg,&target,out);
}
