# SPDX-License-Identifier: Apache-2.0
"""Validate baseline stimulus cardinality and aggregation, not host speed."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_framebuffer  # installs SDK host shims and examples path
from unittest import TestCase, main
import framebuffer_transport_benchmark as B


class StimulusTests(TestCase):
    def test_exact_unique_in_range(self):
        for count in (0,1,2,10,32,100,256,512,1023,1024,1200):
            for layout in ('contiguous','dispersed','narrow_rect','wide_rect','boundary'):
                selected=B.indices(count,layout)
                if selected is None:
                    self.assertEqual(layout,'narrow_rect')
                    self.assertGreater(count,120)
                    continue
                self.assertEqual(len(selected),count)
                self.assertEqual(len(set(selected)),count)
                self.assertTrue(all(0<=x<1200 for x in selected))
        self.assertEqual(list(B.indices(2,'boundary')),[1023,1024])
        for count,width in ((256,16),(512,32)):
            values=list(B.indices(count,'compact_rect'))
            self.assertEqual(len(set(values)),count)
            self.assertEqual(values[-1],15*40+width-1)

    def test_distribution_and_nearest_rank(self):
        s=B.detail([9,1,4,2])
        self.assertEqual(s['median_us'],3)
        self.assertEqual(s['mean_us'],4)
        self.assertEqual(s['p95_us'],9)
        self.assertEqual(s['samples_us'],[9,1,4,2])
        self.assertEqual(B.detail(list(range(100)))['p95_us'],94)


if __name__=='__main__':main()
