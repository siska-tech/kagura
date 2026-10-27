# SPDX-License-Identifier: Apache-2.0
from .device import Kagura, DeviceError


def connect(ready_timeout_us=100_000, **config):
    from .transport_rp2 import PIOTransport
    transport = PIOTransport(**config)
    try:
        device = Kagura(transport)
        device.probe(ready_timeout_us)
        return device
    except BaseException:
        transport.deinit()
        raise
