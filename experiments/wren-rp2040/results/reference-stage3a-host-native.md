# kdm_bench: pure C through kdm (op + present into a TILE4 mirror), per iteration
| workload | mean us | p50 us | p90 us | max us | tiles | fb crc | vram crc |
|---|---:|---:|---:|---:|---:|---:|---:|
| idle | 0.64 | 0.66 | 0.66 | 0.69 | 0.0 | b9bf75cd | 2f32c79d |
| full_redraw | 88.64 | 86.50 | 91.06 | 110.01 | 0.0 | b9bf75cd | 2f32c79d |
| label_one_char | 1.75 | 1.70 | 1.72 | 1.82 | 2.0 | 2b8b766d | 05e94a4e |
| button_press | 2.67 | 2.63 | 2.68 | 2.80 | 15.0 | aad959dd | 10c72fe9 |
| panel_move_4px | 2.16 | 2.07 | 2.11 | 2.27 | 10.0 | 0a946139 | b8b3023b |
| window_rebuild | 11.80 | 11.41 | 11.62 | 30.41 | 2.0 | 2b8b766d | 05e94a4e |
| sprite_pixel | 2.36 | 2.31 | 2.37 | 2.61 | 7.0 | a33ba434 | 1a9dff6a |
| sprite_16px_calls | 10.80 | 9.60 | 9.80 | 21.84 | 27.4 | 0c756c58 | c3ec647f |
| sprite_16px_batched | 9.78 | 9.70 | 9.93 | 43.80 | 27.4 | 0c756c58 | c3ec647f |
| sprite_import | 45.02 | 79.24 | 83.68 | 243.53 | 147.0 | b9bf75cd | 2f32c79d |
| window_activate | 27.60 | 34.48 | 36.39 | 44.97 | 205.0 | 2fe15104 | f873fc4f |
| window_move_8px | 65.51 | 63.31 | 66.90 | 167.72 | 273.0 | cc30eda2 | 9d2251d7 |
| window_open_close | 44.46 | 43.91 | 44.71 | 56.80 | 194.0 | b9bf75cd | 2f32c79d |
| events_3 | 1.84 | 1.85 | 2.40 | 75.46 | 6.0 | 321f525a | ca539152 |
| rects_1_calls | 24.09 | 23.01 | 23.59 | 38.50 | 6.8 | e62fea0f | 1a0c87f7 |
| rects_16_calls | 33.98 | 33.55 | 34.90 | 183.34 | 164.8 | 4ba66c42 | 3f6660ef |
| rects_256_calls | 136.17 | 135.57 | 138.58 | 177.90 | 680.9 | 323aea33 | 48170570 |
| rects_16_batched | 33.70 | 33.51 | 34.23 | 145.51 | 164.8 | 4ba66c42 | 3f6660ef |
| rects_256_batched | 135.40 | 135.52 | 138.43 | 151.74 | 680.9 | 323aea33 | 48170570 |
# sizeof(kdm) 46552, kd_desktop 34416, records 5760, text 2048, sprites 1088, events 896
