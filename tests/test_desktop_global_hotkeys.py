import unittest

from iw3.desktop.local_viewer import (
    GLOBAL_HOTKEYS, HOTKEY_DIVERGENCE_DOWN, HOTKEY_DIVERGENCE_UP,
    VK_OEM_4, VK_OEM_6, DIVERGENCE_STEP, divergence_delta_for_hotkey,
)


class GlobalHotkeyTest(unittest.TestCase):
    def test_bracket_virtual_keys(self):
        # US layout: VK_OEM_4 is "[", VK_OEM_6 is "]"
        self.assertEqual(VK_OEM_4, 0xDB)
        self.assertEqual(VK_OEM_6, 0xDD)

    def test_hotkeys_are_plain_brackets_without_modifiers(self):
        self.assertEqual(GLOBAL_HOTKEYS[HOTKEY_DIVERGENCE_DOWN], (0, VK_OEM_4))
        self.assertEqual(GLOBAL_HOTKEYS[HOTKEY_DIVERGENCE_UP], (0, VK_OEM_6))

    def test_hotkey_ids_are_distinct_and_positive(self):
        ids = list(GLOBAL_HOTKEYS)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i > 0 for i in ids))

    def test_delta_for_hotkey(self):
        self.assertEqual(divergence_delta_for_hotkey(HOTKEY_DIVERGENCE_UP), DIVERGENCE_STEP)
        self.assertEqual(divergence_delta_for_hotkey(HOTKEY_DIVERGENCE_DOWN), -DIVERGENCE_STEP)
        self.assertIsNone(divergence_delta_for_hotkey(999))


if __name__ == "__main__":
    unittest.main()
