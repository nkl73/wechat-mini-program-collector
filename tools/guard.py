"""Window identification, safety guards, frame stability and progress measurement.

Guards are deliberately strict: any doubt -> stop, never grind on.
"""
import ctypes, ctypes.wintypes as w, hashlib, os, time
from ctypes import windll, byref

import mss
import win32gui
import numpy as np
from PIL import Image

user32 = windll.user32
try:
    windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

MINIMIZED_MARK = -32000


class GuardError(Exception):
    pass


# ---------------------------------------------------------------- windows
def enum_windows():
    out = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            r = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True
        w_, h_ = r[2] - r[0], r[3] - r[1]
        if w_ <= 0 or h_ <= 0:
            return True
        out.append({"hwnd": hwnd,
                    "title": win32gui.GetWindowText(hwnd),
                    "class": win32gui.GetClassName(hwnd),
                    "rect": list(r),
                    "size": [w_, h_],
                    "minimized": r[0] <= MINIMIZED_MARK})
        return True

    win32gui.EnumWindows(cb, None)
    return out


def find_candidates(class_name="Chrome_WidgetWin_0", title_contains=None, min_size=(200, 200)):
    res = []
    for win in enum_windows():
        if win["class"] != class_name:
            continue
        if win["minimized"]:
            continue
        if win["size"][0] < min_size[0] or win["size"][1] < min_size[1]:
            continue
        if title_contains and title_contains not in win["title"]:
            continue
        res.append(win)
    return res


def ancestors(hwnd):
    chain, h = [], hwnd
    for _ in range(8):
        if not h:
            break
        chain.append(h)
        h = user32.GetParent(h)
    return chain


def is_occluded(hwnd, rect, samples=7):
    """True if some other window covers a sample point inside the target."""
    l, t, r, b = rect
    pts = []
    for i in range(1, samples + 1):
        fy = i / (samples + 1.0)
        pts.append((int(l + (r - l) * 0.5), int(t + (b - t) * fy)))
    bad = []
    for (px, py) in pts:
        p = w.POINT(px, py)
        top = user32.WindowFromPoint(p)
        if top and hwnd not in ancestors(top):
            bad.append({"point": [px, py], "top_hwnd": top,
                        "top_title": win32gui.GetWindowText(top),
                        "top_class": win32gui.GetClassName(top)})
    return bad


def check_target(hwnd, expected_size=None, require_foreground=True, do_occlusion=True):
    """Raise GuardError on any problem. Returns a dict of observed facts."""
    facts = {"hwnd": hwnd}
    if not win32gui.IsWindow(hwnd):
        raise GuardError("target window no longer exists")
    if not win32gui.IsWindowVisible(hwnd):
        raise GuardError("target window is not visible")
    r = win32gui.GetWindowRect(hwnd)
    size = [r[2] - r[0], r[3] - r[1]]
    facts["rect"] = list(r)
    facts["size"] = size
    if r[0] <= MINIMIZED_MARK:
        raise GuardError("target window is minimized")
    if expected_size and list(expected_size) != size:
        raise GuardError(f"window size changed {expected_size} -> {size}")
    fg = user32.GetForegroundWindow()
    facts["foreground_hwnd"] = fg
    facts["foreground_title"] = win32gui.GetWindowText(fg)
    if require_foreground and fg != hwnd:
        raise GuardError(f"foreground lost: {fg} ({win32gui.GetWindowText(fg)})")
    if do_occlusion:
        bad = is_occluded(hwnd, r)
        facts["occlusion"] = bad
        if bad:
            raise GuardError(f"target occluded at {bad[0]['point']} by {bad[0]['top_class']}")
    return facts


def focus_once(hwnd):
    try:
        win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
    except Exception:
        pass
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    return user32.GetForegroundWindow() == hwnd


# ---------------------------------------------------------------- capture
def grab(hwnd, out_path):
    r = win32gui.GetWindowRect(hwnd)
    box = {"left": r[0], "top": r[1], "width": r[2] - r[0], "height": r[3] - r[1]}
    with mss.mss() as sct:
        img = sct.grab(box)
        mss.tools.to_png(img.rgb, img.size, output=out_path)
    return {"box": box, "file": out_path, "size": img.size}


def region_hash(path, frac, cache=None):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    box = (int(frac[0] * W), int(frac[1] * H), int(frac[2] * W), int(frac[3] * H))
    c = im.crop(box)
    h = hashlib.md5(np.asarray(c).tobytes()).hexdigest()
    if cache is not None:
        cache[path] = c
    return h, c


def wait_stable(hwnd, out_dir, tag, frac, attempts=4, interval=0.55):
    """Take shots until two consecutive region hashes match (or attempts run out)."""
    prev, last, last_size = None, None, None
    for i in range(attempts):
        p = os.path.join(out_dir, f"{tag}_stable{i}.png")
        check_target(hwnd)
        meta = grab(hwnd, p)
        check_target(hwnd)
        h, _ = region_hash(p, frac)
        last_size = meta["size"]
        if h == prev:
            return {"file": p, "hash": h, "stable": True, "tries": i + 1, "size": list(meta["size"])}
        prev, last = h, p
        time.sleep(interval)
    return {"file": last, "hash": prev, "stable": False, "tries": attempts, "size": list(last_size)}


def measure_shift(img_a, img_b, max_shift=400):
    """Row-profile correlation. Returns px the content moved UP (positive = up)."""
    na = np.asarray(img_a.convert("L"), dtype=np.int16).mean(axis=1)
    nb = np.asarray(img_b.convert("L"), dtype=np.int16).mean(axis=1)
    na = na - na.mean()
    nb = nb - nb.mean()
    best_s, best = 0, -2.0
    lim = min(max_shift, len(na) // 2)
    for s in range(-lim, lim + 1):
        if s >= 0:
            v1, v2 = na[s:], nb[:len(nb) - s]
        else:
            v1, v2 = na[:len(na) + s], nb[-s:]
        if len(v1) < 30:
            continue
        d1, d2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if d1 == 0 or d2 == 0:
            continue
        sc = float(np.dot(v1, v2) / (d1 * d2))
        if sc > best:
            best, best_s = sc, s
    return best_s, round(best, 4)


# ---------------------------------------------------------------- ocr
def detect_ocr():
    """Report whatever local OCR is already usable. Never downloads anything."""
    found = {"available": [], "missing": []}
    try:
        import rapidocr_onnxruntime  # noqa
        found["available"].append("rapidocr-onnxruntime")
    except Exception:
        found["missing"].append("rapidocr-onnxruntime (pip install rapidocr-onnxruntime)")
    try:
        import pytesseract  # noqa
        found["available"].append("pytesseract(module)")
    except Exception:
        found["missing"].append("pytesseract (pip install pytesseract)")
    from shutil import which
    if which("tesseract"):
        found["available"].append("tesseract.exe binary")
    else:
        found["missing"].append("tesseract.exe binary (not on PATH)")
    try:
        import winsdk.windows.media.ocr  # noqa
        found["available"].append("windows-media-ocr")
    except Exception:
        found["missing"].append("winsdk (pip install winsdk)")
    found["any"] = bool(found["available"])
    return found
