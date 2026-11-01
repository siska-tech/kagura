# SPDX-License-Identifier: Apache-2.0
"""PC/RegisterModel benchmark: timings are NOT hardware transport timings."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'software/micropython/tests'))
import test_driver as T
sys.path.insert(0,str(root/'software/micropython/examples'))
from kagura import Kagura, regs as R
from kagura_ja import Font
import ui_benchmark as B

model = T.RegisterModel()
model.ext[R.EXT_SCREEN_HEIGHT] = 240
model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
device = Kagura(model).probe()
font = Font(str(root/'software/micropython/fonts/misaki8.kfnt'))
app, widgets = B.make(device,font,exclusive=True)
try:
    print('PLATFORM CPython RegisterModel; Python raster; no FPGA, not RP2040 performance')
    app.step()
    B.baseline(app)
    B.run(app,widgets)
finally:
    app.close()
    font.close()
