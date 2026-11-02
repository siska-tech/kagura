| workload | C through kdm, mean us | MicroPython + binding, mean us | difference us | ratio |
|---|---:|---:|---:|---:|
| idle | 0.46 | 0.56 | 0.10 | 1.22 |
| full_redraw | 66.97 | 83.39 | 16.42 | 1.25 |
| label_one_char | 1.33 | 1.80 | 0.47 | 1.35 |
| button_press | 2.13 | 2.85 | 0.72 | 1.34 |
| panel_move_4px | 1.66 | 2.23 | 0.57 | 1.34 |
| window_rebuild | 9.37 | 13.48 | 4.11 | 1.44 |
| sprite_pixel | 1.83 | 2.60 | 0.77 | 1.42 |
| sprite_16px_calls | 7.68 | 10.43 | 2.75 | 1.36 |
| sprite_16px_batched | 7.63 | 9.37 | 1.74 | 1.23 |
| sprite_import | 35.07 | 45.15 | 10.08 | 1.29 |
| window_activate | 21.54 | 28.57 | 7.03 | 1.33 |
| window_move_8px | 51.87 | 69.16 | 17.29 | 1.33 |
| window_open_close | 34.57 | 54.32 | 19.75 | 1.57 |
| events_3 | 1.47 | 4.01 | 2.54 | 2.73 |
| events_3_poll_into | 1.47 | 3.12 | 1.65 | 2.12 |
| rects_1_calls | 19.13 | 29.09 | 9.96 | 1.52 |
| rects_16_calls | 29.77 | 44.99 | 15.22 | 1.51 |
| rects_256_calls | 110.76 | 203.34 | 92.58 | 1.84 |
| rects_16_batched | 27.54 | 42.18 | 14.64 | 1.53 |
| rects_256_batched | 109.23 | 164.76 | 55.53 | 1.51 |

KAGURA-UI framebuf p50 us (median of runs): full_redraw 80, button_press 77, label_one_char 28, panel_move_4px 21, sprite_full_redraw 16752, sprite_pixel 42, sprite_import 579
