# SPDX-License-Identifier: Apache-2.0
# kagura_audio user C module for CMake ports (rp2). The KAGURA boards add it
# with the desktop (boards/KAGURA_PICO/mpconfigboard.cmake).
add_library(usermod_kagura_audio INTERFACE)

set(KA_ROOT ${CMAKE_CURRENT_LIST_DIR}/..)
target_sources(usermod_kagura_audio INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/modkagura_audio.c
    ${KA_ROOT}/hal/ka_audio.c
    ${KA_ROOT}/hal/ka_render.c
    ${KA_ROOT}/seq/ks_song.c
    ${KA_ROOT}/seq/ks_player.c
)
target_include_directories(usermod_kagura_audio INTERFACE ${KA_ROOT}/hal ${KA_ROOT}/seq)
target_link_libraries(usermod INTERFACE usermod_kagura_audio)
