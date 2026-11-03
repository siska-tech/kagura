# SPDX-License-Identifier: Apache-2.0
# kagura_desktop user C module for CMake ports (rp2). The KAGURA_PICO board
# adds it by default (boards/KAGURA_PICO/mpconfigboard.cmake); elsewhere:
#   make -C ports/rp2 USER_C_MODULES=<repo>/software/desktop/binding/micropython.cmake
add_library(usermod_kagura_desktop INTERFACE)

set(KD_ROOT ${CMAKE_CURRENT_LIST_DIR}/..)
target_sources(usermod_kagura_desktop INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/modkagura_desktop.c
    ${KD_ROOT}/retained/kdm.c
    ${KD_ROOT}/text/kj_text.c
    ${KD_ROOT}/text/kd_edit.c
    ${KD_ROOT}/text/kj_misaki8.c
    ${KD_ROOT}/core/kd_fb.c
    ${KD_ROOT}/core/kd_region.c
    ${KD_ROOT}/core/kd_tile4.c
    ${KD_ROOT}/core/kd_font.c
    ${KD_ROOT}/core/kd_font_data.c
    ${KD_ROOT}/core/kd_sprite.c
    ${KD_ROOT}/core/kd_gfx.c
    ${KD_ROOT}/core/kd_app.c
    ${KD_ROOT}/core/kd_desktop.c
)
target_include_directories(usermod_kagura_desktop INTERFACE ${KD_ROOT}/retained ${KD_ROOT}/core ${KD_ROOT}/text)
# UTF-8 text with the Misaki font embedded from the repository (text/kj_misaki8.c).
target_compile_definitions(usermod_kagura_desktop INTERFACE KD_UTF8=1
    KJ_MISAKI8_PATH="${KD_ROOT}/../micropython/fonts/misaki8.kfnt")
target_link_libraries(usermod INTERFACE usermod_kagura_desktop)
