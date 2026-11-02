# SPDX-License-Identifier: Apache-2.0
# kagura_desktop user C module (CMake ports, e.g. rp2):
#   make -C ports/rp2 USER_C_MODULES=<repo>/experiments/c-gem-desktop/micropython/micropython.cmake
add_library(usermod_kagura_desktop INTERFACE)

set(KD_CORE_DIR ${CMAKE_CURRENT_LIST_DIR}/../../src)
target_sources(usermod_kagura_desktop INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/modkagura_desktop.c
    ${CMAKE_CURRENT_LIST_DIR}/kdm.c
    ${KD_CORE_DIR}/kd_fb.c
    ${KD_CORE_DIR}/kd_region.c
    ${KD_CORE_DIR}/kd_tile4.c
    ${KD_CORE_DIR}/kd_font.c
    ${KD_CORE_DIR}/kd_font_data.c
    ${KD_CORE_DIR}/kd_sprite.c
    ${KD_CORE_DIR}/kd_gfx.c
    ${KD_CORE_DIR}/kd_app.c
    ${KD_CORE_DIR}/kd_desktop.c
)
target_include_directories(usermod_kagura_desktop INTERFACE ${CMAKE_CURRENT_LIST_DIR} ${KD_CORE_DIR})
target_link_libraries(usermod INTERFACE usermod_kagura_desktop)
