// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
void sf_option_position(const SfGame *g,unsigned option,int32_t *x,int32_t *y) {
    unsigned h=(g->history_pos+32-8*(option+1))&31;
    *x=g->history_x[h]-(int32_t)(12*(option+1))*256;
    *y=g->history_y[h]+(option?8:-8)*256;
    if(*x<0)*x=0;
    if(*x>304*256)*x=304*256;
    if(*y<24*256)*y=24*256;
    if(*y>(int32_t)(SF_HUD_TOP(g->height)-16)*256)*y=(int32_t)(SF_HUD_TOP(g->height)-16)*256;
}
void sf_player_step(SfGame *g, unsigned input) {
    int dx = !!(input&SF_RIGHT) - !!(input&SF_LEFT);
    int dy = !!(input&SF_DOWN) - !!(input&SF_UP);
    int axial=512+(g->power>3?3:g->power)*128;
    int speed=dx && dy?axial*181/256:axial;
    g->x += dx*speed; g->y += dy*speed;
    if (g->x < 0) g->x = 0;
    if (g->x > 304*256) g->x = 304*256;
    if (g->y < 24*256) g->y = 24*256;
    if (g->y > (int32_t)(SF_HUD_TOP(g->height)-16)*256)g->y=(int32_t)(SF_HUD_TOP(g->height)-16)*256;
    g->history_pos=(uint8_t)((g->history_pos+1)&31);
    g->history_x[g->history_pos]=g->x;g->history_y[g->history_pos]=g->y;
}
