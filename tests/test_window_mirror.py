import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.core.window_mirror import (
    is_window_cloaked,
    get_open_windows,
    capture_window_frame
)
from backend.api import SYSFIXApi

class TestWindowMirror(unittest.TestCase):
    def test_window_enumeration(self):
        """Verify window enumeration returns structured list of top-level windows."""
        windows = get_open_windows()
        self.assertIsInstance(windows, list)
        for w in windows:
            self.assertIn("hwnd", w)
            self.assertIn("title", w)
            self.assertIn("process_name", w)
            self.assertIn("pid", w)
            self.assertIn("width", w)
            self.assertIn("height", w)
            self.assertIsInstance(w["hwnd"], int)
            self.assertGreater(w["width"], 0)
            self.assertGreater(w["height"], 0)

    def test_invalid_window_capture(self):
        """Verify capture gracefully handles nonexistent window handle."""
        res = capture_window_frame(hwnd=999999999)
        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("success", True))
        self.assertIn("error", res)

    def test_cloaked_check(self):
        """Verify cloaked check handles invalid handle safely without crashing."""
        res = is_window_cloaked(0)
        self.assertIsInstance(res, bool)

    def test_api_window_mirror_methods(self):
        """Verify SYSFIXApi integrates window mirror capabilities."""
        api = SYSFIXApi()
        win_list = api.get_window_mirror_list()
        self.assertIsInstance(win_list, list)

        if win_list:
            target = win_list[0]
            frame = api.capture_window_mirror_frame(target["hwnd"], max_width=400, quality=50)
            self.assertIsInstance(frame, dict)
            if frame.get("success"):
                self.assertIn("image_base64", frame)
                self.assertTrue(frame["image_base64"].startswith("data:image/jpeg;base64,"))
                self.assertLessEqual(frame.get("rendered_width", 9999), 400)

if __name__ == "__main__":
    unittest.main()
