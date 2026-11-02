# bench_binding: MicroPython 1.26.0, kagura_desktop (op + present into a TILE4 mirror), per iteration
| workload | mean us | p50 us | p90 us | max us | tiles | heap B/iter | fb crc | vram crc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| idle | 0.76 | 1 | 1 | 1 | 0.0 | 0 | b9bf75cd | 2f32c79d |
| full_redraw | 93.93 | 91 | 96 | 128 | 0.0 | 0 | b9bf75cd | 2f32c79d |
| label_one_char | 2.01 | 2 | 2 | 13 | 2.0 | 0 | 2b8b766d | 05e94a4e |
| button_press | 3.21 | 3 | 4 | 12 | 15.0 | 0 | aad959dd | 10c72fe9 |
| panel_move_4px | 2.35 | 2 | 3 | 3 | 10.0 | 0 | 0a946139 | b8b3023b |
| window_rebuild | 14.71 | 14 | 15 | 23 | 2.0 | 0 | 2b8b766d | 05e94a4e |
| sprite_pixel | 3.13 | 3 | 3 | 10 | 7.0 | 0 | a33ba434 | 1a9dff6a |
| sprite_16px_calls | 11.22 | 11 | 12 | 20 | 27.4 | 0 | 0c756c58 | c3ec647f |
| sprite_16px_batched | 9.89 | 10 | 10 | 19 | 27.4 | 0 | 0c756c58 | c3ec647f |
| sprite_import | 49.79 | 47 | 50 | 57 | 147.0 | 0 | b9bf75cd | 2f32c79d |
| window_activate | 31.26 | 39 | 40 | 49 | 205.0 | 0 | 2fe15104 | f873fc4f |
| window_move_8px | 74.81 | 74 | 77 | 87 | 273.0 | 0 | cc30eda2 | 9d2251d7 |
| window_open_close | 51.23 | 51 | 53 | 83 | 194.0 | 32 | b9bf75cd | 2f32c79d |
| events_3 | 4.16 | 4 | 5 | 6 | 6.0 | 288 | 321f525a | ca539152 |
| events_3_poll_into | 3.04 | 3 | 3 | 12 | 6.0 | 0 | 321f525a | ca539152 |
| rects_1_calls | 29.75 | 29 | 30 | 38 | 6.8 | 0 | e62fea0f | 1a0c87f7 |
| rects_16_calls | 45.38 | 45 | 46 | 100 | 164.8 | 0 | 4ba66c42 | 3f6660ef |
| rects_256_calls | 203.86 | 204 | 213 | 319 | 680.9 | 1 | 323aea33 | 48170570 |
| rects_16_batched | 44.73 | 44 | 45 | 61 | 164.8 | 0 | 4ba66c42 | 3f6660ef |
| rects_256_batched | 185.26 | 174 | 183 | 305 | 680.9 | 1 | 323aea33 | 48170570 |

| call (100,000 iterations, loop overhead subtracted) | ns |
|---|---:|
| empty loop iteration | 21 |
| Python function call, 2 args | 50 |
| w.is_open() (handle check only) | 15 |
| w.set_color(id, same colour) (5 checks, no change) | 52 |
| w.fill_rect(...) + w.remove(id) | 176 |
| d.present() with no damage | 604 |
| d.poll_into(lst), queue empty | 33 |

heap: scene objects (Desktop, 2 Windows, Sprite, mirror bytearray 32,000 B) 32416 B of 2072832 B
native static: desktop 34416, events 896, framebuffer 32000, items 5760, max_items 320, menus 912, sprites 1088, staging 1280, text 2048, total 46552
gc.collect(): 12 us with the scene; 15 us with an extra 38,400 B bytearray alive
