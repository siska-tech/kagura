# SPDX-License-Identifier: Apache-2.0
"""Offline contracts for the hardware acceptance fixture (no real I/O)."""
import ast
import importlib.util
from pathlib import Path
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / 'software/micropython/examples/tile1200_accept.py'
spec = importlib.util.spec_from_file_location('fixture', FIXTURE)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class AcceptanceFixtureTests(unittest.TestCase):
    def test_generated_register_names(self):
        regs = ast.parse((ROOT / 'software/micropython/kagura/regs.py').read_text())
        names = {target.id for node in regs.body if isinstance(node, ast.Assign)
                 for target in node.targets if isinstance(target, ast.Name)}
        fixtures = (FIXTURE, FIXTURE.with_name('tile1200_cache_accept.py'))
        used = {node.attr for path in fixtures
                for node in ast.walk(ast.parse(path.read_text()))
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == 'R'}
        self.assertFalse(used - names, used - names)

    def test_public_pattern_windows_and_hardware_crc(self):
        self.assertEqual([fixture.tile_address(n) for n in (0, 1023, 1024, 1199)],
                         [0, 0x7FE0, 0xB000, 0xC5E0])
        data = b''.join(fixture.tile_bytes(n) for n in range(1200))
        self.assertEqual(len(data), 38400)
        self.assertEqual(zlib.crc32(data), 2221330119)
        self.assertIn(1200, fixture.BOUNDARIES)
        self.assertIn(2047, fixture.BOUNDARIES)


if __name__ == '__main__':
    unittest.main(verbosity=2)
