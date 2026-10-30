from kagurafbx.framebuffer import TileFramebuffer as OriginalFramebuffer
from kagurafbx.device import _range
class GapFramebuffer(OriginalFramebuffer):
    def flush(self, max_gap=0):
            """No I/O if clean; failure keeps the entire unconfirmed run dirty.
    
            Counters count requested pattern writes/bytes, not individual SPI
            register transactions. transfer_us includes write_memory error checks;
            wait_us includes FENCE and its checks, not a pure FPGA execution time.
            max_gap opts into sending clean gaps of at most this many tiles between
            dirty runs. Default 0 preserves exact dirty transfer. Counts describe
            sent tiles, including gaps. The buffer must be the sole VRAM owner.
            """
            if not self.initialized:
                raise RuntimeError('call initialize() successfully before flush()')
            _range(max_gap, 0, 1198, 'max_gap')
            return self._flush(max_gap)
    def _flush(self, max_gap=0):
            stats = self._stats()
            self.last_flush = stats
            start = ticks_us()
            d = self.device
            d.busy += 1
            try:
                if max_gap:
                    # Mark additional writes dirty before I/O. A failed write or
                    # FENCE must never leave any part of its expanded run clean.
                    first = self.dirty.find(b'\x01')
                    while first >= 0:
                        end = self.dirty.find(b'\x00', first)
                        if end < 0:
                            break
                        following = self.dirty.find(b'\x01', end)
                        if following < 0:
                            break
                        if following - end <= max_gap:
                            self.dirty[end:following] = b'\x01' * (following - end)
                        first = following
                tile = 0
                while tile < 1200:
                    first = self.dirty.find(b'\x01', tile)
                    if first < 0:
                        break
                    tile = self.dirty.find(b'\x00', first)
                    if tile < 0:
                        tile = 1200
                    count = tile - first
                    stats['runs'] += 1
                    stats['bytes'] += count * 32
                    stats['writes'] += 1 + int(first < 1024 < tile)
                    begin = ticks_us()
                    try:
                        self.video.tiles(first, self._view[first * 32:tile * 32])
                    finally:
                        stats['transfer_us'] += ticks_diff(ticks_us(), begin)
                    begin = ticks_us()
                    stats['fences'] += 1
                    try:
                        d.fence()
                        d.check_errors()
                    finally:
                        stats['wait_us'] += ticks_diff(ticks_us(), begin)
                    # No callback may draw while busy; only a confirmed run is clean.
                    self.dirty[first:tile] = bytes(count)
                    stats['tiles'] += count
            finally:
                d.busy -= 1
                stats['total_us'] = ticks_diff(ticks_us(), start)
            return stats
import kagurafbx.framebuffer as _fb_module
_fb_module.TileFramebuffer=GapFramebuffer
