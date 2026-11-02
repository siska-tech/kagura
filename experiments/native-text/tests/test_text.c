/* SPDX-License-Identifier: Apache-2.0 */
#include "kj_text.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); exit(1); } } while (0)
static unsigned changes;
static void changed(void *ctx,int32_t x,int32_t y) { (void)ctx; CHECK(x>=0 && x<9 && y>=0 && y<10); changes++; }
static void decoder(void) {
    unsigned tested=0;
    for (uint32_t cp=0;cp<=0x10ffff;cp++) {
        if (cp>=0xd800 && cp<=0xdfff) continue;
        uint8_t b[4]; unsigned n;
        if (cp<0x80) { b[0]=(uint8_t)cp; n=1; }
        else if (cp<0x800) { b[0]=(uint8_t)(0xc0|(cp>>6)); b[1]=(uint8_t)(0x80|(cp&63)); n=2; }
        else if (cp<0x10000) { b[0]=(uint8_t)(0xe0|(cp>>12)); b[1]=(uint8_t)(0x80|((cp>>6)&63)); b[2]=(uint8_t)(0x80|(cp&63)); n=3; }
        else { b[0]=(uint8_t)(0xf0|(cp>>18)); b[1]=(uint8_t)(0x80|((cp>>12)&63)); b[2]=(uint8_t)(0x80|((cp>>6)&63)); b[3]=(uint8_t)(0x80|(cp&63)); n=4; }
        kj_decoded d=kj_utf8_next(b,n); CHECK(d.valid && d.scalar==cp && d.consumed==n); tested++;
    }
    const uint8_t bad[][4]={{0xc0,0x80},{0xc1,0xbf},{0xe0,0x80,0x80},{0xed,0xa0,0x80},
        {0xf0,0x80,0x80,0x80},{0xf4,0x90,0x80,0x80},{0xf5,0x80,0x80,0x80},{0xff},{0x80},{0xe3,0x28,0xa1}};
    for (size_t i=0;i<sizeof bad/sizeof bad[0];i++) {
        kj_decoded d=kj_utf8_next(bad[i],4); CHECK(!d.valid && d.consumed==1 && d.scalar==0xfffd);
    }
    /* Exact-sized heap spans make sanitizer-visible overreads at truncation. */
    const uint8_t full[]={0xf0,0x90,0x80,0x80};
    for (size_t n=1;n<4;n++) {
        uint8_t *p=malloc(n); CHECK(p); memcpy(p,full,n);
        kj_decoded d=kj_utf8_next(p,n); CHECK(!d.valid && d.consumed==1); free(p);
    }
    CHECK(kj_utf8_next(NULL,0).consumed==0 && kj_utf8_next(NULL,9).consumed==0);
    const uint8_t mix[]="A\xe7\xa5\x9e" "B";
    CHECK(kj_utf8_prefix(mix,5,0)==0); CHECK(kj_utf8_prefix(mix,5,3)==1);
    CHECK(kj_utf8_prefix(mix,5,4)==4); CHECK(kj_utf8_prefix(mix,5,99)==5);
    printf("Unicode scalar roundtrips: %u\n",tested);
}
static void fonts(void) {
    kj_font f; CHECK(kj_font_open(&f,kj_misaki8.data,kj_misaki8.bytes)); CHECK(f.count==7171);
    uint8_t b[28]={'K','J','8','F',1,0,2,0,32,0,0,0,0,0,0,0,0,0,63,0,0xff,0x81,0x42,0x24,0x18,0x24,0x42,0x81};
    CHECK(kj_font_open(&f,b,sizeof b)); kj_glyph g=kj_lookup(&f,'?'); CHECK(!g.fallback && g.rows[0]==0xff && g.rows[7]==0x81);
    g=kj_lookup(&f,0x1f600); CHECK(g.fallback && g.rows[0]==0xff);
    b[18]=31; CHECK(!kj_font_open(&f,b,sizeof b) && !f.data);
    b[18]=32; CHECK(!kj_font_open(&f,b,sizeof b));
    b[18]=0; b[19]=0xd8; CHECK(!kj_font_open(&f,b,sizeof b));
    b[18]=63; b[19]=0;
    for (size_t n=0;n<sizeof b;n++) CHECK(!kj_font_open(&f,b,n));
    b[4]=2; CHECK(!kj_font_open(&f,b,sizeof b)); b[4]=1;
    b[6]=0; CHECK(!kj_font_open(&f,b,sizeof b)); b[6]=2;
    CHECK(!kj_font_open(NULL,b,sizeof b));
    b[6]=1; CHECK(kj_font_open(&f,b,18)); g=kj_lookup(&f,0x795e); CHECK(g.fallback && g.rows[0]==0xff); /* built-in box */
    kj_glyph space=kj_lookup(&kj_misaki8,0x3000); CHECK(!space.fallback);
    for (int i=0;i<8;i++) CHECK(space.rows[i]==0);
    f=kj_misaki8; uint8_t ascii[95*8]={0};
    CHECK(!kj_font_ascii(&f,ascii,sizeof ascii-1,4) && !f.ascii);
    CHECK(!kj_font_ascii(&f,ascii,sizeof ascii,9) && !f.ascii);
    CHECK(kj_font_ascii(&f,ascii,sizeof ascii,4) && kj_lookup(&f,'A').advance==4);
    CHECK(!kj_font_ascii(&f,NULL,0,4) && f.ascii);
    CHECK(kj_font_ascii(&f,NULL,0,0) && !f.ascii);
}
static void measurement(void) {
    const uint8_t s[]="A\xe7\xa5\x9e\xe6\xa5\xbd" "B\nC";
    kj_metrics m; CHECK(kj_measure(&kj_misaki8,s,sizeof s-1,&m)==KJ_OK);
    CHECK(m.width==32 && m.height==16 && m.end_x==8 && m.end_y==8 && m.glyphs==5 && !m.invalid && !m.fallbacks);
    CHECK(kj_measure(&kj_misaki8,NULL,0,&m)==KJ_OK && !m.width && !m.height);
    CHECK(kj_measure(&kj_misaki8,NULL,1,&m)==KJ_ARGUMENT);
    CHECK(kj_measure(NULL,s,1,&m)==KJ_ARGUMENT);
    CHECK(kj_measure(&kj_misaki8,s,1,NULL)==KJ_ARGUMENT);
    CHECK(kj_measure(&kj_misaki8,(const uint8_t *)"\n",1,&m)==KJ_OK && m.height==16 && !m.width);
    const uint8_t invalid[]={0xe0,0x80,0x80,0,0xf0,0x9f,0x98,0x80};
    CHECK(kj_measure(&kj_misaki8,invalid,sizeof invalid,&m)==KJ_OK && m.invalid==3 && m.fallbacks==5 && m.width==40);
    CHECK(kj_measure(&kj_misaki8,(const uint8_t *)"AB\rC",4,&m)==KJ_OK && m.width==16 && m.end_x==8);
}
static void raster(void) {
    uint8_t storage[72]; memset(storage,0xa7,sizeof storage);
    kj_surface4 s={storage+1,70,7,9,10,{0,0,9,10},changed,NULL};
    kj_glyph g=kj_lookup(&kj_misaki8,0x795e); CHECK(!g.fallback);
    const uint8_t text[]={0xe7,0xa5,0x9e};
    for (int mode=0;mode<3;mode++) for (int y=-9;y<=10;y++) for (int x=-9;x<=9;x++) {
        memset(storage,0xa7,sizeof storage); changes=0;
        s.clip=(kj_rect){mode==1?2:0,mode==1?3:0,mode==2?0:5,mode==2?0:6};
        int bg=mode==1?-1:4;
        CHECK(kj_draw4(&kj_misaki8,text,3,x,y,3,bg,&s,NULL)==KJ_OK);
        unsigned predicted=0;
        for (int yy=0;yy<10;yy++) for (int xx=0;xx<9;xx++) {
            unsigned old=(xx&1)?7:10,expected=old;
            int gx=xx-x,gy=yy-y;
            if (xx>=s.clip.x && xx<s.clip.x+s.clip.w && yy>=s.clip.y && yy<s.clip.y+s.clip.h && gx>=0 && gx<8 && gy>=0 && gy<8) {
                bool ink=(g.rows[gy]&(0x80u>>gx))!=0;
                if (ink) expected=3; else if (bg!=-1) expected=(unsigned)bg;
            }
            unsigned actual=(xx&1)?(s.pixels[yy*7+xx/2]&15u):(s.pixels[yy*7+xx/2]>>4);
            CHECK(actual==expected); if (actual!=old) predicted++;
        }
        CHECK(changes==predicted && storage[0]==0xa7 && storage[71]==0xa7);
        for (int yy=0;yy<10;yy++) CHECK((s.pixels[yy*7+4]&15)==7 && s.pixels[yy*7+5]==0xa7 && s.pixels[yy*7+6]==0xa7);
        changes=0; CHECK(kj_draw4(&kj_misaki8,text,3,x,y,3,bg,&s,NULL)==KJ_OK && changes==0);
    }
    s.clip=(kj_rect){INT32_MIN,INT32_MIN,INT32_MAX,INT32_MAX}; changes=0;
    CHECK(kj_draw4(&kj_misaki8,text,3,INT32_MIN,INT32_MAX,1,-1,&s,NULL)==KJ_OK && !changes);
    CHECK(kj_draw4(&kj_misaki8,text,3,INT32_MAX,INT32_MIN,1,-1,&s,NULL)==KJ_OK && !changes);
    CHECK(kj_draw4(&kj_misaki8,text,3,0,0,16,-1,&s,NULL)==KJ_ARGUMENT && !changes);
    CHECK(kj_draw4(&kj_misaki8,text,3,0,0,1,-2,&s,NULL)==KJ_ARGUMENT);
    s.bytes=67; CHECK(kj_draw4(&kj_misaki8,text,3,0,0,1,-1,&s,NULL)==KJ_ARGUMENT);
    s.bytes=70; s.stride=4; CHECK(kj_draw4(&kj_misaki8,text,3,0,0,1,-1,&s,NULL)==KJ_ARGUMENT);
}
int main(void) { decoder(); fonts(); measurement(); raster(); puts("TEXT_CORE_PASS strict UTF8 font validation metrics clipping packed4 guards"); return 0; }
