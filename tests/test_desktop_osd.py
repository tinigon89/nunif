import unittest

from iw3.desktop.local_viewer import osd_quads, OSD_DURATION, OSD_REL_HEIGHT, OSD_REL_TOP


class OsdQuadsTest(unittest.TestCase):
    # the SBS image is drawn at x0=0, y0=125, 1000x250 (two eye cells of 500x250)
    DRAW = (0, 125, 1000, 250)

    def test_duration_is_three_seconds(self):
        self.assertEqual(OSD_DURATION, 3.0)

    def test_sbs_draws_once_per_eye_at_same_relative_position(self):
        quads = osd_quads(self.DRAW, "sbs", text_aspect=4.0)
        self.assertEqual(len(quads), 2)
        (x1, y1, w1, h1), (x2, y2, w2, h2) = quads
        self.assertEqual((y1, w1, h1), (y2, w2, h2))
        self.assertAlmostEqual(x2 - x1, 500)  # shifted by exactly one eye cell
        self.assertAlmostEqual(h1, 250 * OSD_REL_HEIGHT)
        self.assertAlmostEqual(w1, h1 * 4.0)
        self.assertAlmostEqual(y1, 125 + 250 * OSD_REL_TOP)
        self.assertAlmostEqual(x1 + w1 / 2, 250)  # centered in the left eye cell

    def test_tb_stacks_vertically(self):
        draw = (0, 0, 1000, 500)  # two eye cells of 1000x250
        quads = osd_quads(draw, "tb", text_aspect=4.0)
        self.assertEqual(len(quads), 2)
        (x1, y1, w1, h1), (x2, y2, w2, h2) = quads
        self.assertEqual((x1, w1, h1), (x2, w2, h2))
        self.assertAlmostEqual(y2 - y1, 250)
        self.assertAlmostEqual(h1, 250 * OSD_REL_HEIGHT)

    def test_mono_draws_once(self):
        quads = osd_quads((0, 0, 1000, 500), "mono", text_aspect=4.0)
        self.assertEqual(len(quads), 1)
        x, y, w, h = quads[0]
        self.assertAlmostEqual(x + w / 2, 500)

    def test_wide_text_is_capped_to_eye_width(self):
        quads = osd_quads(self.DRAW, "sbs", text_aspect=100.0)
        x, y, w, h = quads[0]
        self.assertLessEqual(w, 500 * 0.9)
        self.assertGreaterEqual(x, 0)


if __name__ == "__main__":
    unittest.main()
