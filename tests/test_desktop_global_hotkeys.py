import unittest

import wx

from iw3.desktop.local_viewer import (
    GLOBAL_HOTKEYS,
    HOTKEY_CONVERGENCE_DOWN,
    HOTKEY_CONVERGENCE_UP,
    HOTKEY_DIVERGENCE_DOWN,
    HOTKEY_DIVERGENCE_UP,
    HOTKEY_FOREGROUND_DOWN,
    HOTKEY_FOREGROUND_UP,
    VK_OEM_4,
    VK_OEM_6,
    hotkey_action,
)


class GlobalHotkeyTest(unittest.TestCase):
    def test_bracket_virtual_keys(self):
        # US layout: VK_OEM_4 is "[", VK_OEM_6 is "]"
        self.assertEqual(VK_OEM_4, 0xDB)
        self.assertEqual(VK_OEM_6, 0xDD)

    def test_modifiers_per_parameter(self):
        self.assertEqual(GLOBAL_HOTKEYS[HOTKEY_DIVERGENCE_DOWN][:2], (0, VK_OEM_4))
        self.assertEqual(GLOBAL_HOTKEYS[HOTKEY_DIVERGENCE_UP][:2], (0, VK_OEM_6))
        self.assertEqual(GLOBAL_HOTKEYS[HOTKEY_FOREGROUND_DOWN][:2], (wx.MOD_CONTROL, VK_OEM_4))
        self.assertEqual(GLOBAL_HOTKEYS[HOTKEY_FOREGROUND_UP][:2], (wx.MOD_CONTROL, VK_OEM_6))
        self.assertEqual(GLOBAL_HOTKEYS[HOTKEY_CONVERGENCE_DOWN][:2], (wx.MOD_ALT, VK_OEM_4))
        self.assertEqual(GLOBAL_HOTKEYS[HOTKEY_CONVERGENCE_UP][:2], (wx.MOD_ALT, VK_OEM_6))

    def test_hotkey_ids_are_distinct_and_positive(self):
        ids = list(GLOBAL_HOTKEYS)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i > 0 for i in ids))

    def test_hotkey_action_maps_to_parameter_and_direction(self):
        self.assertEqual(hotkey_action(HOTKEY_DIVERGENCE_UP), ("divergence", +1))
        self.assertEqual(hotkey_action(HOTKEY_DIVERGENCE_DOWN), ("divergence", -1))
        self.assertEqual(hotkey_action(HOTKEY_FOREGROUND_UP), ("foreground_scale", +1))
        self.assertEqual(hotkey_action(HOTKEY_FOREGROUND_DOWN), ("foreground_scale", -1))
        self.assertEqual(hotkey_action(HOTKEY_CONVERGENCE_UP), ("convergence", +1))
        self.assertEqual(hotkey_action(HOTKEY_CONVERGENCE_DOWN), ("convergence", -1))
        self.assertIsNone(hotkey_action(999))


if __name__ == "__main__":
    unittest.main()
