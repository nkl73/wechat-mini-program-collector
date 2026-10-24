"""Desktop capability layer: window, capture, wheel, click, input, back, guards.

Business-neutral. Every mutating call runs a pre-check; if the target window is
gone / minimized / resized / unfocused / occluded it raises GuardError and the
caller stops. Foreground is taken ONCE, never re-stolen in a loop.
"""
import os, sys, time, json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard
import wheelapi

OCR_AVAILABLE = bool(guard.detect_ocr().get("any"))


def ocr_lines(png):
    """Return OCR lines or None when no local OCR exists. Never guesses."""
    if not OCR_AVAILABLE:
        return None
    from wa_ocr import read
    return read(png)["lines"]


class Core:
    def __init__(self, hwnd, log=print):
        self.hwnd = hwnd
        self.size = None
        self.log = log
        r = self._rect()
        self.size = [r[2] - r[0], r[3] - r[1]]
        self.rect = list(r)

    # ---------------------------------------------------------- guards
    def _rect(self):
        import win32gui
        return win32gui.GetWindowRect(self.hwnd)

    def precheck(self, do_occlusion=True):
        self.rect = list(self._rect())
        return guard.check_target(self.hwnd, expected_size=self.size,
                                  require_foreground=True, do_occlusion=do_occlusion)

    def focus_once(self):
        ok = guard.focus_once(self.hwnd)
        if ok:
            self.rect = list(self._rect())
        return ok

    # ---------------------------------------------------------- capture
    def capture(self, out_dir, tag, frac=None, attempts=4):
        self.precheck()
        os.makedirs(out_dir, exist_ok=True)
        st = guard.wait_stable(self.hwnd, out_dir, tag, frac or (0.0, 0.0, 1.0, 1.0), attempts=attempts)
        if list(st["size"]) != list(self.size):
            raise guard.GuardError(f"screenshot size {st['size']} != window size {self.size}")
        self.precheck()
        if not st["stable"]:
            raise guard.GuardError("capture did not stabilize")
        st["ts"] = datetime.now().isoformat(timespec="seconds")
        return st

    def crop(self, png, frac, out_path):
        from PIL import Image
        im = Image.open(png).convert("RGB")
        W, H = im.size
        c = im.crop((int(frac[0] * W), int(frac[1] * H), int(frac[2] * W), int(frac[3] * H)))
        c.save(out_path)
        return out_path

    # ---------------------------------------------------------- input
    def scroll(self, notches, frac=(0.5, 0.5)):
        self.precheck()
        l, t, r, b = self.rect
        W, H = r - l, b - t
        x = int(l + W * frac[0])
        y = int(t + H * frac[1])
        res = wheelapi.scroll(x, y, notches=notches)
        self.log(f"    scroll notches={notches} delta={res['delta']} at ({x},{y}) err={res['lasterr'][:1]}")
        return res

    def click_frac(self, fx, fy):
        self.precheck()
        import pyautogui
        l, t, r, b = self.rect
        W, H = r - l, b - t
        x, y = int(l + W * fx), int(t + H * fy)
        pyautogui.moveTo(x, y, duration=0.2)
        self.precheck()
        pyautogui.click(x, y)
        self.log(f"    click frac=({fx},{fy}) -> ({x},{y})")
        return {"x": x, "y": y}

    def click_anchor(self, text, ocr_lines_):
        """Only usable with OCR; otherwise refuse instead of guessing."""
        if ocr_lines_ is None:
            raise guard.GuardError("click_anchor requires OCR; refusing to guess coordinates")
        for ln in ocr_lines_:
            if text in ln.get("text", ""):
                box = ln["box"]
                fx = ((box[0] + box[2]) / 2.0) / self.size[0]
                fy = ((box[1] + box[3]) / 2.0) / self.size[1]
                return self.click_frac(fx, fy)
        raise guard.GuardError(f"anchor text not found: {text!r}")

    def back(self, frac=(0.09, 0.055)):
        return self.click_frac(*frac)

    def input_text(self, text, frac):
        import pyautogui, pyperclip
        self.precheck()
        l, t, r, b = self.rect
        W, H = r - l, b - t
        self.click_frac(*frac)
        old = None
        try:
            old = pyperclip.paste()
            pyperclip.copy(text)
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "v")
        finally:
            if old is not None:
                try:
                    pyperclip.copy(old)
                except Exception:
                    pass
        return {"pasted_len": len(text)}
