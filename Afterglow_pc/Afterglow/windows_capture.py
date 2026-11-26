"""Capture the monitor under the focused fullscreen window."""

import ctypes as ct
from ctypes import wintypes as wt
import time
from uuid import UUID

from palette import HEIGHT, WIDTH


class MonitorInfo(ct.Structure):
    _fields_ = [("size", wt.DWORD), ("monitor", wt.RECT),
                ("work", wt.RECT), ("flags", wt.DWORD)]


class BitmapInfo(ct.Structure):
    _fields_ = [("size", wt.DWORD), ("width", wt.LONG), ("height", wt.LONG),
                ("planes", wt.WORD), ("bit_depth", wt.WORD),
                ("compression", wt.DWORD), ("image_size", wt.DWORD),
                ("x_resolution", wt.LONG), ("y_resolution", wt.LONG),
                ("colors_used", wt.DWORD), ("colors_important", wt.DWORD),
                ("color_table", wt.DWORD)]


user32 = ct.WinDLL("user32", use_last_error=True)
gdi32 = ct.WinDLL("gdi32", use_last_error=True)
dwmapi = ct.WinDLL("dwmapi", use_last_error=True)


def bind(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = arguments
    return function


get_foreground = bind(user32, "GetForegroundWindow", wt.HWND)
get_class = bind(user32, "GetClassNameW", ct.c_int, wt.HWND, wt.LPWSTR, ct.c_int)
is_minimized = bind(user32, "IsIconic", wt.BOOL, wt.HWND)
is_maximized = bind(user32, "IsZoomed", wt.BOOL, wt.HWND)
get_style = bind(user32, "GetWindowLongW", wt.LONG, wt.HWND, ct.c_int)
monitor_from_window = bind(user32, "MonitorFromWindow", wt.HMONITOR, wt.HWND, wt.DWORD)
monitor_info = bind(user32, "GetMonitorInfoW", wt.BOOL, wt.HMONITOR, ct.POINTER(MonitorInfo))
window_rect = bind(user32, "GetWindowRect", wt.BOOL, wt.HWND, ct.POINTER(wt.RECT))
dwm_attribute = bind(dwmapi, "DwmGetWindowAttribute", wt.LONG,
                     wt.HWND, wt.DWORD, ct.c_void_p, wt.DWORD)
get_dc = bind(user32, "GetDC", wt.HDC, wt.HWND)
release_dc = bind(user32, "ReleaseDC", ct.c_int, wt.HWND, wt.HDC)
create_dc = bind(gdi32, "CreateCompatibleDC", wt.HDC, wt.HDC)
delete_dc = bind(gdi32, "DeleteDC", wt.BOOL, wt.HDC)
create_bitmap = bind(gdi32, "CreateDIBSection", wt.HBITMAP,
                     wt.HDC, ct.POINTER(BitmapInfo), wt.UINT, ct.POINTER(ct.c_void_p),
                     wt.HANDLE, wt.DWORD)
select_object = bind(gdi32, "SelectObject", wt.HANDLE, wt.HDC, wt.HANDLE)
delete_object = bind(gdi32, "DeleteObject", wt.BOOL, wt.HANDLE)
stretch_mode = bind(gdi32, "SetStretchBltMode", ct.c_int, wt.HDC, ct.c_int)
stretch_blit = bind(gdi32, "StretchBlt", wt.BOOL,
                    wt.HDC, ct.c_int, ct.c_int, ct.c_int, ct.c_int,
                    wt.HDC, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.DWORD)
flush = bind(gdi32, "GdiFlush", wt.BOOL)

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
HALFTONE = 4
DESKTOP_WINDOWS = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                   "Windows.UI.Core.CoreWindow", "TaskSwitcherWnd", "MultitaskingViewFrame"}


def enable_dpi_awareness():
    set_dpi = bind(user32, "SetProcessDpiAwarenessContext", wt.BOOL, wt.HANDLE)
    set_dpi(ct.c_void_p(-4))  # Per-monitor v2, coordinates in physical pixels.


def fullscreen_window():
    window = get_foreground()
    if not window or is_minimized(window):
        return None
    name = ct.create_unicode_buffer(128)
    get_class(window, name, len(name))
    if name.value in DESKTOP_WINDOWS:
        return None
    cloaked = wt.DWORD()
    if dwm_attribute(window, DWMWA_CLOAKED, ct.byref(cloaked), ct.sizeof(cloaked)) == 0:
        if cloaked.value:
            return None
    monitor = MonitorInfo(size=ct.sizeof(MonitorInfo))
    handle = monitor_from_window(window, 0)
    if not handle or not monitor_info(handle, ct.byref(monitor)):
        return None
    frame = wt.RECT()
    if dwm_attribute(window, DWMWA_EXTENDED_FRAME_BOUNDS, ct.byref(frame), ct.sizeof(frame)):
        if not window_rect(window, ct.byref(frame)):
            return None
    screen = monitor.monitor
    edges = ("left", "top", "right", "bottom")
    if any(abs(getattr(frame, edge) - getattr(screen, edge)) > 2 for edge in edges):
        return None
    # A maximized normal window can cover the screen with an auto-hidden taskbar.
    if is_maximized(window) and get_style(window, -16) & 0x00C00000:  # WS_CAPTION
        return None
    return window, handle, screen


class GdiSampler:
    def __init__(self):
        self.dc = create_dc(None)
        self.bitmap = self.previous = None
        self.buffer = ct.c_void_p()
        if not self.dc:
            raise OSError("Windows could not open screen capture.")
        try:
            info = BitmapInfo(size=40, width=WIDTH, height=-HEIGHT, planes=1, bit_depth=32)
            self.bitmap = create_bitmap(self.dc, ct.byref(info), 0, ct.byref(self.buffer), None, 0)
            if not self.bitmap:
                raise OSError("Windows could not allocate screen capture.")
            self.previous = select_object(self.dc, self.bitmap)
            if not self.previous or self.previous == ct.c_void_p(-1).value:
                self.previous = None
                raise OSError("Windows could not initialize screen capture.")
            stretch_mode(self.dc, HALFTONE)
        except OSError:
            self.close()
            raise

    def close(self):
        if self.previous:
            select_object(self.dc, self.previous)
        if self.bitmap:
            delete_object(self.bitmap)
        delete_dc(self.dc)

    def read(self, bounds):
        screen_dc = get_dc(None)
        if not screen_dc:
            raise OSError("Windows could not read the desktop.")
        try:
            arguments = (self.dc, 0, 0, WIDTH, HEIGHT, screen_dc, bounds.left, bounds.top,
                         bounds.right - bounds.left, bounds.bottom - bounds.top)
            if not stretch_blit(*arguments, SRCCOPY | CAPTUREBLT):
                if not stretch_blit(*arguments, SRCCOPY):
                    raise OSError("GDI could not copy the desktop.")
            flush()
        finally:
            release_dc(None, screen_dc)
        bgra = ct.string_at(self.buffer, WIDTH * HEIGHT * 4)
        rgb = bytearray(WIDTH * HEIGHT * 3)
        rgb[::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[::4]
        return bytes(rgb)


# DXGI and D3D11 expose C-compatible COM interfaces. Method slots are from
# dxgi.h, dxgi1_2.h and d3d11.h, including inherited interface methods.
PTR = ct.c_void_p
UINT = wt.UINT
HRESULT = wt.LONG
OUT = ct.POINTER(PTR)
ENUM_ADAPTERS1, ENUM_OUTPUTS, OUTPUT_GET_DESC, DUPLICATE_OUTPUT = 12, 7, 7, 22
ACQUIRE_FRAME, RELEASE_FRAME = 8, 14
CREATE_TEXTURE2D, GET_TEXTURE_DESC, MAP, UNMAP, COPY_REGION = 5, 10, 14, 15, 46
DXGI_NOT_FOUND, DXGI_WAIT_TIMEOUT = 0x887A0002, 0x887A0027
BGRA8_UNORM = 87
ROTATE_90, ROTATE_180, ROTATE_270 = 2, 3, 4
SAMPLES = 3


def guid(value):
    return (ct.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)


FACTORY1 = guid("770aae78-f26f-4dba-a829-253c83d1b387")
OUTPUT1 = guid("00cddea8-939b-4b83-a340-a685226666cc")
TEXTURE2D = guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")


class OutputDesc(ct.Structure):
    _fields_ = [("name", wt.WCHAR * 32), ("bounds", wt.RECT), ("attached", wt.BOOL),
                ("rotation", UINT), ("monitor", wt.HMONITOR)]


class FrameInfo(ct.Structure):
    _fields_ = [("present_time", ct.c_int64), ("mouse_time", ct.c_int64),
                ("accumulated", UINT), ("coalesced", wt.BOOL), ("protected", wt.BOOL),
                ("pointer_position", wt.POINT), ("pointer_visible", wt.BOOL),
                ("metadata_size", UINT), ("pointer_shape_size", UINT)]


class TextureDesc(ct.Structure):
    _fields_ = [(name, UINT) for name in (
        "width", "height", "levels", "array_size", "format", "sample_count",
        "sample_quality", "usage", "bind_flags", "cpu_access", "misc_flags")]


class Box(ct.Structure):
    _fields_ = [(name, UINT) for name in ("left", "top", "front", "right", "bottom", "back")]


class MappedTexture(ct.Structure):
    _fields_ = [("data", PTR), ("pitch", UINT), ("depth_pitch", UINT)]


def check(result, operation):
    if result < 0:
        raise OSError(f"{operation} failed (0x{result & 0xffffffff:08x}).")


class ComPointer:
    def __init__(self):
        self.ptr = PTR()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def method(self, slot, result, *arguments):
        address = ct.cast(self.ptr, ct.POINTER(ct.POINTER(PTR)))[0][slot]
        return ct.WINFUNCTYPE(result, PTR, *arguments)(address)

    def close(self):
        if self.ptr:
            self.method(2, wt.ULONG)(self.ptr)
            self.ptr = PTR()

    def query(self, interface, result):
        check(self.method(0, HRESULT, PTR, OUT)(
            self.ptr, ct.byref(interface), ct.byref(result.ptr)), "QueryInterface")


def sample_positions(length, cells):
    count = cells * SAMPLES
    return [(2 * index + 1) * length // (2 * count) for index in range(count)]


def surface_cells(rotation):
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if rotation == ROTATE_90:
                yield y, WIDTH - 1 - x
            elif rotation == ROTATE_180:
                yield WIDTH - 1 - x, HEIGHT - 1 - y
            elif rotation == ROTATE_270:
                yield HEIGHT - 1 - y, x
            else:
                yield x, y


class DxgiSampler:
    def __init__(self, monitor):
        self.device, self.context = ComPointer(), ComPointer()
        self.duplicate, self.staging = ComPointer(), ComPointer()
        self.surface_size = None
        self.last = None
        self.owns_frame = False
        try:
            self.open_output(monitor)
        except (OSError, AttributeError):
            self.close()
            raise

    def close(self):
        if self.owns_frame:
            self.release_frame(self.duplicate.ptr)
            self.owns_frame = False
        for interface in (self.staging, self.duplicate, self.context, self.device):
            interface.close()

    def open_output(self, monitor):
        factory_dll = ct.WinDLL("dxgi")
        create_factory = bind(factory_dll, "CreateDXGIFactory1", HRESULT, PTR, OUT)
        with ComPointer() as factory:
            check(create_factory(ct.byref(FACTORY1), ct.byref(factory.ptr)), "CreateDXGIFactory1")
            enum_adapters = factory.method(ENUM_ADAPTERS1, HRESULT, UINT, OUT)
            adapter_index = 0
            while True:
                with ComPointer() as adapter:
                    result = enum_adapters(factory.ptr, adapter_index, ct.byref(adapter.ptr))
                    if result & 0xffffffff == DXGI_NOT_FOUND:
                        break
                    check(result, "EnumAdapters1")
                    if self.find_output(adapter, monitor):
                        return
                adapter_index += 1
        raise OSError("DXGI could not find the selected monitor.")

    def find_output(self, adapter, monitor):
        enum_outputs = adapter.method(ENUM_OUTPUTS, HRESULT, UINT, OUT)
        output_index = 0
        while True:
            with ComPointer() as output:
                result = enum_outputs(adapter.ptr, output_index, ct.byref(output.ptr))
                if result & 0xffffffff == DXGI_NOT_FOUND:
                    return False
                check(result, "EnumOutputs")
                desc = OutputDesc()
                check(output.method(OUTPUT_GET_DESC, HRESULT, ct.POINTER(OutputDesc))(
                    output.ptr, ct.byref(desc)), "IDXGIOutput.GetDesc")
                if desc.attached and desc.monitor == monitor:
                    self.rotation = desc.rotation
                    self.duplicate_output(adapter, output)
                    return True
            output_index += 1

    def duplicate_output(self, adapter, output):
        d3d = ct.WinDLL("d3d11")
        create_device = bind(d3d, "D3D11CreateDevice", HRESULT, PTR, UINT, wt.HMODULE,
                             UINT, PTR, UINT, UINT, OUT, PTR, OUT)
        with ComPointer() as output1:
            output.query(OUTPUT1, output1)
            # The device must belong to the same adapter as the monitor.
            check(create_device(adapter.ptr, 0, None, 0x20, None, 0, 7,
                                ct.byref(self.device.ptr), None, ct.byref(self.context.ptr)),
                  "D3D11CreateDevice")
            check(output1.method(DUPLICATE_OUTPUT, HRESULT, PTR, OUT)(
                output1.ptr, self.device.ptr, ct.byref(self.duplicate.ptr)), "DuplicateOutput")
        self.acquire = self.duplicate.method(ACQUIRE_FRAME, HRESULT, UINT,
                                             ct.POINTER(FrameInfo), OUT)
        self.release_frame = self.duplicate.method(RELEASE_FRAME, HRESULT)
        self.copy_region = self.context.method(COPY_REGION, None, PTR, UINT, UINT, UINT,
                                               UINT, PTR, UINT, ct.POINTER(Box))
        self.map = self.context.method(MAP, HRESULT, PTR, UINT, UINT, UINT,
                                       ct.POINTER(MappedTexture))
        self.unmap = self.context.method(UNMAP, None, PTR, UINT)

    def prepare_staging(self, width, height):
        rotated = self.rotation in (ROTATE_90, ROTATE_270)
        columns, rows = (HEIGHT, WIDTH) if rotated else (WIDTH, HEIGHT)
        # Copy several evenly spaced scanlines per output row on the GPU. Only
        # those scanlines cross to CPU memory, even for a 4K or 8K desktop.
        self.strips = [Box(0, y, 0, width, y + 1, 1) for y in sample_positions(height, rows)]
        offsets = [x * 4 for x in sample_positions(width, columns)]
        self.cells = [(tuple(offsets[x * SAMPLES:(x + 1) * SAMPLES]), y * SAMPLES)
                      for x, y in surface_cells(self.rotation)]
        staging = TextureDesc(width=width, height=len(self.strips), levels=1,
                              array_size=1, format=BGRA8_UNORM, sample_count=1,
                              usage=3, cpu_access=0x20000)  # STAGING, CPU_ACCESS_READ
        self.staging.close()
        check(self.device.method(CREATE_TEXTURE2D, HRESULT, ct.POINTER(TextureDesc), PTR, OUT)(
            self.device.ptr, ct.byref(staging), None, ct.byref(self.staging.ptr)),
            "CreateTexture2D")
        self.surface_size = width, height

    def read_texture(self, texture):
        desc = TextureDesc()
        texture.method(GET_TEXTURE_DESC, None, ct.POINTER(TextureDesc))(
            texture.ptr, ct.byref(desc))
        if desc.format != BGRA8_UNORM:
            raise OSError("DXGI returned an unexpected pixel format.")
        if self.surface_size != (desc.width, desc.height):
            self.prepare_staging(desc.width, desc.height)
        for row, strip in enumerate(self.strips):
            self.copy_region(self.context.ptr, self.staging.ptr, 0, 0, row, 0,
                             texture.ptr, 0, ct.byref(strip))
        mapped = MappedTexture()
        check(self.map(self.context.ptr, self.staging.ptr, 0, 1, 0, ct.byref(mapped)), "Map")
        try:
            return self.read_pixels(mapped)
        finally:
            self.unmap(self.context.ptr, self.staging.ptr, 0)

    def read_pixels(self, mapped):
        pixels = memoryview((ct.c_ubyte * (mapped.pitch * len(self.strips)))
                            .from_address(mapped.data)).cast("B")
        rgb = bytearray(WIDTH * HEIGHT * 3)
        count = SAMPLES * SAMPLES
        for index, (columns, first_row) in enumerate(self.cells):
            red = green = blue = 0
            for row in range(first_row, first_row + SAMPLES):
                start = mapped.pitch * row
                for column in columns:
                    offset = start + column
                    blue += pixels[offset]
                    green += pixels[offset + 1]
                    red += pixels[offset + 2]
            offset = index * 3
            rgb[offset] = (red + count // 2) // count
            rgb[offset + 1] = (green + count // 2) // count
            rgb[offset + 2] = (blue + count // 2) // count
        return bytes(rgb)

    def read(self):
        # Holding the acquired frame between polls lets DXGI coalesce updates.
        if self.owns_frame:
            self.owns_frame = False
            check(self.release_frame(self.duplicate.ptr), "ReleaseFrame")
        frame = FrameInfo()
        with ComPointer() as resource:
            result = self.acquire(self.duplicate.ptr, 0, ct.byref(frame), ct.byref(resource.ptr))
            if result & 0xffffffff == DXGI_WAIT_TIMEOUT:
                return self.last
            check(result, "AcquireNextFrame")
            self.owns_frame = True
            if frame.present_time or self.last is None:
                with ComPointer() as texture:
                    resource.query(TEXTURE2D, texture)
                    self.last = self.read_texture(texture)
        return self.last


class DesktopSampler:
    def __init__(self):
        self.gdi = None
        self.dxgi = None
        self.window = None
        self.display = None
        self.retry_after = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def reset(self):
        if self.dxgi is not None:
            self.dxgi.close()
        self.dxgi = self.window = self.display = None
        self.retry_after = 0

    def close(self):
        self.reset()
        if self.gdi is not None:
            self.gdi.close()
            self.gdi = None

    def sample(self):
        source = fullscreen_window()
        if source is None:
            self.reset()
            return "waiting", None
        window, monitor, bounds = source
        display = (monitor, bounds.left, bounds.top, bounds.right, bounds.bottom)
        if display != self.display:
            self.reset()
            self.display = display
        if window != self.window and self.dxgi is not None:
            self.dxgi.last = None
        self.window = window
        raw = None
        try:
            if self.dxgi is None and time.monotonic() >= self.retry_after:
                self.dxgi = DxgiSampler(monitor)
            if self.dxgi is not None:
                raw = self.dxgi.read()
        except (OSError, AttributeError):
            if self.dxgi is not None:
                self.dxgi.close()
                self.dxgi = None
            self.retry_after = time.monotonic() + 3

        if raw is None:
            if self.gdi is None:
                self.gdi = GdiSampler()
            raw = self.gdi.read(bounds)
        if get_foreground() != window:
            return "waiting", None
        return "live", raw
