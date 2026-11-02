# bench_binding: MicroPython 1.26.0, kagura_desktop (op + present into a TILE4 mirror), per iteration
| workload | mean us | p50 us | p90 us | max us | tiles | heap B/iter | fb crc | vram crc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| idle | 0.61 | 1 | 1 | 1 | 0.0 | 0 | b9bf75cd | 2f32c79d |
| full_redraw | 89.63 | 88 | 90 | 115 | 0.0 | 0 | b9bf75cd | 2f32c79d |
| label_one_char | 1.95 | 2 | 2 | 2 | 2.0 | 0 | 2b8b766d | 05e94a4e |
| button_press | 3.01 | 3 | 3 | 11 | 15.0 | 0 | aad959dd | 10c72fe9 |
| panel_move_4px | 2.35 | 2 | 3 | 30 | 10.0 | 0 | 0a946139 | b8b3023b |
| window_rebuild | 14.09 | 14 | 14 | 35 | 2.0 | 0 | 2b8b766d | 05e94a4e |
| sprite_pixel | 2.71 | 3 | 3 | 3 | 7.0 | 0 | a33ba434 | 1a9dff6a |
| sprite_16px_calls | 11.11 | 11 | 12 | 19 | 27.4 | 0 | 0c756c58 | c3ec647f |
| sprite_16px_batched | 10.03 | 10 | 10 | 50 | 27.4 | 0 | 0c756c58 | c3ec647f |
| sprite_import | 46.84 | 46 | 47 | 59 | 147.0 | 0 | b9bf75cd | 2f32c79d |
| window_activate | 29.32 | 38 | 41 | 49 | 205.0 | 0 | 2fe15104 | f873fc4f |
| window_move_8px | 72.81 | 71 | 75 | 92 | 273.0 | 0 | cc30eda2 | 9d2251d7 |
| window_open_close | 54.32 | 52 | 53 | 63 | 194.0 | 32 | b9bf75cd | 2f32c79d |
| events_3 | 4.11 | 4 | 5 | 11 | 6.0 | 288 | 321f525a | ca539152 |
| events_3_poll_into | 3.12 | 3 | 3 | 4 | 6.0 | 0 | 321f525a | ca539152 |
| rects_1_calls | 29.09 | 29 | 30 | 42 | 6.8 | 0 | e62fea0f | 1a0c87f7 |
| rects_16_calls | 47.48 | 45 | 47 | 260 | 164.8 | 0 | 4ba66c42 | 3f6660ef |
| rects_256_calls | 204.00 | 203 | 213 | 352 | 680.9 | 1 | 323aea33 | 48170570 |
| rects_16_batched | 42.18 | 42 | 43 | 83 | 164.8 | 0 | 4ba66c42 | 3f6660ef |
| rects_256_batched | 164.76 | 165 | 169 | 177 | 680.9 | 1 | 323aea33 | 48170570 |

| call (100,000 iterations, loop overhead subtracted) | ns |
|---|---:|
| empty loop iteration | 20 |
| Python function call, 2 args | 52 |
| w.is_open() (handle check only) | 15 |
| w.set_color(id, same colour) (5 checks, no change) | 56 |
| w.fill_rect(...) + w.remove(id) | 179 |
| d.present() with no damage | 575 |
| d.poll_into(lst), queue empty | 28 |

heap: scene objects (Desktop, 2 Windows, Sprite, mirror bytearray 32,000 B) 32416 B of 2072832 B
native static: desktop 34416, events 896, framebuffer 32000, items 5760, max_items 320, menus 912, sprites 1088, staging 1280, text 2048, total 46552
gc.collect(): 10 us with the scene; 13 us with an extra 38,400 B bytearray alive
