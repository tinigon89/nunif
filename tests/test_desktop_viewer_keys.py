import unittest

from iw3.desktop.local_viewer import divergence_delta_for_key, DIVERGENCE_STEP


class DivergenceKeyTest(unittest.TestCase):
    def test_right_bracket_increases(self):
        self.assertEqual(divergence_delta_for_key("]"), DIVERGENCE_STEP)

    def test_left_bracket_decreases(self):
        self.assertEqual(divergence_delta_for_key("["), -DIVERGENCE_STEP)

    def test_step_is_one_tenth(self):
        self.assertEqual(DIVERGENCE_STEP, 0.1)

    def test_other_keys_are_ignored(self):
        for ch in ("a", "", "{", "}", "\x1b"):
            self.assertIsNone(divergence_delta_for_key(ch))


if __name__ == "__main__":
    unittest.main()
