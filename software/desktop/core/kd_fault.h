// SPDX-License-Identifier: Apache-2.0
// Deliberate fault injection for the mutation tests (tests/CMakeLists).
// A normal build has KD_FAULT 0 and every KD_FAULTY() is a constant false.
// Each mutant build defines one number; the test suite must then fail.
#ifndef KD_FAULT_H
#define KD_FAULT_H

#ifndef KD_FAULT
#define KD_FAULT 0
#endif
#define KD_FAULTY(n) (KD_FAULT == (n))

enum {
    KD_FAULT_NIBBLE_SWAP = 1,      // even x written to the low nibble
    KD_FAULT_SPAN_DIRTY = 2,       // span body changes bytes without marking tiles
    KD_FAULT_CLIP_RIGHT = 3,       // spans run one pixel past the clip edge
    KD_FAULT_TILE4_ROWS = 4,       // export writes tile rows bottom-up
    KD_FAULT_NO_SUBTRACT = 5,      // compose does not remove drawn layers
    KD_FAULT_MOVE_OLD = 6,         // move forgets to damage the old frame
    KD_FAULT_DAMAGE_DROP = 7,      // a full damage list drops the new rect
    KD_FAULT_RAISE_EXPOSE = 8,     // raising a window does not damage exposed parts
    KD_FAULT_FOCUS_BOTTOM = 9,     // keys go to the bottom window
    KD_FAULT_SPRITE_NIBBLE = 10,   // sprite set uses the wrong nibble
    KD_FAULT_FLUSH_CLEAN = 11,     // TILE4 flush clears dirty tiles even on sink failure
    KD_FAULT_CLOSE_EXPOSE = 12,    // closing a window does not damage its frame
    KD_FAULT_OCCLUDED_SKIP = 13,   // window invalidation also subtracts the window itself
};

#endif
