# SPDX-License-Identifier: Apache-2.0
# Stage 3A evaluation programs on top of the native desktop library
# (software/desktop, which also builds the kdm and text tests):
#   kd_ref_demo  the demo scenario written with kd_app.h only
#   kdm_bench    the benchmark workloads in pure C through kdm
#   cmake -S experiments/c-gem-desktop/micropython -B build/c-gem-mp -DCMAKE_BUILD_TYPE=Release
#   cmake --build build/c-gem-mp && ctest --test-dir build/c-gem-mp
cmake_minimum_required(VERSION 3.13)
project(kagura_desktop_stage3a C)

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../../software/desktop desktop)

add_executable(kd_ref_demo tests/ref_demo.c)
target_link_libraries(kd_ref_demo kd_core)

add_executable(kdm_bench bench/bench_native.c)
target_link_libraries(kdm_bench kdm)
