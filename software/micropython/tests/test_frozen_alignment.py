# SPDX-License-Identifier: Apache-2.0
"""Build-time native alignment; hardware CRC tests check actual execution."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    'align_frozen', Path(__file__).resolve().parents[1] / 'align_frozen.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FrozenAlignment(unittest.TestCase):
    def test_only_native_array_alignment_changes(self):
        source = '''static const byte fun_data_native[4] __attribute__((section(".text"))) __attribute__ ((aligned (2))) = {1,2,3,4};
static const byte other[2] __attribute__((aligned (2))) = {5,6};
static const byte fun_data_bytecode[2] = {7,8};
'''
        expected = source.replace('aligned (2)', 'aligned (4)', 1)
        self.assertEqual(module.align(source), expected)
        self.assertEqual(module.align(expected), expected)


if __name__ == '__main__':
    unittest.main()
