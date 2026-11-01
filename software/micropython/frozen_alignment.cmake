# SPDX-License-Identifier: Apache-2.0
# Run after upstream generation, before compilation. No upstream source patch.
set(KAGURA_FROZEN_ALIGNMENT_SCRIPT "${CMAKE_CURRENT_LIST_DIR}/align_frozen.py")
function(kagura_align_frozen)
    add_custom_command(TARGET BUILD_FROZEN_CONTENT POST_BUILD
        COMMAND ${Python3_EXECUTABLE} ${KAGURA_FROZEN_ALIGNMENT_SCRIPT}
            ${MICROPY_FROZEN_CONTENT}
        VERBATIM)
endfunction()
cmake_language(DEFER CALL kagura_align_frozen)
