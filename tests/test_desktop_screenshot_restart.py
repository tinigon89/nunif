"""The wc_cuda capture session can end on its own (e.g. display topology change when a monitor is
plugged in). The screenshot thread must reopen the capture instead of dying."""
import sys
import threading
import time
import types
import unittest

import torch

import iw3.desktop.screenshot_thread_cuda as stc


class FakeFrame:
    def __init__(self, h, w):
        self.frame_buffer = torch.zeros((h, w, 4), dtype=torch.uint8)


class FakeControl:
    def __init__(self, capture):
        self.capture = capture

    def stop(self):
        self.capture.stopped.set()


class FakeWindowsCapture:
    """Mimics wc_cuda.WindowsCapture.start(): blocks and calls on_frame_arrived until closed."""
    instances = []
    # behaviour per instance index: "close" = session ends immediately with no frames,
    # "error" = raises like wc_cuda does on a capture error, "ok" = delivers frames
    plan = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.handlers = {}
        self.stopped = threading.Event()
        self.index = len(FakeWindowsCapture.instances)
        FakeWindowsCapture.instances.append(self)

    def event(self, handler):
        self.handlers[handler.__name__] = handler
        return handler

    def start(self):
        mode = FakeWindowsCapture.plan[min(self.index, len(FakeWindowsCapture.plan) - 1)]
        if mode == "close":
            self.handlers["on_closed"]()
            return
        if mode == "error":
            raise RuntimeError("fake capture error")
        control = FakeControl(self)
        while not self.stopped.is_set():
            self.handlers["on_frame_arrived"](FakeFrame(8, 16), control)
            time.sleep(0.005)
        self.handlers["on_closed"]()


class ScreenshotRestartTest(unittest.TestCase):
    def setUp(self):
        FakeWindowsCapture.instances = []
        self._saved = sys.modules.get("wc_cuda")
        sys.modules["wc_cuda"] = types.SimpleNamespace(WindowsCapture=FakeWindowsCapture)
        self._saved_interval = stc.RESTART_INTERVAL
        stc.RESTART_INTERVAL = 0.01

    def tearDown(self):
        stc.RESTART_INTERVAL = self._saved_interval
        if self._saved is None:
            del sys.modules["wc_cuda"]
        else:
            sys.modules["wc_cuda"] = self._saved

    def make_thread(self):
        return stc.ScreenshotThreadWCCUDA(fps=60, frame_width=16, frame_height=8, monitor_index=0,
                                          window_name=None, device=torch.device("cpu"))

    def test_reopens_capture_after_session_closes(self):
        FakeWindowsCapture.plan = ["close", "ok"]
        t = self.make_thread()
        t.start()
        try:
            frame = t.get_frame()
            self.assertEqual(tuple(frame.shape), (3, 8, 16))
            self.assertEqual(len(FakeWindowsCapture.instances), 2)
        finally:
            t.stop()
        self.assertFalse(t.is_alive())

    def test_reopens_capture_after_error(self):
        FakeWindowsCapture.plan = ["error", "ok"]
        t = self.make_thread()
        t.start()
        try:
            frame = t.get_frame()
            self.assertEqual(tuple(frame.shape), (3, 8, 16))
        finally:
            t.stop()

    def test_stop_ends_thread_without_restart(self):
        FakeWindowsCapture.plan = ["ok"]
        t = self.make_thread()
        t.start()
        t.get_frame()
        t.stop()
        self.assertFalse(t.is_alive())
        self.assertEqual(len(FakeWindowsCapture.instances), 1)


if __name__ == "__main__":
    unittest.main()
