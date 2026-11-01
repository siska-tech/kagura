# SPDX-License-Identifier: Apache-2.0
"""Clipped drawing over an SDK framebuffer; no second dirty-tile tracker."""


def intersect(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def nonempty(rect):
    return rect[0] < rect[2] and rect[1] < rect[3]


class Renderer:
    def __init__(self, backend):
        self.backend = backend
        self.width, self.height = backend.width, backend.height
        self.clip = (0, 0, self.width, self.height)

    def fill_rect(self, x, y, width, height, color):
        c = self.clip
        right, bottom = min(x + width, c[2]), min(y + height, c[3])
        x, y = max(x, c[0]), max(y, c[1])
        if x < right and y < bottom:
            self.backend.fill_rect(x, y, right - x, bottom - y, color)

    def rect(self, x, y, width, height, color):
        if width <= 0 or height <= 0:
            return
        self.fill_rect(x, y, width, 1, color)
        self.fill_rect(x, y + height - 1, width, 1, color)
        self.fill_rect(x, y, 1, height, color)
        self.fill_rect(x + width - 1, y, 1, height, color)

    def text_ascii(self, text, x, y, color):
        """Optional SDK fast path; caller has established full clip containment."""
        draw = getattr(self.backend, 'text_ascii', None)
        if draw is None:
            return False
        draw(text, x, y, color)
        return True


class FramebufferBackend:
    """Cooperative exclusive lease. Raw SDK users must obey this ownership too.

    All patterns, BG maps, OAM/display state and palette bank 0 are exclusive.
    TextLayer/independent sprites/concurrent raw graphics are unsupported.
    """
    width, height = 320, 240
    _owners = []

    def __init__(self, device, console=None, exclusive=False):
        if not exclusive and console is None:
            raise ValueError('pass exclusive=True or the active HDMI console')
        if console is not None and (console.screen is None or console.screen.device is not device):
            raise ValueError('console must own this device')
        self.device, self.console = device, console
        self.fb = None
        self.active = False
        self._restore = False
        self._reattach = False

    def start(self, theme):
        if self.active:
            return
        if any(d is self.device or d.transport is self.device.transport for d in self._owners):
            raise RuntimeError('graphics device already leased')
        from kagura.framebuffer import TileFramebuffer
        # Allocation failure leaves the console and hardware untouched.
        if self.fb is None:
            self.fb = TileFramebuffer(self.device)
        if self.console is not None and self.console.paused:
            raise RuntimeError('console already paused by another owner')
        self._owners.append(self.device)
        self.active = True
        try:
            if self.console is not None:
                self.console.pause()
                self._restore = True
                self._reattach = self.console._attached
                self.console.detach()
            for index, color in enumerate(theme.palette):
                self.fb.video.palette(index, color)
            self.fb.initialize()
        except BaseException:
            self.close()
            raise

    def fill_rect(self, x, y, width, height, color):
        self.fb.fill_rect(x, y, width, height, color)

    def text_ascii(self, text, x, y, color):
        self.fb.text(text, x, y, color)

    def flush(self):
        return self.fb.flush()

    def close(self):
        if not self.active:
            return
        # A failed console restoration retains the lease and can be retried.
        if self._restore:
            self.console.resume()
            self._restore = False
        if self._reattach:
            self.console.attach()
            self._reattach = False
        self._owners.remove(self.device)
        self.active = False
