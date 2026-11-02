"""Supplementary geometry diagnostic, not a replacement colour acceptance test.

The unchanged classifier has no 3x3 interior from which to learn the one-pixel
red outline's capture colour. Keep its failures, and independently ask whether
the red-dominant pixels occupy exactly the reference outline at the already
selected global sampling phase (-1, 0). No phase or threshold search is done.
"""
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image
reference=np.asarray(Image.open(sys.argv[1]))
capture=np.asarray(Image.open(sys.argv[2]).convert('RGB')).astype(np.int32)
sample=capture[np.arange(240)*4+2][:,np.arange(320)*4+1]
expected=reference==6
observed=(sample[:,:,0]>sample[:,:,1]+40)&(sample[:,:,0]>sample[:,:,2]+40)
values=sample[expected]
result=dict(kind='supplementary red geometry only, original colour test unchanged',sampling_dx=-1,sampling_dy=0,
            rule='R > G+40 and R > B+40',expected_pixels=int(expected.sum()),observed_pixels=int(observed.sum()),
            missing=int((expected&~observed).sum()),unexpected=int((observed&~expected).sum()),
            captured_outline_rgb_min=values.min(axis=0).tolist(),captured_outline_rgb_max=values.max(axis=0).tolist())
print(json.dumps(result,indent=2))
