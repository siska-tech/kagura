# SPDX-License-Identifier: Apache-2.0
# KAGURA native desktop library, host build and tests (GCC or Clang):
#   cmake -S software/desktop -B build/desktop -DCMAKE_BUILD_TYPE=Release
#   cmake --build build/desktop && ctest --test-dir build/desktop
# The MicroPython module is built by the port (binding/micropython.cmake
# for rp2, binding/micropython.mk for unix); tools/test.sh runs both.
cmake_minimum_required(VERSION 3.13)
project(kagura_desktop C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
add_compile_options(-Wall -Wextra -Werror)
set(FONT ${CMAKE_CURRENT_SOURCE_DIR}/../micropython/fonts/misaki8.kfnt)

# Native text: UTF-8 decoding, KJ8F lookup and the Misaki font in rodata.
add_library(kj_text STATIC text/kj_text.c text/kj_misaki8.c)
target_include_directories(kj_text PUBLIC text)
target_compile_definitions(kj_text PRIVATE KJ_MISAKI8_PATH="${FONT}")
set_source_files_properties(text/kj_misaki8.c PROPERTIES OBJECT_DEPENDS ${FONT})

set(CORE_SOURCES core/kd_fb.c core/kd_region.c core/kd_tile4.c core/kd_font.c core/kd_font_data.c
    core/kd_sprite.c core/kd_gfx.c core/kd_app.c core/kd_desktop.c)
add_library(kd_core STATIC ${CORE_SOURCES})
target_include_directories(kd_core PUBLIC core)
target_compile_definitions(kd_core PUBLIC KD_UTF8=1)
target_link_libraries(kd_core PUBLIC kj_text)

# Bounded UTF-8 editing core: no fonts, no desktop, no MicroPython.
add_library(kd_edit STATIC text/kd_edit.c)
target_include_directories(kd_edit PUBLIC text)
target_link_libraries(kd_edit PUBLIC kj_text)

enable_testing()
add_executable(kj_tests tests/test_text.c)
target_link_libraries(kj_tests kj_text)
add_test(NAME text COMMAND kj_tests)
find_package(Python3 COMPONENTS Interpreter)
if(Python3_FOUND)
    add_executable(kj_oracle tests/oracle.c)
    target_link_libraries(kj_oracle kj_text)
    add_test(NAME text_oracle COMMAND ${Python3_EXECUTABLE} -I ${CMAKE_CURRENT_SOURCE_DIR}/tests/oracle.py
             $<TARGET_FILE:kj_oracle>)
endif()

# The retained layer and its mutants (each must fail the tests).
foreach(fault 0 1 2 3 4 5 6 7 8 9 10 11 12)
    if(fault EQUAL 0)
        set(suffix "")
    else()
        set(suffix _fault${fault})
    endif()
    add_library(kdm${suffix} STATIC retained/kdm.c)
    target_include_directories(kdm${suffix} PUBLIC retained)
    target_link_libraries(kdm${suffix} PUBLIC kd_core kd_edit)
    target_compile_definitions(kdm${suffix} PRIVATE KDM_FAULT=${fault})
    add_executable(kdm_tests${suffix} tests/test_kdm.c)
    target_link_libraries(kdm_tests${suffix} kdm${suffix})
    if(fault EQUAL 0)
        add_test(NAME kdm COMMAND kdm_tests)
    else()
        add_test(NAME kdm_mutant_${fault} COMMAND kdm_tests${suffix})
        set_tests_properties(kdm_mutant_${fault} PROPERTIES WILL_FAIL TRUE)
    endif()
endforeach()

# The editing core and its mutants (each must fail the tests), and a
# flat-buffer versus gap-buffer benchmark (run by hand, not a test).
foreach(fault 0 1 2 3 4)
    if(fault EQUAL 0)
        add_executable(kd_edit_tests tests/test_edit.c)
        target_link_libraries(kd_edit_tests kd_edit)
        add_test(NAME edit COMMAND kd_edit_tests)
    else()
        add_library(kd_edit_fault${fault} STATIC text/kd_edit.c)
        target_include_directories(kd_edit_fault${fault} PUBLIC text)
        target_link_libraries(kd_edit_fault${fault} PUBLIC kj_text)
        target_compile_definitions(kd_edit_fault${fault} PRIVATE KD_EDIT_FAULT=${fault})
        add_executable(kd_edit_tests_fault${fault} tests/test_edit.c)
        target_link_libraries(kd_edit_tests_fault${fault} kd_edit_fault${fault})
        add_test(NAME edit_mutant_${fault} COMMAND kd_edit_tests_fault${fault})
        set_tests_properties(edit_mutant_${fault} PROPERTIES WILL_FAIL TRUE)
    endif()
endforeach()
add_executable(kd_edit_bench tests/bench_edit.c)
target_link_libraries(kd_edit_bench kd_edit)
add_executable(kd_compose_bench tests/bench_compose.c)
target_link_libraries(kd_compose_bench kdm)
