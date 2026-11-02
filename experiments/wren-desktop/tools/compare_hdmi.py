"""Reuse unchanged native Desktop HDMI classification against MVP references.
Usage: python compare_hdmi.py REFERENCE_PGM_DIRECTORY HARDWARE_RUN_DIRECTORY
Needs numpy/Pillow. Captures must be 1280x960 as recorded by hardware_run.py.
"""
from pathlib import Path
import shutil
import sys
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'c-gem-desktop/tools'))
import hdmi_compare
reference,run=map(Path,sys.argv[1:])
(run/'stills').mkdir(exist_ok=True)
for i in range(1,7):
    Image.open(reference/f'frame-{i}.pgm').save(reference/f'frame-{i}.png')
    shutil.copyfile(run/f'frame-{i}.png',run/'stills'/f'frame-{i}.png')
hdmi_compare.SCENES=[f'frame-{i}' for i in range(1,7)]
sys.argv=[sys.argv[0],str(reference),str(run)]
hdmi_compare.main()
