# SPDX-License-Identifier: Apache-2.0
# Appended to bench/workloads.py in the count build. Each sample of a
# workload is bracketed by kdmark.begin()/end(); "markers" counts an empty
# bracket, which tools/m0count/count.sh subtracts.
import kdmark


def count(name, n):
    for w in TABLE:
        if w[0] == name:
            fn, n_rects = w[1], w[3]
    sc, op = setup(fn, n_rects, n)
    d, vram = sc.d, sc.vram
    for i in range(-4, 0):
        op(i)
        d.present(vram)
    begin, end = kdmark.begin, kdmark.end
    for i in range(n):
        begin()
        op(i)
        d.present(vram)
        end()
    print('%s %08x' % (name, d.crc()))


def markers(n):
    begin, end = kdmark.begin, kdmark.end
    for i in range(n):
        begin()
        end()
    print('markers')
