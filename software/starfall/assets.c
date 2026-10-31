// SPDX-License-Identifier: Apache-2.0
// Original code-drawn 4bpp artwork; no external images or fonts.
#include "starfall.h"
#include <string.h>
static void pixel(uint8_t *p,unsigned tile,unsigned x,unsigned y,unsigned c) {
    unsigned a=tile*32+y*4+x/2;
    if(x&1)p[a]=(uint8_t)((p[a]&240)|c);else p[a]=(uint8_t)((p[a]&15)|(c<<4));
}
static void large(uint8_t *p,unsigned base,unsigned x,unsigned y,unsigned c) {
    pixel(p,base+(y/8)*2+x/8,x%8,y%8,c);
}
static const uint8_t digits[10][7]={
    {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},
    {30,1,1,14,1,1,30},{2,6,10,18,31,2,2},{31,16,16,30,1,1,30},
    {14,16,16,30,17,17,14},{31,1,2,4,8,8,8},{14,17,17,14,17,17,14},
    {14,17,17,15,1,1,14}
};
static const uint8_t letters[26][7]={
    {14,17,17,31,17,17,17},{30,17,17,30,17,17,30},{15,16,16,16,16,16,15},
    {30,17,17,17,17,17,30},{31,16,16,30,16,16,31},{31,16,16,30,16,16,16},
    {15,16,16,23,17,17,15},{17,17,17,31,17,17,17},{14,4,4,4,4,4,14},
    {7,2,2,2,2,18,12},{17,18,20,24,20,18,17},{16,16,16,16,16,16,31},
    {17,27,21,21,17,17,17},{17,25,21,19,17,17,17},{14,17,17,17,17,17,14},
    {30,17,17,30,16,16,16},{14,17,17,17,21,18,13},{30,17,17,30,20,18,17},
    {15,16,16,14,1,1,30},{31,4,4,4,4,4,4},{17,17,17,17,17,17,14},
    {17,17,17,17,17,10,4},{17,17,17,21,21,27,17},{17,17,10,4,10,17,17},
    {17,17,10,4,4,4,4},{31,1,2,4,8,16,31}
};
void sf_make_patterns(uint8_t *p) {
    memset(p,0,SF_PATTERNS*32);
    pixel(p,1,2,3,2);pixel(p,1,3,3,1);pixel(p,2,6,1,3);
    for(unsigned y=0;y<16;y++)for(unsigned x=0;x<16;x++) {
        int d=(int)y-7;if(d<0)d=-d;
        unsigned c=0;
        if(x>=2 && x<=14 && d<=2)c=y<7?1:4;
        if(x>=5 && x<=10 && d<=(int)(11-x))c=y<7?1:4;
        if(x>=7 && x<=11 && y>=5 && y<=7)c=5;
        if(x<=2 && d<=1)c=6;
        if((y==2 || y==12) && x>=3 && x<=7)c=4;
        if(c)large(p,4,x,y,c);
        /* Red drone, violet wave drone, armored turret, segmented boss. */
        if(x>=2 && x<14 && d<=5)large(p,12,x,y,(x+y)%5==0?1:7);
        if(x>=1 && x<15 && d<=(int)(x<8?x:15-x))large(p,16,x,y,d<2?8:9);
        if(x>=2 && x<14 && y>=3 && y<14)large(p,20,x,y,(x==3 || y==3)?3:4);
        if(x<8 && y>=6 && y<=8)large(p,20,x,y,6);
        if(x>=1 && x<15 && y>=1 && y<15)large(p,24,x,y,
            x==1 || y==1 || y==14?3:(x>5 && x<11 && y>5 && y<11?7:9));
        int r=((int)x-7)*((int)x-7)+((int)y-7)*((int)y-7);
        if(r<30)large(p,28,x,y,r<10?1:6);
        if(r<45 && r>6)large(p,32,x,y,r<25?1:6);
        if(r<52 && r>30 && (x+y)%3)large(p,44,x,y,6);
        if(x>=2 && x<=13 && y>=2 && y<=13)large(p,36,x,y,
            x==2 || x==13 || y==2 || y==13?6:11);
        if((x==6 && y>=5 && y<=10) || (y==5 && x>=6 && x<=9) ||
           (y==8 && x>=6 && x<=9) || (x==9 && y>=5 && y<=8))large(p,36,x,y,1);
    }
    for(unsigned y=0;y<8;y++)for(unsigned x=0;x<8;x++) {
        if(y==3 || y==4) { pixel(p,8,x,y,5);pixel(p,9,x,y,y==3?1:8); }
        int dx=(int)x-3,dy=(int)y-3,r=dx*dx+dy*dy;
        if(r<10)pixel(p,10,x,y,r<3?1:7);
        pixel(p,40,x,y,((x+y*3)%7==0)?3:11);
        pixel(p,41,x,y,y<2?5:(y==2?4:11));
        pixel(p,42,x,y,y>5?5:(y==5?4:11));
        pixel(p,43,x,y,(x==0 || y==0)?4:11);
    }
    /* 32x32 original siege drone: swept plates, recessed hot core, aft jets.
     * Four independently aligned 16x16 blocks consume two sprites per line. */
    for(unsigned y=0;y<32;y++)for(unsigned x=0;x<32;x++) {
        unsigned c=0;int dy=(int)y-15;if(dy<0)dy=-dy;
        if(x>=12 && x<=28 && dy<=10)c=x<15?3:9;
        if(x>=18 && x<=29 && dy>=10 && dy<=13)c=(y==2 || y==28)?3:4;
        if(x>=6 && x<=20 && dy<=6)c=dy>=5?3:11;
        if(x>=3 && x<12 && dy>=6 && dy<=8)c=4;
        int r=((int)x-12)*((int)x-12)+((int)y-15)*((int)y-15);
        if(r<26)c=r<8?10:7;
        if(x>=28 && x<=30 && (y==9 || y==10 || y==20 || y==21))c=5;
        if(c)large(p,48+((y/16)*2+x/16)*4,x%16,y%16,c);
    }
    for(unsigned ch='0';ch<='Z';ch++) {
        const uint8_t *rows=ch<='9'?digits[ch-'0']:ch>='A'?letters[ch-'A']:0;
        if(!rows)continue;
        for(unsigned y=0;y<7;y++)for(unsigned x=0;x<5;x++)
            if(rows[y]&(1u<<(4-x)))pixel(p,64+ch-32,x+1,y,1);
    }
    for(unsigned y=0;y<8;y++)for(unsigned x=0;x<8;x++)
        if(y>=2 && y<=5 && x<7)pixel(p,11,x,y,x>=5?6:y==2?1:4);
    static const char names[6][4]={"SPD","MSL","DBL","LAS","OPT","SHD"};
    for(unsigned icon=0;icon<6;icon++) {
        unsigned base=144+icon*4;
        for(unsigned y=0;y<16;y++)for(unsigned x=0;x<16;x++)
            large(p,base,x,y,x==0 || x==15 || y==0 || y==15?4:11);
        for(unsigned ch=0;ch<3;ch++)for(unsigned y=0;y<7;y++)for(unsigned x=0;x<3;x++)
            if(letters[names[icon][ch]-'A'][y]&(1u<<(4-x*2)))large(p,base,2+ch*4+x,4+y,1);
        for(unsigned x=3;x<13;x++)large(p,base,x,12,4);
    }
    /* All 16 partial segment widths have their own aligned 16x16 block.
     * Terrain clipping therefore matches the pixels, not only the hitbox. */
    for(unsigned length=1;length<=16;length++)for(unsigned y=4;y<8;y++)for(unsigned x=0;x<length;x++)
        large(p,192+(length-1)*4,x,y,y==5 || y==6?1:8);
    /* HUD panel, bulkheads, rivets and striped hangar lips (unused tile range). */
    for(unsigned y=0;y<8;y++)for(unsigned x=0;x<8;x++) {
        pixel(p,168,x,y,y==0?4:11);pixel(p,169,x,y,11);
        pixel(p,170,x,y,x==0 || y==0?3:11);
        pixel(p,171,x,y,x==0 || y==0?4:(x==4?3:11));
        pixel(p,172,x,y,(x==1 && y==1)||(x==6 && y==6)?1:11);
        pixel(p,173,x,y,y>=5?((x+y)%6<3?6:11):3);
        pixel(p,174,x,y,y<3?((x+y)%6<3?6:11):3);
        pixel(p,175,x,y,x<2?5:y==0 || y==7?4:11);
        if(x>=2 && x<=5 && y<=6)pixel(p,176,x,y,y>=4?6:x==2?1:4);
    }
    /* Original enemy silhouettes: swept interceptor, folding glider, diver.
     * Each animation frame is still one aligned 16x16 sprite. */
    memset(p+12*32,0,16*32);
    for(unsigned frame=0;frame<2;frame++)for(unsigned y=0;y<16;y++)for(unsigned x=0;x<16;x++) {
        int d=(int)y-7;if(d<0)d=-d;unsigned c=0;
        if(x>=2 && x<=13 && d<=2)c=y<7?3:7;
        if(x>=7 && x<=12 && d>=2 && d<=(int)x-5)c=7;
        if(x<4 && d<=1)c=1;
        if(x>=3 && x<=5 && y==6)c=8;
        if(x>=13 && x<15+frame && d<=1)c=6;
        if(c)large(p,frame?256:12,x,y,c);
        c=0;int fold=frame?1:0;
        if(x>=5 && x<=12 && d<=2)c=9;
        if(x>=3 && x<=13 && (y==3u+fold || y==11u-fold))c=8;
        if((x==3 || x==4) && d<=3)c=9;
        if(x>=2 && x<=6 && y>=6 && y<=8)c=x==2?1:6;
        if(c)large(p,frame?260:16,x,y,c);
        c=0;
        if(x>=2 && x<=13 && d<=2)c=y<7?1:3;
        if(x>=9 && x<=12 && d<=5)c=9;
        if(x<4 && d<=1)c=8;
        if(x>=4 && x<=7 && y==6)c=7;
        if(x>=14 && d<=(int)frame+1)c=6;
        if(c)large(p,frame?268:264,x,y,c);
    }
    for(unsigned y=0;y<16;y++)for(unsigned x=0;x<16;x++) {
        unsigned c=0;int r=((int)x-8)*((int)x-8)+((int)y-8)*((int)y-8);
        if(r<30)c=r>18?3:4;
        if(x>=2 && x<=13 && y>=12)c=y==12?5:3;
        if(x<=8 && y>=7 && y<=9)c=y==7?1:4;
        if(x>=5 && x<=7 && y==8)c=7;
        if((x==10 || x==12) && y>=6 && y<=10)c=11;
        if(c)large(p,20,x,y,c);
        int dx=(int)x-7,dy=(int)y-7;if(dx<0)dx=-dx;if(dy<0)dy=-dy;
        if(dx+dy<7 || (dx==dy && dx<6))large(p,288,x,y,dx+dy<3?1:6);
    }
    memcpy(p+272*32,p+48*32,16*32);
    for(unsigned y=10;y<21;y++)for(unsigned x=7;x<18;x++) {
        int r=((int)x-12)*((int)x-12)+((int)y-15)*((int)y-15);
        if(r<26)large(p,272+((y/16)*2+x/16)*4,x%16,y%16,r<9?1:10);
    }
    memcpy(p+300*32,p+4*32,4*32);memcpy(p+304*32,p+28*32,4*32);
    for(unsigned y=6;y<=8;y++)for(unsigned x=0;x<3;x++)large(p,300,x,y,x==0?10:6);
    for(unsigned y=5;y<10;y++)for(unsigned x=5;x<10;x++)large(p,304,x,y,x==7 && y==7?1:8);
    for(unsigned y=0;y<8;y++)for(unsigned x=0;x<8;x++) {
        int dx=(int)x-3,dy=(int)y-3;if(dx<0)dx=-dx;if(dy<0)dy=-dy;
        if(dx+dy<4)pixel(p,292,x,y,dx+dy<2?1:5);
        pixel(p,178,x,y,y%3==0?4:x==0?3:11);
        pixel(p,179,x,y,x==1 || x==6?3:y==3 || y==4?5:11);
    }
}
void sf_make_palette(uint8_t *p) {
    static const uint16_t c[16]={0x001,0xeff,0x345,0x568,0x168,0x6ef,0xf93,0xf45,
        0x8bf,0x647,0xff7,0x123,0x246,0x469,0x79a,0xfff};
    for(unsigned bank=0;bank<4;bank++)for(unsigned i=0;i<16;i++) {
        uint16_t color=c[i];
        if(bank==1) { if(i==1)color=0xff8;if(i==4)color=0xfa3;if(i==7)color=0xfa3;if(i==8)color=0xfb5;if(i==11)color=0x420; }
        if(bank==2) { if(i==4)color=0x4fc;if(i==11)color=0x032; }
        if(bank==3 && i)color=0xfff;
        p[(bank*16+i)*2]=(uint8_t)color;p[(bank*16+i)*2+1]=(uint8_t)(color>>8);
    }
}
void sf_make_map(uint8_t *map,unsigned height) {
    sf_make_map_at(map,height,0);
}
void sf_make_column(uint8_t *column,unsigned height,uint32_t col) {
    int top,bottom;sf_terrain(col,height,&top,&bottom);
    uint32_t rng=0x53544152u^col*2654435761u;
    for(unsigned row=0;row<32;row++) {
        rng=rng*1664525u+1013904223u;unsigned tile=(rng>>27)==0?1:(rng>>26)==1?2:0;
        if(row*8<(unsigned)top)tile=row*8==(unsigned)top-8?173:col%8==0?175:170;
        if(row*8>=(unsigned)bottom && col>=SF_BASE_WORLD_X/8)
            tile=row*8==(unsigned)bottom?174:col%8==0?175:(row+col)%4==0?172:171;
        if((tile==170 || tile==171) && col%8==3)tile=row%2?178:179;
        if(row*8>=SF_HUD_TOP(height))tile=row*8==SF_HUD_TOP(height)?168:169;
        column[row]=(uint8_t)tile;
    }
}
void sf_make_map_at(uint8_t *map,unsigned height,uint32_t world_tile) {
    memset(map,0,4096);
    for(unsigned i=0;i<64;i++) {
        uint32_t col=world_tile+i;uint8_t column[32];sf_make_column(column,height,col);
        for(unsigned row=0;row<32;row++)map[(row*64+(col&63))*2]=column[row];
    }
}
