#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Cycle model of the KAGURA host PIO programs, read from the pioasm header
(build/pico/kagura_host.pio.h), against a behavioural FPGA adapter whose
outputs change 37..56 ns after each SCK rise plus output and board delay
(docs/host-interface.md). Checks SCK high/low time, MOSI setup, read data
over many output-delay draws, BUSY gating, and that the QSPI host releases
IO before the FPGA drives it. Not a model of the RP2040 beyond the opcodes
these programs use. Usage: test_pio_timing.py <kagura_host.pio.h>"""
import random, re, sys

T = 1e3 / 120.0          # ns per PIO cycle at 120 MHz, clkdiv 1
SYNC = 2                 # input synchronizer cycles
BOARD = 3.0              # ns each way

def load(header, name):
    text = open(header).read()
    body = re.search(name + r"_program_instructions\[\] = \{(.*?)\};", text, re.S).group(1)
    ins = [int(h, 16) for h in re.findall(r"0x([0-9a-f]{4}),", body)]
    wrap_t = int(re.search(name + r"_wrap_target (\d+)", text).group(1))
    wrap = int(re.search(name + r"_wrap (\d+)", text).group(1))
    return ins, wrap_t, wrap

class SM:
    def __init__(self, ins, wrap_t, wrap, out_base, out_count, in_base, busy_index, busy_pin):
        self.ins = list(ins); self.ins[busy_index] = 0x2000 | busy_pin   # wait 0 gpio busy
        self.wrap_t, self.wrap = wrap_t, wrap
        self.pc = wrap_t; self.x = self.y = 0; self.osr = 0; self.isr = 0; self.isr_n = 0
        self.delay = 0; self.tx = []; self.rx = []
        self.out_base, self.out_count, self.in_base = out_base, out_count, in_base
        self.sck = 0; self.out = {}; self.dirs = {}
    def step(self, cyc, pin_hist, gpio):
        if self.delay: self.delay -= 1; return
        i = self.ins[self.pc]; op = i >> 13; self.sck = (i >> 12) & 1; d = (i >> 8) & 0xF
        stall = False; nxt = self.pc + 1 if self.pc != self.wrap else self.wrap_t
        if op == 4 and i & 0x80:                       # pull block
            if self.tx: self.osr = self.tx.pop(0)
            else: stall = True
        elif op == 3:                                  # out
            dest, n = (i >> 5) & 7, (i & 31) or 32
            v = self.osr >> (32 - n); self.osr = (self.osr << n) & 0xFFFFFFFF
            if dest == 0:
                for k in range(min(n, self.out_count)): self.out[self.out_base + k] = (v >> k) & 1
            elif dest == 1: self.x = v
            elif dest == 2: self.y = v
            else: raise ValueError(hex(i))
        elif op == 0:                                  # jmp
            cond, addr = (i >> 5) & 7, i & 31
            take = {0: True, 1: self.x == 0, 3: self.y == 0, 4: self.y != 0}[cond]
            if cond == 4: self.y = (self.y - 1) & 0xFFFFFFFF
            if take: nxt = addr
        elif op == 1:                                  # wait 0 gpio n
            if gpio(i & 31, cyc - SYNC) != ((i >> 7) & 1): stall = True
        elif op == 2:                                  # in pins
            n = (i & 31) or 32
            v = sum(pin_hist(self.in_base + k, cyc - SYNC) << k for k in range(n))
            self.isr = ((self.isr << n) | v) & 0xFFFFFFFF; self.isr_n += n
            if self.isr_n >= 8: self.rx.append(self.isr & 0xFF); self.isr = 0; self.isr_n = 0
        elif op == 5: pass                             # mov y, y (nop)
        elif op == 7:                                  # set
            dest, v = (i >> 5) & 7, i & 31
            if dest == 2: self.y = v
            elif dest == 4:
                for k in range(self.out_count): self.dirs[self.out_base + k] = (v >> k) & 1
            else: raise ValueError(hex(i))
        else: raise ValueError(hex(i))
        if not stall: self.pc = nxt; self.delay = d

def run(lanes, header, words, reply, busy_until_ns=0, seed=1):
    rnd = random.Random(seed)
    name = "kagura_qspi" if lanes == 4 else "kagura_spi"
    ins, wt, w = load(header, name)
    io0 = 2; busy_pin = 8
    sm = SM(ins, wt, w, io0, lanes, io0 if lanes == 4 else io0 + 1, 3, busy_pin)
    for k in range(lanes if lanes == 4 else 1): sm.dirs[io0 + k] = 1
    sm.tx = list(words)
    hist = {}                       # pin -> list of (time, value) as seen at the Pico pin
    def set_pin(p, t, v):
        h = hist.setdefault(p, [(-1e9, 0)])
        if h[-1][1] != v: h.append((t, v))
    def level(p, t):
        v = 0
        for (tt, vv) in hist.get(p, [(-1e9, 0)]):
            if tt <= t: v = vv
        return v
    pin_hist = lambda p, c: level(p, c * T)
    gpio = lambda p, c: 1 if (p == busy_pin and c * T < busy_until_ns) else 0
    rises, falls, host_changes = [], [], {k: [] for k in range(4)}
    fpga_drive_from = None; fpga_events = []       # (time, nibble/bit) scheduled FPGA output changes
    prev_sck = 0; prev_out = {}; prev_dirs = dict(sm.dirs)
    # FPGA model: SPI shifts `reply` bytes MSB first starting at /CS fall (bit 7 ready before the
    # first rise); QSPI starts after the count byte: it drives from the first dummy rise and the
    # nibble after each rise is the next one of the dummy byte (0) followed by `reply`.
    if lanes == 1:
        bits = [(b >> (7 - k)) & 1 for b in reply for k in range(8)]
        # t_CSS makes the first status bit valid before the first host clock.
        set_pin(io0 + 1, -100.0, bits[0])
    else:
        nibbles = [0, 0] + [(b >> s) & 15 for b in reply for s in (4, 0)]
    nrise = 0; host_rel_time = None; contention = []
    for cyc in range(200000):
        t = cyc * T
        sm.step(cyc, pin_hist, gpio)
        # host-driven pins
        for k in range(4):
            p = io0 + k
            if sm.dirs.get(p) and (lanes == 4 or k == 0):
                v = sm.out.get(p, 0)
                if prev_out.get(p) != v: host_changes[k].append(t)
                prev_out[p] = v
                if lanes == 1 or fpga_drive_from is None or t < fpga_drive_from: set_pin(p, t + BOARD, v)
        if lanes == 4 and prev_dirs.get(io0) and not sm.dirs.get(io0): host_rel_time = t
        prev_dirs = dict(sm.dirs)
        if sm.sck != prev_sck:
            (rises if sm.sck else falls).append(t)
            if sm.sck:
                nrise += 1; r = t + BOARD
                delay = r + rnd.uniform(37.0, 56.0) + 5.0 + BOARD   # adapter + output buffer + board
                if lanes == 1:
                    if nrise < len(bits): fpga_events.append((delay, io0 + 1, bits[nrise]))
                else:
                    # header (2 rises) + count (2 rises) are host driven; dummy starts at rise 5
                    if nrise >= 5:
                        if fpga_drive_from is None: fpga_drive_from = delay
                        idx = nrise - 5 + 1
                        if idx < len(nibbles):
                            for k in range(4): fpga_events.append((delay, io0 + k, (nibbles[idx] >> k) & 1))
            prev_sck = sm.sck
        for e in [e for e in fpga_events if e[0] <= t]:
            set_pin(e[1], e[0], e[2]); fpga_events.remove(e)
        if lanes == 4 and fpga_drive_from is not None and t >= fpga_drive_from and sm.dirs.get(io0):
            contention.append(t)
        if not sm.tx and sm.pc == sm.wrap_t and not sm.delay and cyc > 10 and not fpga_events:
            break
    # timing checks
    highs = [f - r for r, f in zip(rises, falls[1:] if falls and falls[0] < rises[0] else falls)]
    lows = [r - f for f, r in zip(falls, rises[1:])]
    setup = min(r - max([c for c in host_changes[0] if c <= r] or [-1e9]) for r in rises[:4 if lanes == 4 else 8])
    return dict(rx=sm.rx, rises=rises, highs=highs, lows=lows, host_setup=setup,
                host_rel=host_rel_time, fpga_from=fpga_drive_from, contention=contention)

def main(header):
    ok = True
    # SPI: write header + 3 data bytes (one with BUSY flag), and a read of 4 bytes.
    reply = [0x20, 0x4B, 0x39, 0x00, 0x02, 0x13, 0xA5, 0x5A]
    words = [(b << 23) for b in [0x87, 0x04, 0x00, 0x00]] + [(1 << 31) | (0x11 << 23)] + [0] * 3
    r = run(1, header, words, reply, busy_until_ns=0)
    print("SPI rx", [hex(b) for b in r["rx"]], "expected", [hex(b) for b in reply])
    ok &= r["rx"] == reply
    print("SPI SCK high ns min/max %.1f/%.1f, low min %.1f, period(within byte) %.1f" %
          (min(r["highs"]), max(r["highs"]), min(r["lows"]), r["rises"][1] - r["rises"][0]))
    print("SPI MOSI setup before rise (first byte) min %.1f ns" % r["host_setup"])
    ok &= abs(min(r["highs"]) - 50) < 1 and min(r["lows"]) >= 49
    # BUSY gating: BUSY high until 3us; byte 4 (flagged) must not start before it falls.
    r2 = run(1, header, words, reply, busy_until_ns=5000)
    gated = [x for x in r2["rises"] if x > 5000]
    print("SPI BUSY: rises before 5us %d (header+3 bytes = 32 expected), first flagged rise at %.0f ns" %
          (len(r2["rises"]) - len(gated), gated[0]))
    ok &= len(r2["rises"]) - len(gated) == 32 and gated[0] > 5000 + SYNC * T
    # Read data across output-delay draws in both modes.
    bad = 0
    for seed in range(50):
        bad += run(1, header, words, reply, seed=seed)["rx"] != reply
        s = run(4, header, [(0x98 << 22), (1 << 30) | (3 << 22), 0, 0, 0, 0], [0x4B, 0x39, 0x02], seed=seed)
        bad += s["rx"][3:] != [0x4B, 0x39, 0x02] or bool(s["contention"])
    print("50 output-delay draws x 2 modes: %d failures" % bad)
    ok &= bad == 0
    # QSPI read: header, count(release), dummy, 3 data bytes.
    qreply = [0x4B, 0x39, 0x02]
    qwords = [(0x98 << 22), (1 << 30) | (3 << 22), 0, 0, 0, 0]
    q = run(4, header, qwords, qreply)
    print("QSPI rx", [hex(b) for b in q["rx"]][3:], "expected", [hex(b) for b in qreply])
    ok &= q["rx"][3:] == qreply
    if q["host_rel"] is None:
        print("QSPI host never released IO, contention cycles %d" % len(q["contention"]))
        ok = False
    else:
        print("QSPI host releases IO at %.1f ns, FPGA drives from %.1f ns, margin %.1f ns, contention cycles %d" %
              (q["host_rel"], q["fpga_from"], q["fpga_from"] - q["host_rel"], len(q["contention"])))
        ok &= q["host_rel"] < q["fpga_from"] and not q["contention"]
    print("QSPI SCK high min/max %.1f/%.1f, low min %.1f" % (min(q["highs"]), max(q["highs"]), min(q["lows"])))
    ok &= abs(min(q["highs"]) - 50) < 1 and min(q["lows"]) >= 49
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
