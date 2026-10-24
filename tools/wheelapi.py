"""Unified wheel interface. The only place where "notches" are converted to raw delta.

Verified facts (2026-10-24, WeChatAppEx mini program + Chromium windows):
  * pyautogui.scroll(n) passes n straight into mouse_event dwData.
  * One wheel notch = WHEEL_DELTA = 120 raw units.
  * n < 120 is silently ignored by the target. That was the original bug.
  * mouse_event returns void: failures never surface as an error.

Rule for callers: always talk in NOTCHES. scroll_raw exists only for
experiments and normalises to a whole multiple of 120 on the way in.
"""
import ctypes, ctypes.wintypes as w, time
from ctypes import windll, byref

WHEEL_DELTA = 120
MOUSEEVENTF_WHEEL = 0x0800
INPUT_MOUSE = 0

user32 = windll.user32
try:
    windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 40)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("u", _U)]


def notches_to_delta(notches):
    """notches -> raw delta, always a whole multiple of 120."""
    return int(round(float(notches))) * WHEEL_DELTA


def delta_to_notches(delta):
    return float(delta) / WHEEL_DELTA


class WheelError(Exception):
    pass


def _send(x, y, delta, api, gap_ms):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.12)
    p = w.POINT()
    user32.GetCursorPos(byref(p))
    last = []
    for _ in range(max(1, int(round(abs(delta) / WHEEL_DELTA)))):
        step = WHEEL_DELTA if delta > 0 else -WHEEL_DELTA
        if api == "sendinput":
            inp = INPUT(type=INPUT_MOUSE,
                        u=_U(mi=MOUSEINPUT(dx=0, dy=0, mouseData=ctypes.c_uint32(step & 0xFFFFFFFF).value,
                                           dwFlags=MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=0)))
            user32.SendInput(1, byref(inp), ctypes.sizeof(INPUT))
        else:
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, step, 0)
        last.append(ctypes.get_last_error())
        time.sleep(gap_ms / 1000.0)
    return {"cursor": [p.x, p.y], "api": api, "delta": delta,
            "notches": delta_to_notches(delta), "lasterr": last[:3]}


def scroll(x, y, notches=1, gap_ms=70, api="mouse_event"):
    """Preferred entry point. `notches` > 0 = up, < 0 = down."""
    if notches == 0:
        raise WheelError("notches must be non-zero")
    return _send(x, y, notches_to_delta(notches), api, gap_ms)


def scroll_raw(x, y, delta, gap_ms=70, api="mouse_event"):
    """Low-level. delta is normalised to whole notches before sending."""
    if delta == 0:
        raise WheelError("delta must be non-zero")
    notches = int(round(float(delta) / WHEEL_DELTA))
    if notches == 0:
        notches = 1 if delta > 0 else -1
    return _send(x, y, notches * WHEEL_DELTA, api, gap_ms)
