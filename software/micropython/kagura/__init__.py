# SPDX-License-Identifier: Apache-2.0
from .device import Kagura, DeviceError

SPEEDS = (5_000_000, 2_500_000, 1_000_000)


def connect(ready_timeout_us=100_000, baudrate=None, accelerate=True, **config):
    """Open and probe KAGURA.

    baudrate=None tries SPEEDS fastest first and keeps the first speed whose
    link check passes. An explicit baudrate is used as given, without fallback.
    accelerate=True then turns on transport.accelerate(): kagura.link where its
    Viper kernels load (one call per transaction and per write_memory, fence,
    commit and flush), the plain Python transport elsewhere.
    """
    from machine import freq
    from .transport_rp2 import PIOTransport
    if baudrate is None:
        # The state machine runs at 12x SCK.
        speeds = [b for b in SPEEDS if b * 12 <= freq()] or [SPEEDS[-1]]
    else:
        speeds = [baudrate]
    for i, speed in enumerate(speeds):
        transport = PIOTransport(baudrate=speed, **config)
        try:
            device = Kagura(transport)
            device.probe(ready_timeout_us)
            if baudrate is None:
                device.check_link()
            if accelerate and hasattr(transport, "accelerate"):
                transport.accelerate()
            return device
        except OSError:
            # READY/BUSY do not depend on SCK; a slower speed cannot help.
            idle = transport.idle()
            transport.deinit()
            if not idle or i == len(speeds) - 1:
                raise
        except BaseException:
            transport.deinit()
            raise
