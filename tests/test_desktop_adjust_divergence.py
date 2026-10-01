import threading
import unittest
from types import SimpleNamespace

from iw3.desktop.utils import adjust_divergence


def make_args(divergence, hook=None):
    state = {"args_lock": threading.Lock()}
    if hook is not None:
        state["on_divergence_changed"] = hook
    return SimpleNamespace(divergence=divergence, state=state)


class AdjustDivergenceTest(unittest.TestCase):
    def test_increase_by_step_is_rounded_to_one_decimal(self):
        args = make_args(1.1)
        self.assertEqual(adjust_divergence(args, 0.1), 1.2)
        self.assertEqual(args.divergence, 1.2)

    def test_decrease_by_step(self):
        args = make_args(1.1)
        self.assertEqual(adjust_divergence(args, -0.1), 1.0)

    def test_clamps_at_zero(self):
        args = make_args(0.05)
        self.assertEqual(adjust_divergence(args, -0.1), 0.0)

    def test_clamps_at_ten(self):
        args = make_args(9.95)
        self.assertEqual(adjust_divergence(args, 0.1), 10.0)

    def test_notifies_hook_with_new_value(self):
        seen = []
        args = make_args(2.0, hook=seen.append)
        adjust_divergence(args, 0.1)
        self.assertEqual(seen, [2.1])

    def test_works_without_hook(self):
        args = make_args(2.0)
        adjust_divergence(args, 0.1)  # must not raise


if __name__ == "__main__":
    unittest.main()
