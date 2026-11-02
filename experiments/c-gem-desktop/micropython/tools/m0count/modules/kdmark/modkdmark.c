// SPDX-License-Identifier: Apache-2.0
// kdmark.begin()/end(): call the marker functions that tools/m0count/count.sh
// brackets its instruction counts with (count build only).
#include "py/runtime.h"

void kd_mark_begin(void);
void kd_mark_end(void);

static mp_obj_t kdmark_begin(void) {
    kd_mark_begin();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(kdmark_begin_obj, kdmark_begin);

static mp_obj_t kdmark_end(void) {
    kd_mark_end();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(kdmark_end_obj, kdmark_end);

static const mp_rom_map_elem_t kdmark_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_kdmark)},
    {MP_ROM_QSTR(MP_QSTR_begin), MP_ROM_PTR(&kdmark_begin_obj)},
    {MP_ROM_QSTR(MP_QSTR_end), MP_ROM_PTR(&kdmark_end_obj)},
};
static MP_DEFINE_CONST_DICT(kdmark_globals, kdmark_globals_table);

const mp_obj_module_t kdmark_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&kdmark_globals,
};

MP_REGISTER_MODULE(MP_QSTR_kdmark, kdmark_module);
