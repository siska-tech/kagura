# HDMI capture vs PC reference

Sampling phase: dx -1, dy +0 capture pixels from the block centre.

| index | expected RGB | observed (median) | scenes |
|---:|---|---|---:|
| 0 | (0, 170, 85) | (0, 203, 81) | 13 |
| 1 | (0, 0, 0) | (0, 0, 0) | 13 |
| 2 | (255, 255, 255) | (255, 255, 255) | 13 |
| 3 | (187, 187, 187) | (197, 197, 197) | 10 |
| 4 | (102, 102, 102) | (98, 98, 98) | 10 |
| 5 | (34, 51, 204) | (22, 31, 203) | 10 |
| 6 | (221, 34, 34) | (211, 0, 20) | 10 |
| 7 | (238, 204, 34) | (247, 228, 32) | 10 |
| 8 | (0, 102, 51) | (0, 113, 40) | 10 |
| 9 | (34, 187, 204) | (35, 215, 211) | 9 |
| 10 | (204, 68, 204) | (198, 34, 207) | 9 |
| 11 | (136, 68, 34) | (127, 55, 23) | 10 |
| 12 | (136, 170, 255) | (143, 176, 255) | 10 |
| 13 | (136, 238, 136) | (148, 255, 143) | 10 |
| 14 | (255, 136, 34) | (255, 133, 28) | 10 |
| 15 | (255, 255, 204) | (255, 255, 219) | 10 |

A mismatch is "chroma" when explained by 4:2:2 colour blur (on a horizontal colour edge of the reference, luma correct); every other mismatch is "unexplained".

| scene | colour mismatches | of 76,800 | chroma | unexplained | unexplained tiles |
|---|---:|---:|---:|---:|---|
| 01-desktop | 59 | 0.0768% | 59 | 0 |  |
| 02-files-open | 53 | 0.0690% | 53 | 0 |  |
| 03-files-closed | 63 | 0.0820% | 63 | 0 |  |
| 04-overlap | 355 | 0.4622% | 355 | 0 |  |
| 05-activate | 186 | 0.2422% | 186 | 0 |  |
| 06-menu | 171 | 0.2227% | 171 | 0 |  |
| 07-menu-closed | 186 | 0.2422% | 186 | 0 |  |
| 08-about | 164 | 0.2135% | 164 | 0 |  |
| 09-about-closed | 186 | 0.2422% | 186 | 0 |  |
| 10-move-live | 350 | 0.4557% | 350 | 0 |  |
| 11-outline-drag | 369 | 0.4805% | 369 | 0 |  |
| 12-outline-drop | 377 | 0.4909% | 377 | 0 |  |
| 13-sprite-draw | 266 | 0.3464% | 266 | 0 |  |

Total colour mismatches: 2785, of which unexplained: 0

## Recorded transitions

Capture-to-capture: the settled frames before the transition (median of the first 10) and after it (median of the last 10) are the "old" and "new" images, so static capture artefacts cancel. A pixel is old or new when within 40 RGB units of that image, or a blend (on the line between its old and new colour). Frames with both old and new pixels are the expected non-atomic intermediates: runs land while the frame is scanned out, byte by byte, so an 8x1 tile-row segment can be partly written ("partial segments"). A remaining pixel at the edge of a segment whose neighbouring segment is in a different update state is a "torn-row boundary" (the capture filter mixes the new colour on one side with the old on the other). Any other pixel is corrupt. The settled endpoints are also checked against the PC references (after the recording path alignment, found by search, and with colours learned from the recording).

| scene | frames | old | new | mixed (non-atomic) | partial segments | torn-row boundary px | corrupt px | settled new vs PC: unexplained px |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 05-activate | 241 | 52 | 188 | 1 | 10 | 1 | 0 | 2 (alignment dx +1 dy +0) |
| 07-menu-closed | 241 | 54 | 187 | 0 | 0 | 0 | 0 | 2 (alignment dx +1 dy +0) |
| 12-outline-drop | 241 | 56 | 184 | 1 | 10 | 3 | 0 | 2 (alignment dx +1 dy +0) |

Console after the run vs before: 0 of 76,800 logical pixels differ (text threshold).

