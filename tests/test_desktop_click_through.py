import unittest
from types import SimpleNamespace

from iw3.desktop.click_through import (
    view_to_image, image_to_source, source_to_monitor, to_absolute,
    layout_from_args, MouseForwarder,
    LAYOUT_SBS, LAYOUT_TB, LAYOUT_MONO,
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_WHEEL,
)


class ViewToImageTest(unittest.TestCase):
    # window 1000x500 showing a 2000x500 image -> drawn 1000x250 centered (letterbox top/bottom 125px)
    VIEW = (1000, 500)
    IMAGE = (2000, 500)

    def test_center_maps_to_center(self):
        self.assertEqual(view_to_image(500, 250, self.VIEW, self.IMAGE), (0.5, 0.5))

    def test_top_left_of_drawn_area_is_origin(self):
        self.assertEqual(view_to_image(0, 125, self.VIEW, self.IMAGE), (0.0, 0.0))

    def test_click_in_letterbox_is_ignored(self):
        self.assertIsNone(view_to_image(10, 10, self.VIEW, self.IMAGE))
        self.assertIsNone(view_to_image(10, 490, self.VIEW, self.IMAGE))

    def test_pillarbox_left_right(self):
        # window 1000x500 showing a 500x500 image -> drawn 500x500 at x0=250
        self.assertIsNone(view_to_image(100, 250, (1000, 500), (500, 500)))
        self.assertEqual(view_to_image(500, 250, (1000, 500), (500, 500)), (0.5, 0.5))


class ImageToSourceTest(unittest.TestCase):
    def test_sbs_left_and_right_half_map_to_same_point(self):
        img = (3840, 1080)
        self.assertEqual(image_to_source(0.25, 0.5, LAYOUT_SBS, img, 16 / 9), (0.5, 0.5))
        self.assertEqual(image_to_source(0.75, 0.5, LAYOUT_SBS, img, 16 / 9), (0.5, 0.5))

    def test_sbs_scales_within_half(self):
        su, sv = image_to_source(0.1, 0.5, LAYOUT_SBS, (3840, 1080), 16 / 9)
        self.assertAlmostEqual(su, 0.2)

    def test_tb_top_and_bottom_map_to_same_point(self):
        img = (1920, 2160)
        self.assertEqual(image_to_source(0.5, 0.25, LAYOUT_TB, img, 16 / 9), (0.5, 0.5))
        self.assertEqual(image_to_source(0.5, 0.75, LAYOUT_TB, img, 16 / 9), (0.5, 0.5))

    def test_mono_is_identity(self):
        self.assertEqual(image_to_source(0.3, 0.7, LAYOUT_MONO, (1920, 1080), 16 / 9), (0.3, 0.7))

    def test_horizontal_padding_inside_eye_is_removed(self):
        # eye cell 2048x1080 holding a 16:9 source (1920 wide): 64px pad on each side
        img = (4096, 1080)
        su, _ = image_to_source(64 / 4096, 0.5, LAYOUT_SBS, img, 16 / 9)
        self.assertAlmostEqual(su, 0.0, places=6)
        self.assertEqual(image_to_source(0.25, 0.5, LAYOUT_SBS, img, 16 / 9), (0.5, 0.5))

    def test_click_in_padding_is_ignored(self):
        img = (4096, 1080)
        self.assertIsNone(image_to_source(10 / 4096, 0.5, LAYOUT_SBS, img, 16 / 9))


class MonitorMappingTest(unittest.TestCase):
    def test_source_to_monitor_pixel(self):
        rect = (3840, 0, 1920, 1080)  # second monitor to the right
        self.assertEqual(source_to_monitor(0.0, 0.0, rect), (3840, 0))
        self.assertEqual(source_to_monitor(1.0, 1.0, rect), (3840 + 1919, 1079))
        self.assertEqual(source_to_monitor(0.5, 0.5, rect), (3840 + 960, 540))

    def test_to_absolute_spans_virtual_screen(self):
        vrect = (0, 0, 5760, 1080)
        self.assertEqual(to_absolute(0, 0, vrect), (0, 0))
        self.assertEqual(to_absolute(5759, 1079, vrect), (65535, 65535))


class LayoutFromArgsTest(unittest.TestCase):
    def make(self, **flags):
        base = dict(full_sbs=False, half_sbs=False, cross_eyed=False, rgbd=False, half_rgbd=False,
                    tb=False, half_tb=False, anaglyph=None)
        base.update(flags)
        return SimpleNamespace(**base)

    def test_layouts(self):
        self.assertEqual(layout_from_args(self.make(full_sbs=True)), LAYOUT_SBS)
        self.assertEqual(layout_from_args(self.make(half_sbs=True)), LAYOUT_SBS)
        self.assertEqual(layout_from_args(self.make(cross_eyed=True)), LAYOUT_SBS)
        self.assertEqual(layout_from_args(self.make(tb=True)), LAYOUT_TB)
        self.assertEqual(layout_from_args(self.make(half_tb=True)), LAYOUT_TB)
        self.assertEqual(layout_from_args(self.make(anaglyph="dubois")), LAYOUT_MONO)


class FakeBackend:
    def __init__(self):
        self.cursor = (100, 100)
        self.sent = []
        self.cursor_sets = []
        self.foreground_restored = 0

    def virtual_screen_rect(self):
        return (0, 0, 7680, 2160)

    def get_cursor_pos(self):
        return self.cursor

    def set_cursor_pos(self, x, y):
        self.cursor_sets.append((x, y))

    def send(self, ax, ay, flags, wheel_delta=0):
        self.sent.append((ax, ay, flags, wheel_delta))

    def restore_foreground(self):
        self.foreground_restored += 1


class MouseForwarderTest(unittest.TestCase):
    def make(self):
        backend = FakeBackend()
        fwd = MouseForwarder(monitor_rect=(0, 0, 3840, 2160), layout=LAYOUT_SBS,
                             image_size=(3840, 1080), source_aspect=16 / 9, backend=backend)
        return fwd, backend

    def test_left_click_center_of_left_eye_hits_monitor_center(self):
        fwd, backend = self.make()
        view = (1920, 540)  # same aspect as image, no letterbox
        self.assertTrue(fwd.click(480, 270, view, "left"))
        ex, ey = to_absolute(1920, 1080, backend.virtual_screen_rect())
        # a click is a press followed by a release at the same point, with no cursor move in between
        self.assertEqual(len(backend.sent), 2)
        (ax1, ay1, flags1, _), (ax2, ay2, flags2, _) = backend.sent
        self.assertEqual((ax1, ay1), (ex, ey))
        self.assertEqual((ax2, ay2), (ex, ey))
        self.assertTrue(flags1 & MOUSEEVENTF_LEFTDOWN)
        self.assertTrue(flags2 & MOUSEEVENTF_LEFTUP)
        self.assertEqual(backend.cursor_sets, [(100, 100)])  # restored once, after the release

    def test_right_click_flags(self):
        fwd, backend = self.make()
        fwd.click(480, 270, (1920, 540), "right")
        self.assertTrue(backend.sent[0][2] & MOUSEEVENTF_RIGHTDOWN)
        self.assertTrue(backend.sent[1][2] & MOUSEEVENTF_RIGHTUP)

    def test_unknown_button_is_ignored(self):
        fwd, backend = self.make()
        self.assertFalse(fwd.click(480, 270, (1920, 540), "middle"))
        self.assertEqual(backend.sent, [])

    def test_wheel_forwards_delta(self):
        fwd, backend = self.make()
        self.assertTrue(fwd.wheel(480, 270, (1920, 540), 120))
        ax, ay, flags, delta = backend.sent[-1]
        self.assertTrue(flags & MOUSEEVENTF_WHEEL)
        self.assertEqual(delta, 120)

    def test_cursor_restored_and_focus_returned_after_click(self):
        fwd, backend = self.make()
        fwd.click(480, 270, (1920, 540), "left")
        self.assertEqual(backend.cursor_sets[-1], (100, 100))
        self.assertEqual(backend.foreground_restored, 1)

    def test_click_outside_image_sends_nothing(self):
        fwd, backend = self.make()
        self.assertFalse(fwd.click(5, 5, (1920, 1080), "left"))  # letterbox area
        self.assertEqual(backend.sent, [])

    def test_disabled_sends_nothing(self):
        fwd, backend = self.make()
        fwd.enabled = False
        self.assertFalse(fwd.click(480, 270, (1920, 540), "left"))
        self.assertEqual(backend.sent, [])


if __name__ == "__main__":
    unittest.main()
