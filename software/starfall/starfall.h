// SPDX-License-Identifier: Apache-2.0
#ifndef STARFALL_H
#define STARFALL_H
#include <stdbool.h>
#include <stdint.h>
#define SF_SHOTS 4
#define SF_ENEMIES 4
#define SF_HOSTILES 3
#define SF_EFFECTS 6
#define SF_SPRITES 64
#define SF_PATTERNS 704
#define SF_PALETTE_BYTES 160
#define SF_STAGE_COUNT 6
#define SF_TITLE_IDLE_TICKS 900u
#define SF_DEMO_TICKS 2400u
#define SF_STAGE_TICKS 3600u
#define SF_BASE_WORLD_X 1440u
#define SF_BASE_APPROACH_TICK (SF_BASE_WORLD_X-320u)
#define SF_HUD_TOP(height) (((height)/8u-3u)*8u)
#define SF_SKY_BOTTOM(height) (SF_HUD_TOP(height)-48u)
enum { SF_LEFT=1, SF_RIGHT=2, SF_UP=4, SF_DOWN=8, SF_FIRE=16, SF_EQUIP=32 };
enum { SF_NORMAL, SF_DOUBLE, SF_LASER };
enum { SF_SPEED=1, SF_MISSILE, SF_G_DOUBLE, SF_G_LASER, SF_OPTION, SF_SHIELD };
enum { SF_TITLE, SF_PLAY, SF_OVER, SF_CLEAR, SF_BOOT, SF_INTRO, SF_ENDING };
enum { SF_OPENING, SF_MAIN_AREA, SF_CLIMAX, SF_WARNING, SF_BOSS_BATTLE, SF_DEFEAT };
typedef struct { uint16_t tick;uint8_t type,lane,count,gap,formation; } SfStageEvent;
typedef struct {
    const char *name;uint8_t theme,boss_kind,music;bool ready;
    const SfStageEvent *events;uint8_t event_count;uint16_t warning_frame,boss_frame;
} SfStageDef;
enum { SF_SCOUT, SF_WAVE, SF_TURRET, SF_BOSS, SF_DIVER, SF_METEOR };
enum { SF_FORM_LINE, SF_FORM_V, SF_FORM_WAVE, SF_FORM_ARC, SF_FORM_PINCER, SF_FORM_REAR, SF_FORM_CARRIER };
enum { SF_SOUND_SHOT=1, SF_SOUND_KILL=2, SF_SOUND_POWER=3, SF_SOUND_WARN=4, SF_SOUND_HIT=5 };
typedef struct { int32_t x, y; bool active; } SfShot;
typedef struct { int32_t x,y; int16_t vx,vy; bool active; } SfHostile;
typedef struct {
    int32_t x,y; int16_t origin_y; uint16_t age,hp;
    uint8_t type,phase; bool active,carrier;
} SfEnemy;
typedef struct { int16_t x,y; uint8_t ttl; } SfEffect;
typedef struct { int32_t x,y;uint8_t hit_mask,age,length;bool active; } SfBeam;
typedef struct {
    int32_t x,y;uint16_t hp,max_hp,age,death_age;uint8_t parts[2],phase,slot;bool active,dying;
} SfBoss;
typedef struct {
    int32_t x, y; /* Q8 coordinates; top left */
    uint32_t tick, seed;
    uint16_t height, scroll;
    uint8_t cooldown;
    SfShot shots[SF_SHOTS];
    int16_t shot_vy[SF_SHOTS];
    SfShot missile;
    SfBeam beam;
    SfEnemy enemies[SF_ENEMIES];
    SfHostile hostile[SF_HOSTILES];
    SfEffect effects[SF_EFFECTS];
    int32_t history_x[32],history_y[32];
    int32_t pickup_x,pickup_y;
    uint32_t stage_tick,score;
    uint16_t invincible,state_age;
    uint8_t state,lives,power,options,history_pos,event_index,sound;
    bool pickup_active,boss_dead,fire_was_down;
    uint8_t gauge,weapon,shield,missile_cooldown,emitter,capsule_queue;
    bool missile_enabled,equip_was_down;
    uint8_t enemy_group[SF_ENEMIES],group_remaining[16],wave_spawned;
    uint16_t group_failed;
    uint16_t enemy_serial[SF_ENEMIES],beam_hit_serial[SF_ENEMIES];
    int16_t missile_vy;
    bool missile_grounded;
    uint32_t boss_defeat_tick;
    SfBeam option_beams[2];
    uint16_t option_hit_serial[2][SF_ENEMIES];
    uint8_t enemy_flash[SF_ENEMIES],muzzle_mask,muzzle_timer;
    uint32_t stage_frame,demo_frame;
    uint16_t idle_ticks;
    uint8_t stage_index;
    bool attract,start_was_down;
    SfBoss boss;
} SfGame;
typedef struct { uint8_t oam[SF_SPRITES*8]; unsigned peak_line,dropped_effects; } SfFrame;
void sf_init(SfGame *g, unsigned height, uint32_t seed);
void sf_step(SfGame *g, unsigned input);
void sf_player_step(SfGame *g, unsigned input);
void sf_bullet_step(SfGame *g, unsigned input);
bool sf_render(const SfGame *g, SfFrame *frame);
void sf_start(SfGame *g);
void sf_enemy_step(SfGame *g);
void sf_stage_step(SfGame *g);
void sf_stage_reset(SfGame *g);
void sf_stage_defeat(SfGame *g,unsigned slot);
void sf_stage_lost(SfGame *g,unsigned slot);
void sf_collision_step(SfGame *g);
void sf_powerup_step(SfGame *g);
bool sf_equip(SfGame *g);
void sf_drop_capsule(SfGame *g,int32_t x,int32_t y);
const char *sf_gauge_name(unsigned gauge);
void sf_terrain(unsigned col,unsigned height,int *top,int *bottom);
bool sf_terrain_hit(const SfGame *g,int x,int y,int w,int h);
void sf_explode(SfGame *g,int x,int y);
void sf_hit_player(SfGame *g);
void sf_sound(SfGame *g,unsigned sound);
void sf_make_patterns(uint8_t *patterns);
void sf_make_map(uint8_t *map,unsigned height);
void sf_make_map_at(uint8_t *map,unsigned height,uint32_t world_tile);
void sf_make_column(uint8_t *column,unsigned height,uint32_t world_col);
bool sf_stage_base_visible(const SfGame *g);
void sf_make_palette(uint8_t *palette);
void sf_option_position(const SfGame *g,unsigned option,int32_t *x,int32_t *y);
void sf_laser_fit(SfGame *g);
bool sf_enemy_flying(unsigned type);
const SfStageDef *sf_stage_def(unsigned index);
unsigned sf_scene(const SfGame *g);
void sf_begin_play(SfGame *g);
void sf_to_title(SfGame *g);
void sf_clear_combat(SfGame *g);
void sf_start_demo(SfGame *g);
unsigned sf_demo_input(const SfGame *g);
void sf_demo_events(SfGame *g);
void sf_make_title_map(uint8_t *map,unsigned height);
void sf_title_palette(const SfGame *g,uint8_t *palette);
void sf_boss_begin(SfGame *g,unsigned slot);
void sf_boss_step(SfGame *g);
bool sf_boss_hit(SfGame *g,int x,int y,int w,int h,unsigned damage);
void sf_boss_death_step(SfGame *g);
void sf_enemy_fire(SfGame *g,int32_t x,int32_t y);
#endif
