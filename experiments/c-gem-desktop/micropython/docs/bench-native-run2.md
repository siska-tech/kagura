# kdm_bench: pure C through kdm (op + present into a TILE4 mirror), per iteration
| workload | mean us | p50 us | p90 us | max us | tiles | fb crc | vram crc |
|---|---:|---:|---:|---:|---:|---:|---:|
| idle | 0.57 | 0.59 | 0.59 | 0.60 | 0.0 | b9bf75cd | 2f32c79d |
| full_redraw | 84.40 | 80.15 | 85.97 | 136.87 | 0.0 | b9bf75cd | 2f32c79d |
| label_one_char | 1.56 | 1.56 | 1.59 | 9.27 | 2.0 | 2b8b766d | 05e94a4e |
| button_press | 2.44 | 2.44 | 2.50 | 12.03 | 15.0 | aad959dd | 10c72fe9 |
| panel_move_4px | 2.09 | 1.89 | 2.01 | 3.83 | 10.0 | 0a946139 | b8b3023b |
| window_rebuild | 11.02 | 10.86 | 11.24 | 34.75 | 2.0 | 2b8b766d | 05e94a4e |
| sprite_pixel | 2.16 | 2.17 | 2.20 | 13.70 | 7.0 | a33ba434 | 1a9dff6a |
| sprite_16px_calls | 9.28 | 9.10 | 9.29 | 9.53 | 27.4 | 0c756c58 | c3ec647f |
| sprite_16px_batched | 9.29 | 9.11 | 9.30 | 17.89 | 27.4 | 0c756c58 | c3ec647f |
| sprite_import | 42.00 | 41.20 | 41.59 | 59.80 | 147.0 | b9bf75cd | 2f32c79d |
| window_activate | 25.55 | 32.85 | 35.01 | 100.50 | 205.0 | 2fe15104 | f873fc4f |
| window_move_8px | 61.75 | 60.84 | 62.46 | 84.95 | 273.0 | cc30eda2 | 9d2251d7 |
| window_open_close | 41.99 | 41.70 | 42.82 | 80.47 | 194.0 | b9bf75cd | 2f32c79d |
| events_3 | 1.74 | 1.74 | 1.79 | 1.84 | 6.0 | 321f525a | ca539152 |
| rects_1_calls | 21.67 | 21.34 | 22.13 | 59.70 | 6.8 | e62fea0f | 1a0c87f7 |
| rects_16_calls | 32.13 | 31.86 | 46.58 | 200.02 | 164.8 | 4ba66c42 | 3f6660ef |
| rects_256_calls | 130.34 | 129.88 | 135.14 | 258.89 | 680.9 | 323aea33 | 48170570 |
| rects_16_batched | 31.18 | 31.22 | 32.16 | 259.24 | 164.8 | 4ba66c42 | 3f6660ef |
| rects_256_batched | 124.19 | 125.43 | 129.17 | 140.83 | 680.9 | 323aea33 | 48170570 |
# sizeof(kdm) 46552, kd_desktop 34416, records 5760, text 2048, sprites 1088, events 896
