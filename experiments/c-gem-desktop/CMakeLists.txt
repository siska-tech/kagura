# SPDX-License-Identifier: Apache-2.0
# Experimental C GEM-style desktop for KAGURA-9 (see README.md).
cmake_minimum_required(VERSION 3.13)
project(kagura_c_gem_desktop C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# The core lives in the shared native library (software/desktop/core).
set(KD_CORE ${CMAKE_CURRENT_SOURCE_DIR}/../../software/desktop/core)

option(KD_SDL "Build the interactive SDL2 host" ON)
option(KD_MUTATION_TESTS "Build fault-injected test variants that must fail" ON)

if(MSVC)
    # C4127: KD_FAULTY() is a constant condition by design; C4996: strncpy.
    set(KD_WARNINGS /W4 /WX /wd4127 /wd4996)
else()
    set(KD_WARNINGS -Wall -Wextra -Werror -Wshadow -Wstrict-prototypes)
endif()

set(KD_CORE_SOURCES
    ${KD_CORE}/kd_fb.c ${KD_CORE}/kd_region.c ${KD_CORE}/kd_tile4.c ${KD_CORE}/kd_font.c
    ${KD_CORE}/kd_font_data.c ${KD_CORE}/kd_sprite.c ${KD_CORE}/kd_gfx.c ${KD_CORE}/kd_app.c
    ${KD_CORE}/kd_desktop.c)
set(KD_APP_SOURCES apps/shell.c apps/filemgr.c apps/studio.c)

# One core+apps library per fault number; 0 is the real build.
function(kd_variant fault suffix)
    add_library(kd_desktop_lib${suffix} STATIC ${KD_CORE_SOURCES} ${KD_APP_SOURCES})
    target_include_directories(kd_desktop_lib${suffix} PUBLIC ${KD_CORE} apps)
    target_compile_definitions(kd_desktop_lib${suffix} PUBLIC KD_FAULT=${fault})
    target_compile_options(kd_desktop_lib${suffix} PRIVATE ${KD_WARNINGS})
endfunction()
kd_variant(0 "")

# The existing C TileFramebuffer raster (software/pico/tile_fb.c, unchanged)
# serves as an independent reader of the exported TILE4 patterns.
set(KD_PICO ${CMAKE_CURRENT_SOURCE_DIR}/../../software/pico)
set(KD_TEST_SOURCES tests/test_main.c tests/test_raster.c tests/test_desktop.c)
if(EXISTS ${KD_PICO}/tile_fb.c)
    list(APPEND KD_TEST_SOURCES ${KD_PICO}/tile_fb.c)
    set(KD_TEST_DEFS KD_HAVE_TILE_FB=1)
    set(KD_TEST_INCLUDES ${KD_PICO} ${CMAKE_CURRENT_SOURCE_DIR}/../../software/include)
endif()

function(kd_tests suffix)
    add_executable(kd_tests${suffix} ${KD_TEST_SOURCES})
    target_link_libraries(kd_tests${suffix} kd_desktop_lib${suffix})
    target_include_directories(kd_tests${suffix} PRIVATE tests ${KD_TEST_INCLUDES})
    target_compile_definitions(kd_tests${suffix} PRIVATE ${KD_TEST_DEFS})
    target_compile_options(kd_tests${suffix} PRIVATE ${KD_WARNINGS})
endfunction()

enable_testing()
kd_tests("")
add_test(NAME kd_tests COMMAND kd_tests)

if(KD_MUTATION_TESTS)
    foreach(fault RANGE 1 13)
        kd_variant(${fault} "_fault${fault}")
        kd_tests("_fault${fault}")
        add_test(NAME mutant_${fault} COMMAND kd_tests_fault${fault} --quiet)
        set_tests_properties(mutant_${fault} PROPERTIES WILL_FAIL TRUE)
    endforeach()
endif()

add_executable(kd_headless host/headless.c host/image.c)
target_link_libraries(kd_headless kd_desktop_lib)
target_include_directories(kd_headless PRIVATE host)
target_compile_options(kd_headless PRIVATE ${KD_WARNINGS})
file(MAKE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/scenario)
add_test(NAME headless_scenario COMMAND kd_headless --scenario ${CMAKE_CURRENT_BINARY_DIR}/scenario)

add_executable(kd_hdmi_ref host/hdmi_ref.c host/image.c)
target_link_libraries(kd_hdmi_ref kd_desktop_lib)
target_include_directories(kd_hdmi_ref PRIVATE host bench)
target_compile_options(kd_hdmi_ref PRIVATE ${KD_WARNINGS})
file(MAKE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/hdmi-ref)
add_test(NAME hdmi_reference COMMAND kd_hdmi_ref ${CMAKE_CURRENT_BINARY_DIR}/hdmi-ref)

find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
    add_test(NAME sdk_reference
             COMMAND ${Python3_EXECUTABLE} -I ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_sdk_reference.py
                     $<TARGET_FILE:kd_headless>)
endif()

add_executable(kd_bench bench/bench.c)
target_link_libraries(kd_bench kd_desktop_lib)
target_compile_options(kd_bench PRIVATE ${KD_WARNINGS})

if(KD_SDL)
    find_package(SDL2 CONFIG QUIET)
    if(SDL2_FOUND)
        add_executable(kd_desktop host/sdl_main.c host/image.c)
        target_include_directories(kd_desktop PRIVATE host)
        target_link_libraries(kd_desktop kd_desktop_lib)
        if(TARGET SDL2::SDL2main)
            target_link_libraries(kd_desktop SDL2::SDL2main)
        endif()
        if(TARGET SDL2::SDL2)
            target_link_libraries(kd_desktop SDL2::SDL2)
        else()
            target_link_libraries(kd_desktop ${SDL2_LIBRARIES})
            target_include_directories(kd_desktop PRIVATE ${SDL2_INCLUDE_DIRS})
        endif()
        target_compile_options(kd_desktop PRIVATE ${KD_WARNINGS})
        if(WIN32 AND TARGET SDL2::SDL2)
            add_custom_command(TARGET kd_desktop POST_BUILD COMMAND ${CMAKE_COMMAND} -E copy_if_different
                               $<TARGET_FILE:SDL2::SDL2> $<TARGET_FILE_DIR:kd_desktop>)
        endif()
        add_test(NAME sdl_smoke COMMAND kd_desktop --smoke ${CMAKE_CURRENT_BINARY_DIR}/sdl-smoke.png)
        if(NOT WIN32)   # the Windows SDL2 build has no offscreen driver: a window opens briefly
            set_tests_properties(sdl_smoke PROPERTIES ENVIRONMENT "SDL_VIDEODRIVER=offscreen")
        endif()
    else()
        message(STATUS "SDL2 not found: kd_desktop (interactive host) is skipped")
    endif()
endif()
