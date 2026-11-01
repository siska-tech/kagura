# KAGURA-9 showcase: publication copy

UGREENによる[実機収録の条件・結果](measurements/kagura-showcase-capture-2026-11-01.md)。
以下はYouTube投稿用の英文案。動画ファイルはローカルに保存しており、投稿URLは未登録。

## Title

KAGURA-9: Graphics & Sound on a Tiny FPGA | MicroPython HDMI Showcase

## Description

A tiny FPGA. A world of graphics and sound.

KAGURA-9 is an HDMI graphics and sound chip implemented on a Tang Nano 9K FPGA board.
Controlled by MicroPython running on a Raspberry Pi Pico, it generates video and stereo audio in real time.

This showcase brings together introduction slides, animated graphics, a scrolling shooter,
and a cherry blossom finale. The footage was captured directly from the hardware's HDMI
output using a UGREEN capture device. The on-screen introduction slides are in Japanese.

In this video:

- Japanese introduction slides using tile-based pseudo-256-color graphics
- Plasma, tunnel, 4D tesseract, and neon ribbon demos
- PROJECT STARFALL, ported back to MicroPython from its C implementation
- A cherry blossom scene combining 256 petal sprites, raster scrolling, an animated aurora, and PCM piano playback

Hardware and setup:

- Tang Nano 9K
- Raspberry Pi Pico running MicroPython
- 480p HDMI output with stereo audio
- UGREEN 15390 HDMI capture device

Technical notes:

Pseudo-256-color graphics use 16 colors per 8x8 tile and 16 palettes across the screen.
Color zero is shared. The sprite system supports 256 registered sprites, with a limit of 16 per scanline.
The video is recorded at 59.94 fps. Each demo's actual rendering update rate varies with its workload.
STARFALL currently implements Stage 1; this is not a completed six-stage game.

Source code, specifications, and SDK:
https://github.com/siska-tech/kagura

#FPGA #MicroPython #TangNano9K #RaspberryPiPico #KAGURA9
