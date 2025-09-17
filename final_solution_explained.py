#!/usr/bin/env python3
"""
TaskbarHider Pro (Windows 11)

Goals:
- Fully hide the Windows system taskbar (Explorer) and block mouse-triggered reveal
- Keep third-party taskbar managers (e.g., YASB Reborn) working — hide ONLY Explorer's taskbar
- On Win key press, temporarily show the taskbar for 10 seconds (press Win again to hide immediately)
- Restore everything safely on exit (Alt+`)
- Minimal dependencies (ctypes only), no admin required (recommended but not mandatory)

Notes:
- Work-area expansion (reclaiming bottom space) is applied only when no third‑party taskbar managers are detected.
- Uses continuous enforcement thread to prevent re-appearance.
- Reactivates blocking after each hide via a short Show→Hide cycle.
"""

import ctypes
from ctypes import wintypes
import threading
import time
import subprocess
import sys


# --- Windows API setup ---
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32


# Constants
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SW_SHOWNORMAL = 1

SPI_SETWORKAREA = 0x002F
SPI_GETWORKAREA = 0x0030
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

WM_SETTINGCHANGE = 0x001A
HWND_BROADCAST = 0xFFFF

VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_MENU = 0x12  # Alt
VK_OEM_3 = 0xC0  # backtick `

SM_CXSCREEN = 0
SM_CYSCREEN = 1

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

# AppBar (taskbar) constants
ABM_GETSTATE = 0x00000004
ABM_SETSTATE = 0x0000000A
ABS_AUTOHIDE = 0x0000001
ABS_ALWAYSONTOP = 0x0000002


# Structures
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", RECT),
        ("lParam", wintypes.LPARAM),
    ]


# Function prototypes
FindWindowW = user32.FindWindowW
FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
FindWindowW.restype = wintypes.HWND

FindWindowExW = user32.FindWindowExW
FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
FindWindowExW.restype = wintypes.HWND

GetClassNameW = user32.GetClassNameW
GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GetClassNameW.restype = ctypes.c_int

ShowWindow = user32.ShowWindow
ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
ShowWindow.restype = wintypes.BOOL

IsWindowVisible = user32.IsWindowVisible
IsWindowVisible.argtypes = [wintypes.HWND]
IsWindowVisible.restype = wintypes.BOOL

SetWindowPos = user32.SetWindowPos
SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
SetWindowPos.restype = wintypes.BOOL

GetWindowRect = user32.GetWindowRect
GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
GetWindowRect.restype = wintypes.BOOL

GetSystemMetrics = user32.GetSystemMetrics
GetSystemMetrics.argtypes = [ctypes.c_int]
GetSystemMetrics.restype = ctypes.c_int

SystemParametersInfoW = user32.SystemParametersInfoW
SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
SystemParametersInfoW.restype = wintypes.BOOL

SHAppBarMessage = shell32.SHAppBarMessage
SHAppBarMessage.argtypes = [wintypes.UINT, ctypes.POINTER(APPBARDATA)]
SHAppBarMessage.restype = wintypes.UINT

GetAsyncKeyState = user32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [ctypes.c_int]
GetAsyncKeyState.restype = wintypes.SHORT

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
QueryFullProcessImageNameW.restype = wintypes.BOOL

SendMessageW = user32.SendMessageW
SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
# Compat: wintypes.LRESULT may be missing on some Python versions
try:
    LRESULT = wintypes.LRESULT  # type: ignore[attr-defined]
except AttributeError:
    LRESULT = ctypes.c_ssize_t
SendMessageW.restype = LRESULT


# Access rights
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


# Globals
explorer_taskbars = []   # list[HWND]
third_party_taskbars = []  # list[HWND]
has_taskbar_managers = False
desired_hidden = True
panel_temp_visible = False
show_deadline_ms = 0
original_work_area = None
exit_event = threading.Event()


def log(msg: str):
    print(msg, flush=True)


def current_millis() -> int:
    return int(time.time() * 1000)


def is_key_pressed(vk: int) -> bool:
    return (GetAsyncKeyState(vk) & 0x8000) != 0


def detect_taskbar_managers() -> bool:
    """Detect if known third-party taskbar managers are running using tasklist."""
    try:
        result = subprocess.run(["tasklist"], capture_output=True, text=True, creationflags=0x08000000)
        output = result.stdout.lower()
        managers = [
            "yasb.exe", "taskbarx.exe", "explorerpatcher.exe", "startallback.exe",
            "translucent-tb.exe", "rainmeter.exe", "displayfusion.exe",
        ]
        return any(m in output for m in managers)
    except Exception:
        return False


def get_window_process_path(hwnd: int) -> str | None:
    pid = wintypes.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    hproc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not hproc:
        return None
    try:
        buf_len = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(buf_len.value)
        if QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(buf_len)):
            return buf.value
        return None
    finally:
        CloseHandle(hproc)


def enumerate_taskbars():
    """Populate explorer_taskbars and third_party_taskbars lists."""
    explorer_taskbars.clear()
    third_party_taskbars.clear()

    classes = ["Shell_TrayWnd", "Shell_SecondaryTrayWnd"]
    for cls in classes:
        hwnd = None
        # Primary: FindWindowW returns only one, but we'll also loop via FindWindowEx for completeness
        if cls == "Shell_TrayWnd":
            primary = FindWindowW(cls, None)
            if primary:
                path = (get_window_process_path(primary) or "").lower()
                if path.endswith("\\explorer.exe") or path.endswith("/explorer.exe"):
                    explorer_taskbars.append(primary)
                else:
                    third_party_taskbars.append(primary)

        # Enumerate all windows of this class using FindWindowExW
        while True:
            hwnd = FindWindowExW(None, hwnd, cls, None)
            if not hwnd:
                break
            if hwnd in explorer_taskbars or hwnd in third_party_taskbars:
                continue
            path = (get_window_process_path(hwnd) or "").lower()
            if path.endswith("\\explorer.exe") or path.endswith("/explorer.exe"):
                explorer_taskbars.append(hwnd)
            else:
                third_party_taskbars.append(hwnd)


def save_work_area():
    global original_work_area
    rect = RECT()
    if SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        original_work_area = (rect.left, rect.top, rect.right, rect.bottom)
        log(f"📥 Saved work area: {original_work_area}")


def set_fullscreen_work_area():
    w = GetSystemMetrics(SM_CXSCREEN)
    h = GetSystemMetrics(SM_CYSCREEN)
    full = RECT(0, 0, w, h)
    if SystemParametersInfoW(SPI_SETWORKAREA, 0, ctypes.byref(full), SPIF_UPDATEINIFILE | SPIF_SENDCHANGE):
        SendMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, SPI_SETWORKAREA, 0)
        log(f"🖥️ Work area set to full screen: {w}x{h}")


def restore_work_area():
    if not original_work_area:
        return
    l, t, r, b = original_work_area
    rect = RECT(l, t, r, b)
    if SystemParametersInfoW(SPI_SETWORKAREA, 0, ctypes.byref(rect), SPIF_UPDATEINIFILE | SPIF_SENDCHANGE):
        SendMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, SPI_SETWORKAREA, 0)
        log("↩️ Work area restored")


def force_hide_hwnd(hwnd: int):
    # 1) Hide via ShowWindow
    ShowWindow(hwnd, SW_HIDE)
    # 2) Move far off-screen as a second line of defense
    SetWindowPos(hwnd, None, -10000, -10000, 1, 1, SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)


def hide_system_taskbars(reactivate: bool = True):
    for hwnd in explorer_taskbars:
        # Short training cycle to suppress hover-trigger
        if reactivate:
            for _ in range(2):
                ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                time.sleep(0.05)
                ShowWindow(hwnd, SW_HIDE)
                time.sleep(0.05)
        force_hide_hwnd(hwnd)
    log(f"🕶️ Hidden system taskbars: {len(explorer_taskbars)}")


def show_system_taskbars():
    for hwnd in explorer_taskbars:
        ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    log("👁️ System taskbars shown")


def close_start_menu():
    try:
        # ESC tends to close the Start menu reliably without toggling Win again
        user32.keybd_event(0x1B, 0, 0, 0)   # ESC down
        time.sleep(0.02)
        user32.keybd_event(0x1B, 0, 2, 0)   # ESC up
    except Exception:
        pass


def get_primary_taskbar_hwnd() -> int | None:
    """Return primary system taskbar HWND (Explorer) if possible, else any Shell_TrayWnd."""
    if explorer_taskbars:
        return explorer_taskbars[0]
    hwnd = FindWindowW("Shell_TrayWnd", None)
    return hwnd if hwnd else None


def set_taskbar_autohide(enable: bool):
    """Enable/disable taskbar autohide via SHAppBarMessage.
    Applies to primary taskbar window; silently returns on failure.
    """
    hwnd = get_primary_taskbar_hwnd()
    if not hwnd:
        return
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    abd.hWnd = hwnd
    abd.lParam = ABS_AUTOHIDE if enable else ABS_ALWAYSONTOP
    SHAppBarMessage(ABM_SETSTATE, ctypes.byref(abd))


def enforcement_worker():
    # Keep system taskbars hidden while desired_hidden is True
    while not exit_event.is_set():
        if desired_hidden and not panel_temp_visible:
            for hwnd in explorer_taskbars:
                # If visible again, hide
                if IsWindowVisible(hwnd):
                    force_hide_hwnd(hwnd)
        time.sleep(0.1)


def main():
    global has_taskbar_managers, desired_hidden, panel_temp_visible, show_deadline_ms

    print("🎯 TaskbarHider Pro — Windows 11", flush=True)
    print("   Win: show/hide temporarily (10s). Alt+` to exit.", flush=True)
    print("   YASB-aware: only Explorer taskbar is hidden.", flush=True)
    print("—" * 60, flush=True)

    # Detect managers and enumerate windows
    has_taskbar_managers = detect_taskbar_managers()
    enumerate_taskbars()
    print(f"Detected managers: {has_taskbar_managers}")
    print(f"Explorer taskbars: {len(explorer_taskbars)}, third-party: {len(third_party_taskbars)}")

    if not explorer_taskbars:
        # Be forgiving: continue running and print guidance. Watchdog will keep checking visibility,
        # and user can press Win/Alt+` controls. This avoids Exit Code 1 on setups where Explorer's
        # Shell_TrayWnd is temporarily unavailable or fully replaced by third-party bars.
        print("⚠️ No system taskbars (Explorer) found. If you use a third-party bar (e.g., YASB), this is expected.\n"
              "   The app will still run without changing the work area.")

    # Work area: save original; apply fullscreen only when no third-party managers
    save_work_area()

    desired_hidden = True
    panel_temp_visible = False
    show_deadline_ms = 0

    # Ensure taskbar autohide is ON for best space behavior
    set_taskbar_autohide(True)

    # Initial hide
    hide_system_taskbars(reactivate=True)
    if not has_taskbar_managers and not third_party_taskbars:
        set_fullscreen_work_area()

    # Start enforcement
    t = threading.Thread(target=enforcement_worker, daemon=True)
    t.start()

    # Main loop: key handling
    win_was_down = False
    alt_was_down = False

    try:
        while not exit_event.is_set():
            now = current_millis()

            # Alt+` → exit
            alt_down = is_key_pressed(VK_MENU)
            backtick_down = is_key_pressed(VK_OEM_3)
            if alt_down and backtick_down and not alt_was_down:
                print("⏹ Exit requested (Alt+`)")
                break
            alt_was_down = alt_down and backtick_down

            # Win press handling (edge-triggered)
            win_down = is_key_pressed(VK_LWIN) or is_key_pressed(VK_RWIN)
            if win_down and not win_was_down:
                # Toggle temp visibility
                if not panel_temp_visible:
                    # Show taskbar temporarily (10s)
                    panel_temp_visible = True
                    desired_hidden = False
                    show_system_taskbars()
                    if original_work_area and (not has_taskbar_managers and not third_party_taskbars):
                        restore_work_area()
                    show_deadline_ms = now + 10_000
                    time.sleep(0.12)  # small debounce
                else:
                    # Immediate hide if shown
                    close_start_menu()
                    desired_hidden = True
                    panel_temp_visible = False
                    hide_system_taskbars(reactivate=True)
                    if not has_taskbar_managers and not third_party_taskbars:
                        set_fullscreen_work_area()
                    time.sleep(0.12)

            win_was_down = win_down

            # Auto hide after timeout
            if panel_temp_visible and now >= show_deadline_ms:
                close_start_menu()
                desired_hidden = True
                panel_temp_visible = False
                hide_system_taskbars(reactivate=True)
                if not has_taskbar_managers and not third_party_taskbars:
                    set_fullscreen_work_area()

            time.sleep(0.02)

    except KeyboardInterrupt:
        pass
    finally:
        # Cleanup / restore
        exit_event.set()
        desired_hidden = False
        show_system_taskbars()
        restore_work_area()
        # Restore autohide to OFF (AlwaysOnTop state)
        set_taskbar_autohide(False)
        print("✅ Restored. Bye!")


if __name__ == "__main__":
    main()
