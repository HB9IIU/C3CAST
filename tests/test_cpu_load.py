import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webapp'))
from cpu_load import CpuLoad


class CpuSampling(unittest.TestCase):
    def test_system_percentage_uses_deltas_and_caches_between_polls(self):
        now = [0]
        read = Mock(side_effect=[(100, 1000), (140, 1100), (240, 1200)])
        cpu = CpuLoad(read, lambda: now[0])
        self.assertIsNone(cpu.percent())
        now[0] = 1
        self.assertEqual(cpu.percent(), 60)
        now[0] = 1.5
        self.assertEqual(cpu.percent(), 60)
        self.assertEqual(read.call_count, 2)
        now[0] = 2
        self.assertEqual(cpu.percent(), 0)

    def test_missing_or_reset_counters_are_unavailable_and_recover(self):
        now = [0]
        read = Mock(side_effect=[None, (10, 100), (10, 200), (1, 10), (11, 110)])
        cpu = CpuLoad(read, lambda: now[0])
        for tick, expected in enumerate([None, None, 100, None, 90]):
            now[0] = tick
            self.assertEqual(cpu.percent(), expected)


if __name__ == '__main__':
    unittest.main()
