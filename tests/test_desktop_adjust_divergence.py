import threading
import unittest
from types import SimpleNamespace

from iw3 import utils as IW3U
from iw3.desktop.utils import ADJUSTABLE_PARAMS, adjust_divergence, adjust_param


class FakeDepthModel:
    def __init__(self, metric=False):
        self.metric = metric

    def is_metric(self):
        return self.metric


def make_args(hook=None, depth_model=None, **values):
    state = {"args_lock": threading.Lock(), "depth_model": depth_model}
    if hook is not None:
        state["on_param_changed"] = hook
    base = dict(divergence=1.0, convergence=0.5, foreground_scale=0.0, mapper="auto")
    base.update(values)
    return SimpleNamespace(state=state, **base)


class AdjustDivergenceTest(unittest.TestCase):
    def test_increase_by_step_is_rounded_to_one_decimal(self):
        args = make_args(divergence=1.1)
        self.assertEqual(adjust_divergence(args, 0.1), 1.2)
        self.assertEqual(args.divergence, 1.2)

    def test_clamps_at_zero_and_ten(self):
        self.assertEqual(adjust_divergence(make_args(divergence=0.05), -0.1), 0.0)
        self.assertEqual(adjust_divergence(make_args(divergence=9.95), 0.1), 10.0)

    def test_notifies_hook_with_name_and_value(self):
        seen = []
        args = make_args(hook=lambda name, value: seen.append((name, value)), divergence=2.0)
        adjust_divergence(args, 0.1)
        self.assertEqual(seen, [("divergence", 2.1)])

    def test_works_without_hook(self):
        adjust_divergence(make_args(divergence=2.0), 0.1)  # must not raise


class AdjustParamTest(unittest.TestCase):
    def test_param_table_has_steps_and_labels(self):
        self.assertEqual(ADJUSTABLE_PARAMS["divergence"].step, 0.1)
        self.assertEqual(ADJUSTABLE_PARAMS["convergence"].step, 0.1)
        self.assertEqual(ADJUSTABLE_PARAMS["foreground_scale"].step, 0.5)
        self.assertEqual(ADJUSTABLE_PARAMS["divergence"].label, "3D Strength")
        self.assertEqual(ADJUSTABLE_PARAMS["convergence"].label, "Convergence")
        self.assertEqual(ADJUSTABLE_PARAMS["foreground_scale"].label, "Foreground Scale")

    def test_convergence_clamped_to_unit_range(self):
        args = make_args(convergence=0.95)
        self.assertEqual(adjust_param(args, "convergence", 0.1), 1.0)
        self.assertEqual(adjust_param(make_args(convergence=0.05), "convergence", -0.1), 0.0)
        self.assertEqual(adjust_param(make_args(convergence=0.5), "convergence", 0.1), 0.6)

    def test_foreground_scale_clamped_and_mapper_updated(self):
        dm = FakeDepthModel(metric=False)
        args = make_args(depth_model=dm, foreground_scale=0.0)
        self.assertEqual(adjust_param(args, "foreground_scale", 0.5), 0.5)
        self.assertEqual(args.foreground_scale, 0.5)
        self.assertEqual(args.mapper, IW3U.resolve_mapper_name(mapper=None, foreground_scale=0.5, metric_depth=False))
        self.assertEqual(adjust_param(make_args(depth_model=dm, foreground_scale=2.8), "foreground_scale", 0.5), 3.0)
        self.assertEqual(adjust_param(make_args(depth_model=dm, foreground_scale=-2.8), "foreground_scale", -0.5), -3.0)

    def test_foreground_scale_without_depth_model_keeps_mapper(self):
        args = make_args(depth_model=None, foreground_scale=0.0, mapper="auto")
        adjust_param(args, "foreground_scale", 0.5)
        self.assertEqual(args.mapper, "auto")

    def test_unknown_param_raises(self):
        with self.assertRaises(KeyError):
            adjust_param(make_args(), "nope", 0.1)


if __name__ == "__main__":
    unittest.main()
