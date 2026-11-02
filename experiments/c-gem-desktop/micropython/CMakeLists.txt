# SPDX-License-Identifier: Apache-2.0
# Native (no MicroPython) part of stage 3A: tests of the retained layer kdm,
# its mutants, the C reference of the demo and the pure-C benchmark. The
# MicroPython module itself is built by tools/build_unix.sh.
#   cmake -S experiments/c-gem-desktop/micropython -B build/c-gem-mp -DCMAKE_BUILD_TYPE=Release
#   cmake --build build/c-gem-mp && ctest --test-dir build/c-gem-mp
cmake_minimum_required(VERSION 3.13)
project(kagura_desktop_binding C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CORE ${CMAKE_CURRENT_SOURCE_DIR}/../src)
set(KDM ${CMAKE_CURRENT_SOURCE_DIR}/kagura_desktop)
add_compile_options(-Wall -Wextra -Werror)

add_library(kd_core STATIC
    ${CORE}/kd_fb.c ${CORE}/kd_region.c ${CORE}/kd_tile4.c ${CORE}/kd_font.c ${CORE}/kd_font_data.c
    ${CORE}/kd_sprite.c ${CORE}/kd_gfx.c ${CORE}/kd_app.c ${CORE}/kd_desktop.c)
target_include_directories(kd_core PUBLIC ${CORE})

enable_testing()

foreach(fault 0 1 2 3 4 5 6 7)
    if(fault EQUAL 0)
        set(suffix "")
    else()
        set(suffix _fault${fault})
    endif()
    add_library(kdm${suffix} STATIC ${KDM}/kdm.c)
    target_include_directories(kdm${suffix} PUBLIC ${KDM})
    target_link_libraries(kdm${suffix} PUBLIC kd_core)
    target_compile_definitions(kdm${suffix} PRIVATE KDM_FAULT=${fault})
    add_executable(kdm_tests${suffix} tests/test_kdm.c)
    target_include_directories(kdm_tests${suffix} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../tests)
    target_link_libraries(kdm_tests${suffix} kdm${suffix})
    if(fault EQUAL 0)
        add_test(NAME kdm_tests COMMAND kdm_tests)
    else()
        add_test(NAME kdm_mutant_${fault} COMMAND kdm_tests${suffix})
        set_tests_properties(kdm_mutant_${fault} PROPERTIES WILL_FAIL TRUE)
    endif()
endforeach()

add_executable(kd_ref_demo tests/ref_demo.c)
target_link_libraries(kd_ref_demo kd_core)

add_executable(kdm_bench bench/bench_native.c)
target_link_libraries(kdm_bench kdm)
