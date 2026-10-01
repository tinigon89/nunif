"""Forward mouse clicks from the Local Viewer window to the captured monitor.

Coordinate pipeline:
  window pixel -> image (0..1, letterbox removed) -> source (0..1, stereo half and padding removed)
  -> monitor pixel -> SendInput absolute coordinate (0..65535 over the virtual desktop)

The pure functions have no wx/win32 dependency so they can be unit-tested anywhere.
"""
import sys

LAYOUT_SBS = "sbs"    # left/right halves (Full SBS, Half SBS, cross-eyed, RGBD)
LAYOUT_TB = "tb"      # top/bottom halves
LAYOUT_MONO = "mono"  # single image (anaglyph)

# Win32 MOUSEINPUT flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

BUTTON_FLAGS = {
    ("left", True): MOUSEEVENTF_LEFTDOWN,
    ("left", False): MOUSEEVENTF_LEFTUP,
    ("right", True): MOUSEEVENTF_RIGHTDOWN,
    ("right", False): MOUSEEVENTF_RIGHTUP,
}


def view_to_image(x, y, view_size, image_size):
    """Window pixel -> image coords in [0, 1]. Mirrors GLCanvas.draw() (aspect-fit, centered).
    Returns None when the point falls in the letterbox/pillarbox area."""
    W, H = view_size
    tex_w, tex_h = image_size
    if W <= 0 or H <= 0 or tex_w <= 0 or tex_h <= 0:
        return None
    scale = min(W / tex_w, H / tex_h)
    draw_w = tex_w * scale
    draw_h = tex_h * scale
    x0 = (W - draw_w) / 2
    y0 = (H - draw_h) / 2
    u = (x - x0) / draw_w
    v = (y - y0) / draw_h
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return None
    return (u, v)


def _remove_centered_padding(u, v, cell_aspect, source_aspect):
    """The source is aspect-fit and centered inside the eye cell (symmetric padding, e.g. --pad).
    Returns (su, sv) or None when inside the padding."""
    if abs(cell_aspect - source_aspect) < 1e-6:
        return (u, v)
    if cell_aspect > source_aspect:
        # cell is wider than source: horizontal padding
        content = source_aspect / cell_aspect  # fraction of cell width used by the source
        pad = (1.0 - content) / 2
        su = (u - pad) / content
        sv = v
    else:
        content = cell_aspect / source_aspect
        pad = (1.0 - content) / 2
        su = u
        sv = (v - pad) / content
    eps = 1e-9
    if not (-eps <= su <= 1.0 + eps and -eps <= sv <= 1.0 + eps):
        return None
    return (min(max(su, 0.0), 1.0), min(max(sv, 0.0), 1.0))


def image_to_source(u, v, layout, image_size, source_aspect):
    """Image coords -> source (captured screen) coords in [0, 1], or None when inside padding."""
    img_w, img_h = image_size
    if layout == LAYOUT_SBS:
        cell_w, cell_h = img_w / 2, img_h
        u = (u * 2) % 1.0 if u < 1.0 else 1.0
    elif layout == LAYOUT_TB:
        cell_w, cell_h = img_w, img_h / 2
        v = (v * 2) % 1.0 if v < 1.0 else 1.0
    else:
        cell_w, cell_h = img_w, img_h
    return _remove_centered_padding(u, v, cell_w / cell_h, source_aspect)


def source_to_monitor(su, sv, monitor_rect):
    """Source coords -> physical pixel on the captured monitor. monitor_rect = (left, top, width, height)."""
    left, top, width, height = monitor_rect
    px = left + min(int(su * width), width - 1)
    py = top + min(int(sv * height), height - 1)
    return (px, py)


def to_absolute(px, py, virtual_rect):
    """Physical pixel -> SendInput absolute coordinate (0..65535) over the virtual desktop."""
    left, top, width, height = virtual_rect
    ax = int(round((px - left) * 65535 / max(width - 1, 1)))
    ay = int(round((py - top) * 65535 / max(height - 1, 1)))
    return (min(max(ax, 0), 65535), min(max(ay, 0), 65535))


def layout_from_args(args):
    if getattr(args, "tb", False) or getattr(args, "half_tb", False):
        return LAYOUT_TB
    if getattr(args, "anaglyph", None):
        return LAYOUT_MONO
    return LAYOUT_SBS


class MouseForwarder:
    """Maps viewer clicks to the captured monitor and injects them through `backend`."""

    def __init__(self, monitor_rect, layout, image_size, source_aspect, backend, enabled=True):
        self.monitor_rect = monitor_rect
        self.layout = layout
        self.image_size = image_size
        self.source_aspect = source_aspect
        self.backend = backend
        self.enabled = enabled

    def _target(self, x, y, view_size):
        uv = view_to_image(x, y, view_size, self.image_size)
        if uv is None:
            return None
        src = image_to_source(uv[0], uv[1], self.layout, self.image_size, self.source_aspect)
        if src is None:
            return None
        px, py = source_to_monitor(src[0], src[1], self.monitor_rect)
        return to_absolute(px, py, self.backend.virtual_screen_rect())

    def _inject(self, x, y, view_size, events):
        """events: list of (flags, wheel_delta) sent at the target point, then cursor/focus restored."""
        if not self.enabled:
            return False
        target = self._target(x, y, view_size)
        if target is None:
            return False
        cursor = self.backend.get_cursor_pos()
        move = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        for flags, wheel_delta in events:
            self.backend.send(target[0], target[1], move | flags, wheel_delta)
        self.backend.set_cursor_pos(*cursor)
        self.backend.restore_foreground()
        return True

    def click(self, x, y, view_size, button):
        """Full press+release at the same point. Sending both together keeps the target from
        seeing a cursor move between down and up, which would cancel the click."""
        down = BUTTON_FLAGS.get((button, True))
        up = BUTTON_FLAGS.get((button, False))
        if down is None or up is None:
            return False
        return self._inject(x, y, view_size, [(down, 0), (up, 0)])

    def wheel(self, x, y, view_size, delta):
        return self._inject(x, y, view_size, [(MOUSEEVENTF_WHEEL, int(delta))])


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_size_t

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("mi", _MOUSEINPUT)]

    INPUT_MOUSE = 0
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79

    class Win32MouseBackend:
        """Real input injection. `hwnd` is the viewer window that should keep keyboard focus."""

        def __init__(self, hwnd=None):
            self.hwnd = hwnd
            self.user32 = ctypes.windll.user32

        def virtual_screen_rect(self):
            m = self.user32.GetSystemMetrics
            return (m(SM_XVIRTUALSCREEN), m(SM_YVIRTUALSCREEN), m(SM_CXVIRTUALSCREEN), m(SM_CYVIRTUALSCREEN))

        def get_cursor_pos(self):
            pt = wintypes.POINT()
            self.user32.GetCursorPos(ctypes.byref(pt))
            return (pt.x, pt.y)

        def set_cursor_pos(self, x, y):
            self.user32.SetCursorPos(int(x), int(y))

        def send(self, ax, ay, flags, wheel_delta=0):
            inp = _INPUT(type=INPUT_MOUSE,
                         mi=_MOUSEINPUT(dx=ax, dy=ay, mouseData=ctypes.c_uint32(wheel_delta & 0xFFFFFFFF).value,
                                        dwFlags=flags, time=0, dwExtraInfo=0))
            self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

        def restore_foreground(self):
            if self.hwnd:
                # best effort; Windows may refuse when another process holds foreground rights
                self.user32.SetForegroundWindow(int(self.hwnd))

    def get_monitor_rect(monitor_index):
        """(left, top, width, height) of the monitor in the same order used by --monitor-index."""
        import win32api
        monitors = win32api.EnumDisplayMonitors()
        left, top, right, bottom = monitors[monitor_index][2]
        return (left, top, right - left, bottom - top)
else:
    Win32MouseBackend = None

    def get_monitor_rect(monitor_index):
        raise RuntimeError("click-through is only supported on Windows")
