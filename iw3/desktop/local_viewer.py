import wx
from wx import glcanvas
from OpenGL import GL
import torch
import threading
import time
import sys
import os
from collections import deque
import ctypes


POLLING_INTERVAL = 1.0 / 240.0


class _CUDART:
    def __init__(self, device_id=0):
        torch_dir = os.path.dirname(torch.__file__)
        site_packages = os.path.dirname(torch_dir)
        candidates = [
            os.path.join(torch_dir, "lib"),
            os.path.join(site_packages, "nvidia", "cuda_runtime", "lib"),
            os.path.join(site_packages, "nvidia", "cu13", "lib"),
            os.path.join(site_packages, "nvidia", "cuda_runtime", "bin"),  # Windows
        ]
        cudart_path = None
        for lib_dir in candidates:
            if not os.path.exists(lib_dir):
                continue
            for f in os.listdir(lib_dir):
                if sys.platform == "win32":
                    if f.startswith("cudart64") and f.endswith(".dll"):
                        cudart_path = os.path.join(lib_dir, f)
                        break
                else:
                    if f.startswith("libcudart") and ".so" in f:
                        cudart_path = os.path.join(lib_dir, f)
                        break
            if cudart_path:
                break
        if not cudart_path:
            raise RuntimeError("Could not find cudart in torch/lib or nvidia/cuda_runtime/lib")

        try:
            if sys.platform == "win32":
                self.lib = ctypes.WinDLL(cudart_path)
            else:
                self.lib = ctypes.CDLL(cudart_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load {cudart_path}: {e}")

        # API Definitions
        self.lib.cudaSetDevice.argtypes = [ctypes.c_int]
        self.lib.cudaGraphicsGLRegisterBuffer.argtypes = [
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_uint
        ]
        self.lib.cudaGraphicsUnregisterResource.argtypes = [ctypes.c_void_p]
        self.lib.cudaGraphicsMapResources.argtypes = [
            ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p
        ]
        self.lib.cudaGraphicsUnmapResources.argtypes = [
            ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p
        ]
        self.lib.cudaGraphicsResourceGetMappedPointer.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
        ]
        self.lib.cudaMemcpy.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
        ]
        self.lib.cudaSetDevice(device_id)

    def register_buffer(self, pbo_id):
        resource = ctypes.c_void_p()
        # 1 = cudaGraphicsRegisterFlagsNone
        res = self.lib.cudaGraphicsGLRegisterBuffer(ctypes.byref(resource), pbo_id, 1)
        if res != 0:
            raise RuntimeError(f"cudaGraphicsGLRegisterBuffer failed: {res}")
        return resource

    def unregister_resource(self, resource):
        self.lib.cudaGraphicsUnregisterResource(resource)

    def memcpy_d2d(self, dst_ptr, src_ptr, size):
        # 3 = cudaMemcpyDeviceToDevice
        res = self.lib.cudaMemcpy(dst_ptr, src_ptr, size, 3)
        if res != 0:
            raise RuntimeError(f"cudaMemcpy failed: {res}")

    def map_resource(self, resource):
        res = self.lib.cudaGraphicsMapResources(1, ctypes.byref(resource), None)
        if res != 0:
            raise RuntimeError(f"cudaGraphicsMapResources failed: {res}")

        ptr = ctypes.c_void_p()
        size = ctypes.c_size_t()
        res = self.lib.cudaGraphicsResourceGetMappedPointer(ctypes.byref(ptr), ctypes.byref(size), resource)
        if res != 0:
            self.lib.cudaGraphicsUnmapResources(1, ctypes.byref(resource), None)
            raise RuntimeError(f"cudaGraphicsResourceGetMappedPointer failed: {res}")
        return ptr.value

    def unmap_resource(self, resource):
        self.lib.cudaGraphicsUnmapResources(1, ctypes.byref(resource), None)


class GLCanvas(glcanvas.GLCanvas):
    def __init__(self, parent, width, height,
                 use_cuda=False, device_id=0,
                 uncap_fps=False, polling_interval=POLLING_INTERVAL,
                 mouse_forwarder=None, stereo_layout="sbs"):
        attribs = [
            glcanvas.WX_GL_RGBA,
            glcanvas.WX_GL_DOUBLEBUFFER,
        ]
        super().__init__(parent, attribList=attribs, size=(width, height))
        self.context = glcanvas.GLContext(self)
        self.initialized = False
        self.closed = False
        self.fps_counter = deque(maxlen=120)

        self.tex_id = None
        self.pbo = None
        self.tex_w = width
        self.tex_h = height
        self.frame = None

        self.use_cuda = use_cuda
        self.device_id = device_id
        self.polling_interval = polling_interval
        self.cuda_resource = None
        self._cudart = None
        # click_through.MouseForwarder or None; forwards clicks to the captured screen
        self.mouse_forwarder = mouse_forwarder
        # OSD state (see show_osd / draw_osd)
        self.stereo_layout = stereo_layout
        self.osd_tex_id = None
        self.osd_size = (0, 0)
        self.osd_pending = None   # text waiting to be uploaded as a texture
        self.osd_until = 0.0      # perf_counter time when the OSD hides
        self.osd_dirty = False    # redraw needed even without a new frame

        if uncap_fps:
            self.Bind(wx.EVT_IDLE, self.on_idle)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, self.on_resize)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        # Clicks are forwarded on button release so press+release reach the target as one click.
        self.Bind(wx.EVT_LEFT_UP, lambda e: self.on_mouse_click(e, "left"))
        self.Bind(wx.EVT_RIGHT_UP, lambda e: self.on_mouse_click(e, "right"))
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)

    def on_mouse_click(self, evt, button):
        if self.mouse_forwarder is not None:
            x, y = evt.GetPosition()
            self.mouse_forwarder.click(x, y, tuple(self.GetClientSize()), button)
        evt.Skip()

    def on_mouse_wheel(self, evt):
        if self.mouse_forwarder is not None:
            x, y = evt.GetPosition()
            self.mouse_forwarder.wheel(x, y, tuple(self.GetClientSize()), evt.GetWheelRotation())
        evt.Skip()

    def init_gl(self, evt=None):
        self.SetCurrent(self.context)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glClearColor(0, 0, 0, 1)
        GL.glViewport(0, 0, *self.GetClientSize())

        self.tex_id = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex_id)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB8, self.tex_w, self.tex_h, 0,
                        GL.GL_RGB, GL.GL_UNSIGNED_BYTE, None)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

        self.pbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_PIXEL_UNPACK_BUFFER, self.pbo)
        GL.glBufferData(GL.GL_PIXEL_UNPACK_BUFFER, self.tex_w * self.tex_h * 4, None, GL.GL_STREAM_DRAW)
        GL.glBindBuffer(GL.GL_PIXEL_UNPACK_BUFFER, 0)

        if self.use_cuda:
            try:
                self._cudart = _CUDART(self.device_id)
                self.cuda_resource = self._cudart.register_buffer(self.pbo)
            except Exception as e:
                print(f"Failed to initialize CUDA-GL Interop: {e}", file=sys.stderr)
                self.use_cuda = False

        self.initialized = True

    def delete_gl(self):
        if not self.initialized:
            return
        self.initialized = False
        self.SetCurrent(self.context)

        if self.cuda_resource:
            self._cudart.unregister_resource(self.cuda_resource)
            self.cuda_resource = None

        if self.tex_id:
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glDeleteTextures([self.tex_id])
            self.tex_id = None
        if self.osd_tex_id:
            GL.glDeleteTextures([self.osd_tex_id])
            self.osd_tex_id = None
        if self.pbo:
            GL.glBindBuffer(GL.GL_PIXEL_UNPACK_BUFFER, 0)
            GL.glDeleteBuffers(1, [self.pbo])
            self.pbo = None

    def destroy(self):
        self.closed = True
        self.delete_gl()

    def update_frame(self, frame):
        if self.closed:
            return
        if not self.initialized:
            # skip
            self.Refresh()
            return

        assert (
            frame.ndim == 3 and
            frame.shape[0] == 3 and
            frame.shape[1] == self.tex_h and
            frame.shape[2] == self.tex_w and
            frame.dtype == torch.float32
        )
        self.frame = frame
        self.Refresh()

    def set_tex(self):
        if self.frame is None:
            return False

        frame = self.frame
        c, h, w = frame.shape
        self.tex_w = w
        self.tex_h = h

        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glBindBuffer(GL.GL_PIXEL_UNPACK_BUFFER, self.pbo)

        if self.use_cuda and frame.is_cuda:
            # Ensure the frame is on the same device as the OpenGL PBO
            if frame.get_device() != self.device_id:
                frame = frame.to(f"cuda:{self.device_id}")

            # Zero-copy transfer using CUDA-GL Interop
            # 1. Convert to uint8 on GPU
            frame = frame.permute(1, 2, 0).contiguous()
            frame = (frame.clamp(0, 1) * 255).to(torch.uint8)

            # 2. Map PBO to CUDA and copy
            ptr = self._cudart.map_resource(self.cuda_resource)
            try:
                self._cudart.memcpy_d2d(ptr, frame.data_ptr(), frame.nbytes)
            finally:
                self._cudart.unmap_resource(self.cuda_resource)
        else:
            # Fallback to CPU transfer
            frame = frame.permute(1, 2, 0).contiguous()
            frame = (frame.clamp(0, 1) * 255).to(torch.uint8).detach().cpu().numpy()

            ptr = GL.glMapBuffer(GL.GL_PIXEL_UNPACK_BUFFER, GL.GL_WRITE_ONLY)
            ctypes.memmove(ptr, frame.ctypes.data, frame.nbytes)
            GL.glUnmapBuffer(GL.GL_PIXEL_UNPACK_BUFFER)

        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex_id)
        GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, w, h, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, None)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glBindBuffer(GL.GL_PIXEL_UNPACK_BUFFER, 0)

        self.frame = None
        self.fps_counter.append(time.perf_counter())

        return True

    def draw(self):
        W, H = self.GetClientSize()
        GL.glViewport(0, 0, W, H)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glOrtho(0, W, H, 0, -1, 1)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()

        GL.glEnable(GL.GL_TEXTURE_2D)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex_id)

        scale = min(W / self.tex_w, H / self.tex_h)
        draw_w = self.tex_w * scale
        draw_h = self.tex_h * scale
        x0 = (W - draw_w) / 2
        y0 = (H - draw_h) / 2
        x1 = x0 + draw_w
        y1 = y0 + draw_h

        self._draw_textured_quad(x0, y0, x1, y1)

        self.draw_osd((x0, y0, draw_w, draw_h))

        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glDisable(GL.GL_TEXTURE_2D)

    @staticmethod
    def _draw_textured_quad(x0, y0, x1, y1):
        GL.glBegin(GL.GL_QUADS)
        GL.glTexCoord2f(0, 0)
        GL.glVertex2f(x0, y0)
        GL.glTexCoord2f(1, 0)
        GL.glVertex2f(x1, y0)
        GL.glTexCoord2f(1, 1)
        GL.glVertex2f(x1, y1)
        GL.glTexCoord2f(0, 1)
        GL.glVertex2f(x0, y1)
        GL.glEnd()

    def show_osd(self, text):
        """Show `text` over the frame for OSD_DURATION seconds (main thread)."""
        self.osd_pending = text
        self.osd_until = time.perf_counter() + OSD_DURATION
        self.osd_dirty = True
        self.Refresh()
        # make sure it disappears even if no new frame arrives
        wx.CallLater(int(OSD_DURATION * 1000) + 50, self._on_osd_expire)

    def _on_osd_expire(self):
        if not self.closed and time.perf_counter() >= self.osd_until:
            self.osd_dirty = True
            self.Refresh()

    def _upload_osd_texture(self, text):
        rgba, w, h = render_osd_image(text)
        if self.osd_tex_id is None:
            self.osd_tex_id = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.osd_tex_id)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        else:
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.osd_tex_id)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, rgba)
        self.osd_size = (w, h)

    def draw_osd(self, draw_rect):
        """Draw the OSD text once per eye cell. Called from draw() with the GL context current."""
        self.osd_dirty = False
        if self.osd_pending is not None:
            text, self.osd_pending = self.osd_pending, None
            try:
                self._upload_osd_texture(text)
            except Exception as e:  # noqa: BLE001
                print(f"OSD render failed: {e!r}", file=sys.stderr)
                self.osd_until = 0.0
        if self.osd_tex_id is None or time.perf_counter() >= self.osd_until:
            return
        w, h = self.osd_size
        if w <= 0 or h <= 0:
            return
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.osd_tex_id)
        for qx, qy, qw, qh in osd_quads(draw_rect, self.stereo_layout, w / h):
            self._draw_textured_quad(qx, qy, qx + qw, qy + qh)
        GL.glDisable(GL.GL_BLEND)

    def on_idle(self, evt):
        if self.closed:
            return
        if not self.initialized:
            return
        if not self.render():
            if self.polling_interval > 0.0:
                time.sleep(self.polling_interval)
        evt.RequestMore()

    def on_paint(self, evt):
        if self.closed:
            return
        if not self.initialized:
            self.init_gl()
        self.render()

    def render(self):
        self.SetCurrent(self.context)
        new_frame = self.set_tex()
        # redraw the last frame when the OSD changed, even without a new frame
        if new_frame or (self.osd_dirty and self.initialized and self.frame is None and self.tex_id):
            self.draw()
            self.SwapBuffers()
            return new_frame
        return False

    def on_resize(self, evt):
        if self.closed:
            return
        if self.initialized:
            self.SetCurrent(self.context)
            w, h = self.GetClientSize()
            GL.glViewport(0, 0, max(1, w), max(1, h))
        evt.Skip()
        self.Refresh()

    def get_fps(self):
        if self.closed:
            return 0.0

        diff = []
        prev = None
        for t in self.fps_counter:
            if prev is not None:
                diff.append(t - prev)
            prev = t
        if diff:
            fps = 1.0 / (sum(diff) / len(diff))
        else:
            fps = 0.0
        return fps


WINDOW_TITLE = "iw3-desktop: Local Viewer"
DIVERGENCE_STEP = 0.1

# On-screen display (OSD): short status text drawn over the frame, once per eye
OSD_DURATION = 3.0        # seconds
OSD_REL_HEIGHT = 0.06     # box height relative to the eye cell height
OSD_REL_TOP = 0.04        # top margin relative to the eye cell height
OSD_MAX_REL_WIDTH = 0.9   # box width cap relative to the eye cell width
OSD_FONT_PX = 40
OSD_PADDING_PX = 14


def osd_quads(draw_rect, layout, text_aspect):
    """Where to draw the OSD box. draw_rect=(x0, y0, w, h) is the on-screen rect of the whole
    frame; layout is "sbs" / "tb" / "mono" (see click_through); text_aspect = width / height
    of the text image. Returns one (x, y, w, h) per eye cell at the same relative position, so
    the text appears at zero disparity in a headset."""
    x0, y0, w, h = draw_rect
    if layout == "sbs":
        cells = [(x0, y0, w / 2, h), (x0 + w / 2, y0, w / 2, h)]
    elif layout == "tb":
        cells = [(x0, y0, w, h / 2), (x0, y0 + h / 2, w, h / 2)]
    else:
        cells = [(x0, y0, w, h)]
    quads = []
    for cx, cy, cw, ch in cells:
        qh = ch * OSD_REL_HEIGHT
        qw = qh * text_aspect
        if qw > cw * OSD_MAX_REL_WIDTH:
            qw = cw * OSD_MAX_REL_WIDTH
            qh = qw / text_aspect
        qx = cx + (cw - qw) / 2
        qy = cy + ch * OSD_REL_TOP
        quads.append((qx, qy, qw, qh))
    return quads


def render_osd_image(text, font_px=OSD_FONT_PX, padding=OSD_PADDING_PX):
    """Render `text` with wx into an RGBA byte buffer: white text on a translucent dark
    rounded box. Returns (rgba_bytes, width, height). Must run on the wx main thread."""
    import numpy as np

    font = wx.Font(wx.FontInfo(wx.Size(0, font_px)).Bold())
    measure = wx.MemoryDC(wx.Bitmap(1, 1))
    measure.SetFont(font)
    tw, th = measure.GetTextExtent(text)
    measure.SelectObject(wx.NullBitmap)

    w, h = int(tw + padding * 2), int(th + padding * 2)
    bmp = wx.Bitmap(w, h, 32)
    bmp.UseAlpha(True)
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 0)))
    dc.Clear()
    gc = wx.GraphicsContext.Create(dc)
    gc.SetPen(wx.TRANSPARENT_PEN)
    gc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 170)))
    gc.DrawRoundedRectangle(0, 0, w, h, padding)
    gc.SetFont(font, wx.Colour(255, 255, 255, 255))
    gc.DrawText(text, padding, padding)
    dc.SelectObject(wx.NullBitmap)

    img = bmp.ConvertToImage()
    rgb = np.frombuffer(bytes(img.GetData()), dtype=np.uint8).reshape(h, w, 3)
    if img.HasAlpha():
        alpha = np.frombuffer(bytes(img.GetAlpha()), dtype=np.uint8).reshape(h, w, 1)
    else:
        alpha = np.full((h, w, 1), 255, dtype=np.uint8)
    rgba = np.concatenate([rgb, alpha], axis=2)
    return rgba.tobytes(), w, h


def divergence_delta_for_key(ch):
    """Map a typed character to a 3D Strength (divergence) change. `]` up, `[` down, else None."""
    if ch == "]":
        return DIVERGENCE_STEP
    if ch == "[":
        return -DIVERGENCE_STEP
    return None


CLICK_THROUGH_TOGGLE_KEY = "C"


class LocalViewerWindow(wx.Frame):
    def __init__(self, width, height, size=(960, 540),
                 use_cuda=False, device_id=0,
                 uncap_fps=False, polling_interval=POLLING_INTERVAL,
                 on_adjust_divergence=None, mouse_forwarder=None, stereo_layout="sbs"):
        super().__init__(None, title=WINDOW_TITLE,
                         size=size, style=wx.DEFAULT_FRAME_STYLE | wx.CLIP_CHILDREN)
        self.mouse_forwarder = mouse_forwarder
        if mouse_forwarder is not None and hasattr(mouse_forwarder.backend, "hwnd"):
            # let the forwarder give keyboard focus back to this window after each click
            mouse_forwarder.backend.hwnd = self.GetHandle()
        self.canvas = GLCanvas(self, width=width, height=height,
                               use_cuda=use_cuda, device_id=device_id,
                               uncap_fps=uncap_fps, polling_interval=polling_interval,
                               mouse_forwarder=mouse_forwarder, stereo_layout=stereo_layout)
        # callable(delta) -> new divergence value, or None when adjustment is not supported
        self.on_adjust_divergence = on_adjust_divergence
        self.status = {}  # title segments, e.g. {"3D Strength": "1.2", "Click-through": "OFF"}

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char)

    def set_status(self, key, value):
        self.status[key] = value
        parts = [WINDOW_TITLE] + [f"{k} {v}" for k, v in self.status.items()]
        self.SetTitle(" | ".join(parts))
        if not self.canvas.closed:
            self.canvas.show_osd(f"{key} {value}")

    def toggle_fullscreen(self):
        is_full = self.IsFullScreen()
        self.ShowFullScreen(not is_full, style=wx.FULLSCREEN_ALL)

    def escape_fullscreen(self):
        self.ShowFullScreen(False, style=wx.FULLSCREEN_ALL)

    def adjust_divergence(self, delta):
        if self.on_adjust_divergence is None:
            return False
        value = self.on_adjust_divergence(delta)
        if value is not None:
            self.set_status("3D Strength", f"{value:.1f}")
        return True

    def toggle_click_through(self):
        if self.mouse_forwarder is None:
            return False
        self.mouse_forwarder.enabled = not self.mouse_forwarder.enabled
        self.set_status("Click-through", "ON" if self.mouse_forwarder.enabled else "OFF")
        return True

    def on_char(self, evt):
        code = evt.GetKeyCode()
        unicode_key = evt.GetUnicodeKey()
        ch = chr(unicode_key) if unicode_key else ""
        delta = divergence_delta_for_key(ch)
        if code == wx.WXK_ESCAPE and self.IsFullScreen():
            self.toggle_fullscreen()
        elif code == wx.WXK_F11:
            self.toggle_fullscreen()
        elif delta is not None and self.adjust_divergence(delta):
            pass
        elif ch.upper() == CLICK_THROUGH_TOGGLE_KEY and self.toggle_click_through():
            pass
        else:
            evt.Skip()

    def update_frame(self, frame):
        if not self.canvas.closed:
            self.canvas.update_frame(frame)

    def get_fps(self):
        return self.canvas.get_fps()

    def on_close(self, evt):
        self.canvas.destroy()
        evt.Skip()

    def is_closed(self):
        return self.canvas.closed


class LocalViewer():
    def __init__(self, lock, width, height,
                 use_cuda=False, device_id=0,
                 uncap_fps=False, polling_interval=POLLING_INTERVAL,
                 on_adjust_divergence=None, mouse_forwarder=None, stereo_layout="sbs",
                 **_unsupported_kwargs):
        self.width = width
        self.height = height
        self.lock = lock
        self.op_lock = threading.RLock()
        self.window = None
        self.initialized = False
        self.last_frame_time = 0
        self.use_cuda = use_cuda
        self.device_id = device_id
        self.uncap_fps = uncap_fps
        self.polling_interval = polling_interval
        self.on_adjust_divergence = on_adjust_divergence
        self.mouse_forwarder = mouse_forwarder
        self.stereo_layout = stereo_layout

    def stop(self):
        with self.op_lock:
            if self.window is not None:
                window = self.window
                self.window = None
                if not window.is_closed():
                    wx.CallAfter(window.Close)

    def _start(self):
        with self.op_lock:
            if self.window is None:
                self.window = LocalViewerWindow(width=self.width, height=self.height,
                                                use_cuda=self.use_cuda, device_id=self.device_id,
                                                uncap_fps=self.uncap_fps, polling_interval=self.polling_interval,
                                                on_adjust_divergence=self.on_adjust_divergence,
                                                mouse_forwarder=self.mouse_forwarder,
                                                stereo_layout=self.stereo_layout)
                self.window.Show()
                self.initialized = True

    def start(self):
        """
        Standard start method for use when wx.App is already running on main thread.
        This is used on Linux with wx.Yield() pattern, and on Windows when called from worker thread.
        """
        if not wx.GetApp():
            raise RuntimeError("wx.App is not initialized")
        wx.CallAfter(self._start)

    def set_frame_data(self, frame_data):
        with self.op_lock:
            frame, frame_time = frame_data
            if self.window is not None and self.last_frame_time < frame_time:
                wx.CallAfter(self.window.update_frame, frame)
                self.last_frame_time = frame_time

    def get_fps(self):
        if self.window is not None:
            return self.window.get_fps()
        else:
            return 0.0

    def is_closed(self):
        with self.op_lock:
            if self.window:
                return self.window.is_closed()
            else:
                if self.initialized:
                    return True
                else:
                    return False


def run_local_viewer_cli(worker_callback):
    """
    Platform-aware entry point for running local viewer from CLI.

    Handles platform-specific requirements:
    - Linux: Calls worker directly, which creates wx.App and uses wx.Yield() pattern
    - Windows: Creates wx.App on main thread, runs worker in background thread

    Args:
        worker_callback: Function to run (the processing loop). Should call iw3_desktop_main.
                        On Windows, should NOT create wx.App (init_wxapp=False)
                        On Linux, SHOULD create wx.App (init_wxapp=True)

    This function blocks until the GUI is closed.
    """
    if sys.platform != "win32":
        # Linux: Original wx.Yield() pattern works fine
        # Worker will create wx.App and use wx.Yield() to pump events
        return worker_callback()

    # Windows: Need wx event loop on main thread
    app = wx.App()

    # Create a hidden dummy frame to keep the app alive
    # Without this, app.MainLoop() exits immediately before worker can create the real window
    dummy_frame = wx.Frame(None)
    dummy_frame.Hide()

    # Track worker state
    worker_started = threading.Event()
    worker_exception = [None]

    def worker_target():
        try:
            worker_started.set()
            worker_callback()
        except Exception as e:
            worker_exception[0] = e
            print(f"LocalViewer worker error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
        finally:
            # Exit the event loop when worker finishes
            wx.CallAfter(app.ExitMainLoop)

    worker_thread = threading.Thread(target=worker_target, daemon=False)

    def start_worker():
        worker_thread.start()
        if not worker_started.wait(timeout=5.0):
            print("Warning: Worker thread did not start within 5 seconds", file=sys.stderr)

    # Start worker after event loop begins
    wx.CallAfter(start_worker)

    # Run event loop on main thread (Windows requirement)
    app.MainLoop()

    # Cleanup
    dummy_frame.Destroy()

    # Wait for worker to finish
    if worker_thread and worker_thread.is_alive():
        worker_thread.join(timeout=5.0)

    # Re-raise any exception from worker
    if worker_exception[0]:
        raise worker_exception[0]


def _test():
    import argparse
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--cuda", action="store_true", help="use cudaMemcpy")
    parser.add_argument("--size", choices=["hd", "4k", "8k"], default="4k", help="frame size")
    parser.add_argument("--fps", type=int, default=2000, help="frame interval")
    args = parser.parse_args()

    # 4K(SBS)
    # on RTX 3070 Ti Linux,
    #    with --cuda: 293FPS
    # without --cuda:  44FPS
    if args.size == "hd":
        W, H = (1920 * 2, 1080)
    elif args.size == "4k":
        W, H = (3840 * 2, 2160)
    elif args.size == "8k":
        W, H = (7680 * 2, 4320)

    def main():
        lock = threading.RLock()
        server = LocalViewer(lock, width=W, height=H, use_cuda=args.cuda, uncap_fps=True, polling_interval=0)
        server.start()
        time.sleep(2)
        frames = torch.rand(4, 3, H, W).cuda()
        torch.cuda.synchronize()
        time.sleep(1)
        for i in range(300):
            if server.is_closed():
                break
            frame = frames[i % frames.shape[0]]
            server.set_frame_data((frame, time.perf_counter()))
            time.sleep(1 / args.fps)

        print(f"{W}x{H}, {round(server.get_fps(), 2)}FPS")
        print("CTRL+C to exit")
        server.stop()

    def start():
        threading.Thread(target=main).start()

    app = wx.App()
    frame = wx.Frame(None)  # noqa
    wx.CallAfter(start)
    app.MainLoop()


if __name__ == '__main__':
    _test()
