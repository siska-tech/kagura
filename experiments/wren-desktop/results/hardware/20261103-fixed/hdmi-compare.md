# HDMI capture vs PC reference

Sampling phase: dx -1, dy +0 capture pixels from the block centre.

| index | expected RGB | observed (median) | scenes |
|---:|---|---|---:|
| 0 | (0, 170, 85) | (0, 203, 81) | 6 |
| 1 | (0, 0, 0) | (0, 0, 0) | 0 |
| 2 | (255, 255, 255) | (255, 255, 255) | 6 |
| 3 | (187, 187, 187) | (187, 187, 187) | 0 |
| 4 | (102, 102, 102) | (102, 102, 102) | 0 |
| 5 | (34, 51, 204) | (34, 51, 204) | 0 |
| 6 | (221, 34, 34) | (221, 34, 34) | 0 |
| 7 | (238, 204, 34) | (238, 204, 34) | 0 |
| 8 | (0, 102, 51) | (0, 102, 51) | 0 |
| 9 | (34, 187, 204) | (34, 187, 204) | 0 |
| 10 | (204, 68, 204) | (204, 68, 204) | 0 |
| 11 | (136, 68, 34) | (136, 68, 34) | 0 |
| 12 | (136, 170, 255) | (136, 170, 255) | 0 |
| 13 | (136, 238, 136) | (136, 238, 136) | 0 |
| 14 | (255, 136, 34) | (255, 136, 34) | 0 |
| 15 | (255, 255, 204) | (255, 255, 204) | 0 |

A mismatch is "chroma" when explained by 4:2:2 colour blur (on a horizontal colour edge of the reference, luma correct); every other mismatch is "unexplained".

| scene | colour mismatches | of 76,800 | chroma | unexplained | unexplained tiles |
|---|---:|---:|---:|---:|---|
| frame-1 | 333 | 0.4336% | 333 | 0 |  |
| frame-2 | 333 | 0.4336% | 333 | 0 |  |
| frame-3 | 379 | 0.4935% | 379 | 0 |  |
| frame-4 | 333 | 0.4336% | 333 | 0 |  |
| frame-5 | 379 | 0.4935% | 333 | 46 | 203, 209, 243, 249, 283, 289, 323, 329 |
| frame-6 | 229 | 0.2982% | 229 | 0 |  |

Total colour mismatches: 1986, of which unexplained: 46
