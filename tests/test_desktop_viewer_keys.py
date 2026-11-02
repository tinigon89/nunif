import unittest

from iw3.desktop.local_viewer import FPS_TOGGLE_KEY, format_fps_line, key_action


class ViewerKeyTest(unittest.TestCase):
    def test_plain_brackets_change_divergence(self):
        self.assertEqual(key_action("]", ctrl=False, alt=False), ("divergence", +1))
        self.assertEqual(key_action("[", ctrl=False, alt=False), ("divergence", -1))

    def test_ctrl_brackets_change_foreground_scale(self):
        self.assertEqual(key_action("]", ctrl=True, alt=False), ("foreground_scale", +1))
        self.assertEqual(key_action("[", ctrl=True, alt=False), ("foreground_scale", -1))

    def test_alt_brackets_change_convergence(self):
        self.assertEqual(key_action("]", ctrl=False, alt=True), ("convergence", +1))
        self.assertEqual(key_action("[", ctrl=False, alt=True), ("convergence", -1))

    def test_other_keys_are_ignored(self):
        for ch in ("a", "", "{", "}", "\x1b"):
            self.assertIsNone(key_action(ch, ctrl=False, alt=False))
        self.assertIsNone(key_action("]", ctrl=True, alt=True))

    def test_fps_toggle_key(self):
        self.assertEqual(FPS_TOGGLE_KEY, "F")


class FpsLineTest(unittest.TestCase):
    def test_format_rounds_to_integers(self):
        self.assertEqual(format_fps_line(57.4, 59.6, 56.9), "FPS 57 | capture 60 | render 57")

    def test_format_handles_none(self):
        self.assertEqual(format_fps_line(None, None, None), "FPS - | capture - | render -")


if __name__ == "__main__":
    unittest.main()
