// SPDX-License-Identifier: Apache-2.0
#include "starfall.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static SfGame a,b;
static SfFrame frame;
static void fresh(unsigned height) { sf_init(&a,height,123);sf_start(&a);sf_begin_play(&a);a.invincible=0; }
static void regressions(unsigned height) {
    /* A real trigger starts all three independent rays on the same tick. */
    fresh(height);a.weapon=SF_LASER;a.options=2;sf_bullet_step(&a,SF_FIRE);
    assert(a.beam.active && a.option_beams[0].active && a.option_beams[1].active);
    assert(a.beam.x==a.x+14*256 && a.beam.y==a.y+4*256);
    for(unsigned i=0;i<2;i++) {
        int32_t x,y;sf_option_position(&a,i,&x,&y);
        assert(a.option_beams[i].x==x+14*256 && a.option_beams[i].y==y+4*256);
        assert(a.option_beams[i].y!=a.beam.y);
    }
    sf_collision_step(&a);assert(sf_render(&a,&frame));
    assert((frame.oam[8+3]&4) && (frame.oam[22*8+3]&4) && (frame.oam[26*8+3]&4));
    sf_hit_player(&a);assert(!a.beam.active && !a.option_beams[0].active && !a.option_beams[1].active);
    /* Reproduce the old phantom floor by sampling future ring columns with
     * the old sky band; prove every corrected pre-entry pixel stays open. */
    unsigned old_floor_samples=0;uint8_t map[4096];
    for(unsigned tick=936;tick<SF_BASE_APPROACH_TICK;tick+=4) {
        sf_make_map_at(map,height,tick/8);
        for(unsigned y=0;y<SF_HUD_TOP(height);y+=4)for(unsigned x=0;x<320;x+=4) {
            unsigned old_scroll=y>=48 && y<height-48?tick/3:tick;
            unsigned old_tile=map[((y/8)*64+((x+old_scroll)&511)/8)*2];
            if(old_tile>=168)old_floor_samples++;
            unsigned scroll=y>=48 && y<SF_SKY_BOTTOM(height)?tick/3:tick;
            unsigned tile=map[((y/8)*64+((x+scroll)&511)/8)*2];
            assert(tile<3);
        }
    }
    assert(old_floor_samples>0);
    /* Extreme overlap: all damaging sprites stay, all three rays keep heads. */
    fresh(height);a.x=80*256;a.y=80*256;a.options=2;a.pickup_active=true;
    a.pickup_x=a.x;a.pickup_y=a.y;a.missile=(SfShot){a.x,a.y,true};
    for(unsigned i=0;i<32;i++) { a.history_x[i]=a.x;a.history_y[i]=a.y; }
    a.history_y[24]+=8*256;a.history_y[16]-=8*256;
    for(unsigned i=0;i<SF_ENEMIES;i++)a.enemies[i]=(SfEnemy){200*256,a.y,80,0,10,SF_SCOUT,0,true,false};
    for(unsigned i=0;i<SF_HOSTILES;i++)a.hostile[i]=(SfHostile){a.x,a.y,0,0,true};
    a.beam=(SfBeam){a.x,a.y,0,0,64,true};
    for(unsigned i=0;i<2;i++)a.option_beams[i]=a.beam;
    sf_laser_fit(&a);assert(a.beam.length==32 && a.option_beams[0].length==16 && a.option_beams[1].length==16);
    assert(sf_render(&a,&frame) && frame.peak_line==16);
    for(unsigned i=5;i<16;i++)assert(frame.oam[i*8+3]&4);
    /* Support beams use their own collision and hit history. */
    fresh(height);a.option_beams[0]=(SfBeam){100*256,70*256,0,0,64,true};
    a.enemies[0]=(SfEnemy){120*256,70*256,70,0,6,SF_DIVER,0,true,false};
    sf_collision_step(&a);assert(a.enemies[0].hp==3 && a.enemy_flash[0]);
    sf_collision_step(&a);assert(a.enemies[0].hp==3);
    fresh(height);a.enemy_group[0]=3;a.group_remaining[2]=1;
    a.enemies[0]=(SfEnemy){100*256,80*256,80,0,1,SF_DIVER,0,true,true};
    a.shots[0]=(SfShot){100*256,80*256,true};sf_collision_step(&a);
    assert(a.score==600 && a.pickup_active && a.capsule_queue==1);
    fresh(height);a.y=100*256;
    a.enemies[0]=(SfEnemy){320*256,60*256,60,31,2,SF_DIVER,0,true,false};
    sf_enemy_step(&a);assert(a.enemies[0].origin_y==100 && a.enemies[0].y>60*256);
    a.enemies[0]=(SfEnemy){100*256,24*256,24,0,2,SF_TURRET,1,true,false};
    assert(sf_render(&a,&frame) && (frame.oam[5*8+3]&32));
    printf("PASS regression options_simultaneous phantom_floor_old_samples=%u corrected=0\n",old_floor_samples);
}
static void weapons(unsigned height) {
    fresh(height);
    for(unsigned n=1;n<=7;n++) {
        a.pickup_active=true;a.pickup_x=a.x+256;a.pickup_y=a.y;sf_powerup_step(&a);
        assert(a.gauge==(n-1)%6+1 && a.power==0);
    }
    sf_step(&a,SF_EQUIP);assert(a.power==1 && a.gauge==0);
    a.gauge=SF_SPEED;sf_step(&a,SF_EQUIP);assert(a.power==1 && a.gauge==SF_SPEED);
    sf_step(&a,0);sf_step(&a,SF_EQUIP);assert(a.power==2 && a.gauge==0);
    a.shield=3;
    for(unsigned i=0;i<3;i++) { a.invincible=0;sf_hit_player(&a);assert(a.lives==3 && a.shield==2-i); }
    a.invincible=0;sf_hit_player(&a);assert(a.lives==2 && a.power==0 && !a.missile_enabled);
    /* One laser crosses two targets and damages each only once per flight. */
    fresh(height);a.beam=(SfBeam){100*256,80*256,0,0,64,true};
    a.enemies[0]=(SfEnemy){112*256,80*256,80,0,6,SF_SCOUT,0,true,false};
    a.enemies[1]=(SfEnemy){144*256,80*256,80,0,1,SF_SCOUT,0,true,false};
    sf_collision_step(&a);assert(a.enemies[0].hp==3 && !a.enemies[1].active && a.beam.active);
    sf_collision_step(&a);assert(a.enemies[0].hp==3);
    a.enemy_serial[0]++;sf_collision_step(&a);assert(!a.enemies[0].active);
    /* First terrain pixel clips the rendered laser as well as its hitbox. */
    fresh(height);a.stage_tick=1648;a.scroll=1648&511;a.beam=(SfBeam){0,32*256,0,0,64,true};
    sf_collision_step(&a);assert(a.beam.length==16);assert(sf_render(&a,&frame));
    a.beam=(SfBeam){80*256,80*256,0,0,21,true};assert(sf_render(&a,&frame));
    assert(frame.oam[8+4]==252 && frame.oam[16+4]==208 && !(frame.oam[24+3]&4));
    /* Ground missile follows all 64 columns and destroys a turret. */
    fresh(height);a.stage_tick=1600;a.missile=(SfShot){80*256,60*256,true};a.missile_enabled=true;a.missile_vy=256;
    for(unsigned n=0;n<10;n++) {
        a.stage_tick=1600+n;sf_bullet_step(&a,0);
        int top,bottom;sf_terrain(((unsigned)(a.missile.x/256)+a.scroll)/8,height,&top,&bottom);
        if(a.missile.active)assert(a.missile.y<(int32_t)SF_HUD_TOP(height)*256);
    }
    assert(a.missile.x==85*256 && a.missile.y>80*256); /* predominantly downward */
    for(unsigned col=0;col<64;col++) {
        a.stage_tick=1600+col*8;a.missile=(SfShot){100*256,(int32_t)height*256,true};a.missile_grounded=false;
        sf_bullet_step(&a,0);int top,bottom;
        sf_terrain(((unsigned)(a.missile.x/256)+a.stage_tick)/8,height,&top,&bottom);
        assert(a.missile.active && a.missile.y==(bottom-8)*256);
    }
    fresh(height);a.missile=(SfShot){80*256,80*256,true};a.missile_vy=256;
    for(unsigned n=0;n<80;n++)sf_bullet_step(&a,0);
    assert(!a.missile.active); /* space has no invisible floor to skate on */
    fresh(height);a.missile=(SfShot){100*256,80*256,true};
    a.enemies[0]=(SfEnemy){100*256,80*256,80,0,2,SF_TURRET,0,true,false};
    sf_collision_step(&a);assert(!a.missile.active && !a.enemies[0].active);
    /* Entire formation earns a second capsule; one escaped member cancels it. */
    fresh(height);a.group_remaining[0]=1;a.enemy_group[0]=1;
    a.enemies[0]=(SfEnemy){100*256,80*256,80,0,1,SF_SCOUT,0,true,true};
    a.shots[0]=(SfShot){100*256,80*256,true};sf_collision_step(&a);
    assert(a.pickup_active && a.capsule_queue==1 && a.score==600);
    fresh(height);a.group_remaining[0]=1;a.enemy_group[0]=1;sf_stage_lost(&a,0);
    a.enemies[0]=(SfEnemy){100*256,80*256,80,0,1,SF_SCOUT,0,true,false};
    a.shots[0]=(SfShot){100*256,80*256,true};sf_collision_step(&a);
    assert(!a.pickup_active && a.score==100);
}
static void checks(unsigned height) {
    fresh(height);int32_t x=a.x,y=a.y;
    sf_player_step(&a,SF_LEFT|SF_RIGHT|SF_UP|SF_DOWN);assert(a.x==x && a.y==y);
    sf_player_step(&a,SF_RIGHT|SF_DOWN);assert(a.x-x==362 && a.y-y==362);
    /* A capsule advances selection; equipment changes only on activation. */
    fresh(height);a.enemies[0]=(SfEnemy){100*256,80*256,80,0,1,SF_SCOUT,0,true,true};
    a.shots[0]=(SfShot){100*256,80*256,true};sf_collision_step(&a);
    assert(!a.enemies[0].active && !a.shots[0].active && a.score==100 && a.pickup_active);
    a.x=a.pickup_x-256;a.y=a.pickup_y;sf_powerup_step(&a);
    assert(a.power==0 && a.gauge==SF_SPEED && a.score==600 && !a.pickup_active);
    assert(sf_equip(&a) && a.power==1 && a.gauge==0);
    a.gauge=SF_MISSILE;assert(sf_equip(&a) && a.missile_enabled);
    a.gauge=SF_G_DOUBLE;assert(sf_equip(&a) && a.weapon==SF_DOUBLE);
    a.gauge=SF_G_LASER;assert(sf_equip(&a) && a.weapon==SF_LASER);
    a.gauge=SF_OPTION;assert(sf_equip(&a));a.gauge=SF_OPTION;assert(sf_equip(&a));
    a.gauge=SF_OPTION;assert(!sf_equip(&a) && a.gauge==SF_OPTION);
    a.gauge=SF_SHIELD;assert(sf_equip(&a) && a.shield==3);a.shield=0;
    /* Both support pod emissions must originate at the displayed history slot. */
    for(unsigned i=0;i<32;i++) { a.history_x[i]=(int32_t)i*256;a.history_y[i]=80*256; }
    a.weapon=SF_NORMAL;a.history_pos=0;a.emitter=1;a.shots[0].active=true;a.cooldown=0;sf_bullet_step(&a,SF_FIRE);
    assert(a.shots[1].active && a.shots[1].x==a.history_x[24]+2*256);
    sf_hit_player(&a);assert(a.lives==2 && a.invincible==180 && a.options==0 && a.power==0);
    sf_hit_player(&a);assert(a.lives==2); /* invincibility prevents repeat damage */
    a.invincible=0;sf_hit_player(&a);a.invincible=0;sf_hit_player(&a);assert(a.state==SF_OVER);
    a.state_age=61;a.start_was_down=false;sf_step(&a,SF_FIRE);assert(a.state==SF_TITLE && a.lives==3);
    /* Each generated world column agrees with collision, before/inside the base. */
    for(unsigned c=0;c<512;c++) {
        uint8_t column[32];sf_make_column(column,height,c);
        int top,bottom;sf_terrain(c,height,&top,&bottom);a.stage_tick=c*8;a.scroll=(uint16_t)((c*8)&511);
        if(top) { assert(sf_terrain_hit(&a,0,top-1,1,1));assert(column[top/8-1]==173); }
        assert(!sf_terrain_hit(&a,0,top,1,bottom-top));assert(sf_terrain_hit(&a,0,bottom,1,1));
        if(c>=SF_BASE_WORLD_X/8 && bottom<(int)SF_HUD_TOP(height))assert(column[bottom/8]==174);
        if(c<SF_BASE_WORLD_X/8)for(unsigned y=0;y<SF_HUD_TOP(height);y++)assert(column[y/8]<3);
        assert(column[SF_HUD_TOP(height)/8]==168);
    }
    /* Reserve all damaging sprites at exactly one scanline. Effects may be dropped. */
    fresh(height);a.x=80*256;a.y=80*256;a.options=2;a.pickup_active=true;a.pickup_x=a.x;a.pickup_y=a.y;
    a.missile=(SfShot){a.x,a.y,true};
    for(unsigned i=0;i<32;i++) { a.history_x[i]=a.x;a.history_y[i]=a.y; }
    a.history_y[24]+=8*256;a.history_y[16]-=8*256;
    for(unsigned i=0;i<SF_SHOTS;i++)a.shots[i]=(SfShot){a.x,a.y,true};
    for(unsigned i=0;i<SF_ENEMIES;i++)a.enemies[i]=(SfEnemy){a.x,a.y,80,0,2,SF_SCOUT,0,true,false};
    for(unsigned i=0;i<SF_HOSTILES;i++)a.hostile[i]=(SfHostile){a.x,a.y,0,0,true};
    sf_explode(&a,80,80);assert(sf_render(&a,&frame));assert(frame.peak_line==16 && frame.dropped_effects==1);
    for(unsigned i=0;i<16;i++)assert(frame.oam[i*8+3]&4);
    for(unsigned i=0;i<SF_SHOTS;i++)a.shots[i].active=false;
    a.beam=(SfBeam){a.x,a.y,0,0,64,true};assert(sf_render(&a,&frame) && frame.peak_line==16);
    for(unsigned i=0;i<6;i++)assert(frame.oam[(48+i)*8+2]==SF_HUD_TOP(height)+4);
    int32_t low=(int32_t)(SF_HUD_TOP(height)-16)*256;
    a.y=a.pickup_y=low;a.beam.y=low+4*256;a.missile.y=low+8*256;
    for(unsigned i=0;i<32;i++)a.history_y[i]=low;
    a.history_y[16]-=8*256;
    for(unsigned i=0;i<SF_ENEMIES;i++)a.enemies[i].y=low;
    for(unsigned i=0;i<SF_HOSTILES;i++)a.hostile[i].y=low+8*256;
    assert(sf_render(&a,&frame) && frame.peak_line<=16); /* beam tail and HUD do not overlap */
    /* Boss appears at the authored tick; clear requires destruction, not just time. */
    fresh(height);a.stage_frame=2759;a.stage_tick=2640;sf_stage_step(&a);
    bool boss=false;for(unsigned i=0;i<SF_ENEMIES;i++)boss|=a.enemies[i].active && a.enemies[i].type==SF_BOSS;
    assert(boss);a.stage_frame=SF_STAGE_TICKS;sf_step(&a,0);assert(a.state==SF_PLAY);
    a.boss_dead=true;sf_step(&a,0);assert(a.state==SF_CLEAR);
    sf_init(&a,height,123);assert(a.state==SF_TITLE);sf_step(&a,SF_FIRE);assert(a.state==SF_INTRO);
}
int main(void) {
    for(unsigned height=180;height<=240;height+=60) {
        checks(height);weapons(height);regressions(height);sf_init(&a,height,123);sf_init(&b,height,123);
        for(unsigned t=0;t<216000;t++) {
            /* Repeated deaths/restarts, waves, terrain and bullet lifetimes. */
            unsigned input=((t/73)%64)|(t%120<110?SF_FIRE:0);
            sf_step(&a,input);sf_step(&b,input);assert(!memcmp(&a,&b,sizeof a));
            assert(a.x>=0 && a.x<=304*256 && a.y>=24*256 && a.y<=(int)(SF_HUD_TOP(height)-16)*256);
            assert(a.scroll<512 && sf_render(&a,&frame) && frame.peak_line<=16);
        }
        /* Full authored stage, including boss, with no collision immunity shortcut
         * in production; the test refreshes invincibility to inspect all events. */
        fresh(height);bool boss_seen=false;
        for(unsigned t=0;t<4000;t++) {
            for(unsigned i=0;i<SF_ENEMIES;i++)if(a.enemies[i].active && a.enemies[i].type==SF_BOSS) {
                a.x=230*256;a.y=a.enemies[i].y;
            }
            a.invincible=2;sf_step(&a,SF_FIRE);
            if(a.stage_tick<1450)for(unsigned i=0;i<SF_ENEMIES;i++)
                assert(!a.enemies[i].active || a.enemies[i].type!=SF_TURRET);
            for(unsigned i=0;i<SF_ENEMIES;i++)boss_seen|=a.enemies[i].active && a.enemies[i].type==SF_BOSS;
            assert(sf_render(&a,&frame));
            if(a.state==SF_CLEAR)break;
        }
        assert(boss_seen && a.boss_dead && a.state==SF_CLEAR);
        for(unsigned weapon=SF_NORMAL;weapon<=SF_LASER;weapon++) {
            fresh(height);a.weapon=(uint8_t)weapon;a.options=2;a.power=3;a.missile_enabled=true;
            for(unsigned t=0;t<4000;t++) {
                a.invincible=2;sf_step(&a,SF_FIRE|((t/47)%16));
                assert(sf_render(&a,&frame) && frame.peak_line<=16);
            }
        }
        printf("PASS height=%u replay_steps=216000 stage=4000 peak_limit=16 state_bytes=%zu frame_bytes=%zu\n",height,sizeof a,sizeof frame);
    }
    return 0;
}
