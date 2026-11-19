"""
Terminal Board — Window Mirror Engine
Enables dynamic discovery of running desktop application windows and real-time
visual capture into a responsive, floating preview with always-on-top,
resizing, pause/resume, and clean resource management.
"""

import os
import io
import time
import base64
import ctypes
from ctypes import wintypes
from typing import Dict, Any, List, Optional
import psutil
from PIL import Image
import win32gui
import win32ui
import win32con
import win32process

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9

def _attach_thread_desktop():
    """Ensure the calling thread is attached to the active user desktop."""
    try:
        hDesk = user32.OpenInputDesktop(0, False, 511)
        if hDesk:
            user32.SetThreadDesktop(hDesk)
            return hDesk
    except Exception:
        pass
    return None

def _detach_thread_desktop(hDesk):
    """Safely release the opened desktop handle."""
    if hDesk:
        try:
            user32.CloseDesktop(hDesk)
        except Exception:
            pass

def is_window_cloaked(hwnd: int) -> bool:
    """Check if window is cloaked by Windows DWM (e.g. virtual desktop / minimized store app)."""
    try:
        dwmapi = ctypes.windll.dwmapi
        cloaked = ctypes.c_int(0)
        hr = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_CLOAKED),
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked)
        )
        return hr == 0 and cloaked.value != 0
    except Exception:
        return False

def get_open_windows(exclude_self_pid: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Enumerate all eligible, top-level visible application windows.
    Excludes tooltips, hidden helper windows, and Terminal Board's own process.
    """
    hDesk = _attach_thread_desktop()
    windows = []
    current_pid = exclude_self_pid if exclude_self_pid else os.getpid()

    def enum_func(hwnd, lParam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if is_window_cloaked(hwnd):
            return True

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width < 120 or height < 80:
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

        if not title or title in ('Program Manager', 'Settings', 'Windows Shell Experience Host', 'Taskbar'):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        owning_pid = pid.value

        if owning_pid == current_pid:
            return True

        proc_name = 'Unknown'
        try:
            p = psutil.Process(owning_pid)
            proc_name = p.name()
        except Exception:
            pass

        windows.append({
            'hwnd': hwnd,
            'title': title,
            'process_name': proc_name,
            'pid': owning_pid,
            'width': width,
            'height': height
        })
        return True

    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        proc = WNDENUMPROC(enum_func)
        if hDesk:
            user32.EnumDesktopWindows(hDesk, proc, 0)
        else:
            win32gui.EnumWindows(lambda hwnd, _: enum_func(hwnd, 0), None)
    finally:
        _detach_thread_desktop(hDesk)

    windows.sort(key=lambda x: x['title'].lower())
    return windows

def capture_window_frame(hwnd: int, max_width: int = 800, quality: int = 70) -> Dict[str, Any]:
    """
    Capture live visual frame of a specified window handle.
    Returns JPEG base64 encoded image and dimensions.
    """
    hDesk = _attach_thread_desktop()

    if not user32.IsWindow(hwnd):
        _detach_thread_desktop(hDesk)
        return {'success': False, 'error': 'Target window handle no longer exists.'}

    hwndDC = None
    mfcDC = None
    saveDC = None
    saveBitMap = None

    try:
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top

        if w <= 0 or h <= 0:
            return {'success': False, 'error': 'Target window is minimized or has zero size.'}

        hwndDC = user32.GetWindowDC(hwnd)
        if not hwndDC:
            return {'success': False, 'error': 'Could not acquire target window Device Context.'}

        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(saveBitMap)

        # Try PrintWindow with PW_RENDERFULLCONTENT (2)
        pw_ok = user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
        if not pw_ok:
            pw_ok = user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)
        if not pw_ok:
            saveDC.BitBlt((0, 0), (w, h), mfcDC, (0, 0), win32con.SRCCOPY)

        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)

        orig_w, orig_h = img.size
        if orig_w > max_width:
            scale = max_width / float(orig_w)
            new_h = int(orig_h * scale)
            img = img.resize((max_width, new_h), Image.Resampling.BILINEAR)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        img_bytes = buf.getvalue()
        b64 = base64.b64encode(img_bytes).decode('ascii')

        return {
            'success': True,
            'hwnd': hwnd,
            'width': orig_w,
            'height': orig_h,
            'rendered_width': img.size[0],
            'rendered_height': img.size[1],
            'image_base64': f'data:image/jpeg;base64,{b64}',
            'timestamp': time.time()
        }
    except Exception as e:
        return {'success': False, 'error': f'Frame capture failed: {str(e)}'}
    finally:
        if saveBitMap:
            try:
                win32gui.DeleteObject(saveBitMap.GetHandle())
            except Exception:
                pass
        if saveDC:
            try:
                saveDC.DeleteDC()
            except Exception:
                pass
        if mfcDC:
            try:
                mfcDC.DeleteDC()
            except Exception:
                pass
        if hwndDC:
            try:
                user32.ReleaseDC(hwnd, hwndDC)
            except Exception:
                pass
        _detach_thread_desktop(hDesk)
