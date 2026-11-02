# Transitional source ownership: no renderer/runtime source is copied or rewritten.
get_filename_component(KD_REPO "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
option(KAGURA_DESKTOP_WITH_WREN "Build the bounded Wren adapter" ON)
set(KD_EXP "${KD_REPO}/experiments")
set(KD_CORE "${KD_EXP}/c-gem-desktop")
set(KD_TEXT "${KD_EXP}/native-text")
set(KD_WD "${KD_EXP}/wren-desktop")
set(KD_JP "${KD_EXP}/wren-japanese-desktop")
find_package(Python3 REQUIRED COMPONENTS Interpreter)

add_custom_command(OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/font_data.c
  COMMAND ${Python3_EXECUTABLE} -I ${KD_TEXT}/tools/gen_font_c.py ${CMAKE_CURRENT_BINARY_DIR}/font_data.c
  DEPENDS ${KD_TEXT}/tools/gen_font_c.py ${KD_REPO}/software/micropython/fonts/misaki8.kfnt)
add_library(desktop_text STATIC ${KD_TEXT}/src/kj_text.c ${CMAKE_CURRENT_BINARY_DIR}/font_data.c)
target_include_directories(desktop_text PUBLIC ${KD_TEXT}/include)
target_compile_options(desktop_text PRIVATE -Wall -Wextra -Werror -Wconversion -fstack-usage)
if(CMAKE_CROSSCOMPILING)
  target_compile_options(desktop_text PRIVATE -Os -ffunction-sections -fdata-sections)
endif()
add_library(Kagura::Text ALIAS desktop_text)

# Object modules allow both a runtime-free native library and an integrated
# archive, with the reference firmware's archive member order preserved.
function(desktop_module target)
  add_library(${target} OBJECT ${ARGN})
  target_include_directories(${target} PUBLIC ${KD_CORE}/src ${KD_TEXT}/include
    ${KD_WD}/src ${KD_JP}/src ${KD_REPO}/software/pico ${KD_REPO}/software/include)
  target_compile_definitions(${target} PRIVATE KD_NATIVE_TEXT=1 WD_JAPANESE=1)
  target_compile_options(${target} PRIVATE -Os -Wall -Wextra -Werror
    -ffunction-sections -fdata-sections -fstack-usage)
endfunction()
desktop_module(desktop_core
  ${KD_CORE}/src/kd_fb.c ${KD_CORE}/src/kd_region.c ${KD_CORE}/src/kd_tile4.c
  ${KD_CORE}/src/kd_font.c ${KD_CORE}/src/kd_font_data.c ${KD_CORE}/src/kd_sprite.c
  ${KD_CORE}/src/kd_gfx.c ${KD_CORE}/src/kd_app.c ${KD_CORE}/src/kd_desktop.c)
desktop_module(desktop_text_bridge ${KD_TEXT}/src/kj_desktop.c)
add_library(desktop_native STATIC $<TARGET_OBJECTS:desktop_core> $<TARGET_OBJECTS:desktop_text_bridge>)
target_include_directories(desktop_native PUBLIC ${KD_CORE}/src ${KD_TEXT}/include)
target_link_libraries(desktop_native PUBLIC desktop_text)
add_library(Kagura::Native ALIAS desktop_native)

# These native modules are also usable when no script runtime is configured.
desktop_module(desktop_application ${KD_WD}/src/ui.c)
desktop_module(desktop_transport ${KD_WD}/src/transport.c)
desktop_module(desktop_title_policy ${KD_JP}/src/wj_title.c)
add_library(desktop_application_host STATIC $<TARGET_OBJECTS:desktop_application>
  $<TARGET_OBJECTS:desktop_transport> $<TARGET_OBJECTS:desktop_title_policy>)
target_include_directories(desktop_application_host PUBLIC ${KD_WD}/src ${KD_JP}/src
  ${KD_REPO}/software/pico ${KD_REPO}/software/include)
target_compile_definitions(desktop_application_host INTERFACE WD_JAPANESE=1)
target_link_libraries(desktop_application_host PUBLIC desktop_native)
add_library(Kagura::Application ALIAS desktop_application_host)

if(KAGURA_DESKTOP_WITH_WREN)
  include(${KD_EXP}/wren-rp2040/wren.cmake)
  # Generated into the build tree: configuring never edits app source artifacts.
  execute_process(COMMAND ${Python3_EXECUTABLE} -I ${KD_JP}/tools/gen_app.py
    ${CMAKE_CURRENT_BINARY_DIR}/japanese_app_source.h RESULT_VARIABLE APP_STATUS)
  if(NOT APP_STATUS EQUAL 0)
    message(FATAL_ERROR "Application source generation failed")
  endif()
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    ${KD_JP}/src/app.wren ${KD_JP}/tools/gen_app.py)
  desktop_module(desktop_wren ${KD_WD}/src/runtime.c)
  target_include_directories(desktop_wren BEFORE PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
  target_link_libraries(desktop_wren PRIVATE wren_vm)
  desktop_module(desktop_metrics ${KD_WD}/src/diagnostics.c)
  add_library(desktop_integration STATIC
    $<TARGET_OBJECTS:desktop_application> $<TARGET_OBJECTS:desktop_transport>
    $<TARGET_OBJECTS:desktop_wren> $<TARGET_OBJECTS:desktop_metrics>
    $<TARGET_OBJECTS:desktop_core> $<TARGET_OBJECTS:desktop_title_policy>
    $<TARGET_OBJECTS:desktop_text_bridge>)
  target_include_directories(desktop_integration PUBLIC ${KD_WD}/src ${KD_CORE}/src
    ${KD_REPO}/software/pico ${KD_REPO}/software/include ${KD_JP}/src ${KD_TEXT}/include)
  target_compile_definitions(desktop_integration INTERFACE WD_JAPANESE=1)
  target_link_libraries(desktop_integration PUBLIC wren_vm m desktop_text)
  add_library(Kagura::WrenDesktop ALIAS desktop_integration)
endif()
