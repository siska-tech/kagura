set(DESKTOP ${CMAKE_CURRENT_LIST_DIR}/../c-gem-desktop)
set(WREN_EXPERIMENT ${CMAKE_CURRENT_LIST_DIR}/../wren-rp2040)
include(${WREN_EXPERIMENT}/wren.cmake)
add_library(integration STATIC ${CMAKE_CURRENT_LIST_DIR}/src/ui.c ${CMAKE_CURRENT_LIST_DIR}/src/transport.c ${CMAKE_CURRENT_LIST_DIR}/src/runtime.c
  ${DESKTOP}/src/kd_fb.c ${DESKTOP}/src/kd_region.c ${DESKTOP}/src/kd_tile4.c
  ${DESKTOP}/src/kd_font.c ${DESKTOP}/src/kd_font_data.c ${DESKTOP}/src/kd_sprite.c
  ${DESKTOP}/src/kd_gfx.c ${DESKTOP}/src/kd_app.c ${DESKTOP}/src/kd_desktop.c)
target_include_directories(integration PUBLIC ${CMAKE_CURRENT_LIST_DIR}/src
  ${DESKTOP}/src ${CMAKE_CURRENT_LIST_DIR}/../../software/pico
  ${CMAKE_CURRENT_LIST_DIR}/../../software/include)
target_link_libraries(integration PUBLIC wren_vm m)
target_compile_options(integration PRIVATE -Os -Wall -Wextra -Werror -ffunction-sections -fdata-sections -fstack-usage)
