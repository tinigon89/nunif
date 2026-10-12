# CLAUDE.md — ghi chú cho fork nunif của tinigon89

Đọc thêm `AGENTS.md` của upstream (ruff, mypy, quy ước code). File này chỉ ghi những gì riêng của fork và máy này.

## Bố cục thư mục

- `E:\nunif-dev` là thư mục gốc **và** là git repo. Không có clone lồng trong `windows_package/nunif` nữa.
- Python đóng gói: `windows_package\python\python.exe` (Python 3.12 embeddable). File `windows_package\python\python312._pth` trỏ `..\..` nên import mã nguồn từ gốc.
- `windows_package\setenv.bat` đã sửa `NUNIF_DIR=%ROOT_DIR%..` và được đánh dấu `git update-index --skip-worktree`, không đưa vào commit.
- Model nằm ở `iw3\pretrained_models\hub\checkpoints`. Config GUI ở `tmp\iw3-desktop.cfg`. Không liệt kê hai thư mục này (xem AGENTS.md).
- Chạy lệnh bằng Python đóng gói từ thư mục gốc, ví dụ:
  `windows_package\python\python.exe -m iw3.desktop.gui`

## Nhánh git

| Nhánh  | Vai trò | Remote |
|--------|---------|--------|
| `dev`    | bản sao sạch của upstream, **không commit lên đây** | `origin/dev`, `upstream/dev` |
| `dev-jk` | dev + code riêng, dùng hằng ngày | `origin/dev-jk` |

- `origin` = fork https://github.com/tinigon89/nunif, `upstream` = nagadomi/nunif. Credential helper của repo là `gh auth git-credential`, tài khoản gh active là tinigon89.
- Đóng góp ngược: tạo nhánh từ `dev`, cherry-pick commit cần gửi, mở PR. Không gửi thẳng `dev-jk`.

### Quy trình lấy bản mới từ tác giả

```
git checkout dev
git pull --ff-only upstream dev
git push origin dev
git checkout dev-jk
git merge dev            # giải quyết xung đột nếu có, thường chỉ là định dạng
git push
```

Sau đó cài dependency **bằng pip**, không dùng `update.bat`:

```
windows_package\python\python.exe -m pip install --no-cache-dir --upgrade -r requirements-torch.txt
windows_package\python\python.exe -m pip install --no-cache-dir --upgrade -r requirements.txt
windows_package\python\python.exe -m pip install --no-cache-dir --upgrade -r requirements-gui.txt
```

**Cảnh báo:** `update.bat` chạy `git pull --ff` và nếu thất bại sẽ `git reset --hard`. Không bao giờ chạy nó khi đang merge dở hoặc có thay đổi chưa commit.

## Kiểm thử và lint

- Unit test desktop (unittest, không cần pytest):
  `windows_package\python\python.exe -m unittest tests.test_desktop_osd tests.test_desktop_click_through tests.test_desktop_viewer_keys tests.test_desktop_adjust_divergence tests.test_desktop_screenshot_restart tests.test_desktop_global_hotkeys`
- Lint: `windows_package\python\python.exe -m ruff check --fix <file>` rồi `ruff format <file>`. ruff đã cài trong Python đóng gói. `.flake8` cũ không còn là chuẩn.
- E2E Local Viewer: chạy `python -u -m iw3.desktop --local-viewer --screenshot wc_cuda ...` rồi đọc dòng `Estimated FPS` (phân cách bằng `\r`). Bơm sự kiện giả qua `wx.CallAfter` thay vì gửi phím chuột thật để không bấm nhầm vào desktop.
- Có thể chụp framebuffer của viewer bằng `glReadPixels` sau `SetCurrent` để kiểm tra OSD bằng mắt.

## Tính năng riêng trên dev-jk (iw3/desktop)

- `[` / `]` đổi 3D Strength 0.1 mỗi lần. Khi viewer đang chạy, hai phím này là **global hotkey** (RegisterHotKey), nhận ở mọi cửa sổ và bị lấy khỏi app khác cho tới khi đóng viewer. Mã phím theo layout US (VK_OEM_4 / VK_OEM_6).
- `C` bật tắt click-through, chỉ khi viewer có focus. Click trái, click phải, lăn chuột trong viewer được chuyển sang monitor đang capture qua SendInput (`iw3/desktop/click_through.py`). Gửi nhấn và nhả cùng lúc lúc nhả chuột, trả con trỏ và focus về viewer sau mỗi click. Tắt khi capture theo Window Name.
- OSD: `set_status` của cửa sổ viewer vẽ chữ đè lên khung hình 3 giây, mỗi mắt một lần (SBS hai nửa, TB trên dưới, anaglyph một lần). Viewer tự vẽ lại khung cuối khi OSD xuất hiện hoặc hết hạn.
- Capture tự mở lại: cả wc_cuda và wc_mp lặp lại khi phiên capture tự kết thúc (cắm thêm màn hình làm Windows Graphics Capture đóng phiên). Trước đây lỗi `RuntimeError: thread is dead`.
- Khi đổi divergence từ viewer, GUI đồng bộ ô 3D Strength qua `args.state["on_divergence_changed"]`.

## Hiệu năng đã đo trên máy này (RTX 4090, màn 4K 120 Hz)

- Dùng `wc_cuda`. wc_mp chỉ 27 đến 35 fps vì copy CPU 35 ms mỗi khung 4K.
- Any_V2_S 10 ms, Any_B 9.6 ms, Any_V2_N_B 8.7 ms, Distill_Any_S 7.3 ms, VDA_Stream_S 14 ms, ZoeD_Any_N 24 ms, Any_V3_Mono 22 ms và pipeline chỉ 26 đến 28 fps dù hạ độ phân giải. Model Base chạy gần bằng Small ở độ phân giải 392.
- Local Viewer đạt 59 fps với torch 2.13 trở lên. Với torch 2.7.1 trước đây bị kẹt 45 fps do `SwapBuffers` chờ vsync giữ GIL.
- Hạ độ phân giải màn hình, giảm Depth Resolution, tắt Edge Fix, đổi stereo method đều không tăng FPS đáng kể. Không gợi ý những cách đó.
- torch.compile cần `windows_package\torch_compile\install_python_dev.bat` vì Python embeddable thiếu `Python.h`. Lợi ích thấp với V2_S.
- Virtual Desktop Streamer chạy nền và mã hóa 4K làm FPS tụt khoảng 15. Khi đó đặt Streaming FPS 48 cho phim 24 fps.

## Người dùng

- Trao đổi bằng tiếng Việt. Chỉ dùng iw3-desktop (Local Viewer, Full SBS, Pico 4 qua Virtual Desktop).
- Khi sửa tính năng: thiết kế ngắn trong chat, chờ đồng ý, viết test trước, mỗi việc một commit trên `dev-jk`, push sau khi commit.
