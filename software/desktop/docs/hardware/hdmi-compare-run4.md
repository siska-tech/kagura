# HDMI capture vs PC reference

Sampling phase: dx -1, dy +0 capture pixels from the block centre.

| index | expected RGB | observed (median) | scenes |
|---:|---|---|---:|
| 0 | (0, 170, 85) | (0, 203, 81) | 11 |
| 1 | (0, 0, 0) | (0, 0, 0) | 11 |
| 2 | (255, 255, 255) | (255, 255, 255) | 11 |
| 3 | (187, 187, 187) | (197, 197, 197) | 4 |
| 4 | (102, 102, 102) | (98, 98, 98) | 4 |
| 5 | (34, 51, 204) | (22, 31, 203) | 10 |
| 6 | (221, 34, 34) | (211, 0, 20) | 4 |
| 7 | (238, 204, 34) | (247, 228, 32) | 4 |
| 8 | (0, 102, 51) | (0, 113, 40) | 4 |
| 9 | (34, 187, 204) | (35, 215, 211) | 4 |
| 10 | (204, 68, 204) | (198, 34, 207) | 4 |
| 11 | (136, 68, 34) | (127, 55, 23) | 4 |
| 12 | (136, 170, 255) | (143, 176, 255) | 11 |
| 13 | (136, 238, 136) | (148, 255, 143) | 4 |
| 14 | (255, 136, 34) | (255, 133, 28) | 4 |
| 15 | (255, 255, 204) | (255, 255, 219) | 4 |

A mismatch is "chroma" when explained by 4:2:2 colour blur (on a horizontal colour edge of the reference, luma correct); every other mismatch is "unexplained".

| scene | colour mismatches | of 76,800 | chroma | unexplained | unexplained tiles |
|---|---:|---:|---:|---:|---|
| 01-desktop | 86 | 0.1120% | 86 | 0 |  |
| 02-files | 82 | 0.1068% | 82 | 0 |  |
| 03-menu | 54 | 0.0703% | 54 | 0 |  |
| 04-about | 77 | 0.1003% | 77 | 0 |  |
| 05-ok-pressed | 81 | 0.1055% | 81 | 0 |  |
| 06-about-closed | 81 | 0.1055% | 81 | 0 |  |
| 07-studio | 378 | 0.4922% | 378 | 0 |  |
| 08-paint | 401 | 0.5221% | 401 | 0 |  |
| 09-import | 476 | 0.6198% | 476 | 0 |  |
| 10-move | 445 | 0.5794% | 445 | 0 |  |
| 11-closed | 81 | 0.1055% | 81 | 0 |  |

Total colour mismatches: 2242, of which unexplained: 0

Console after the run vs before: 10838 of 76,800 logical pixels differ (text threshold).

