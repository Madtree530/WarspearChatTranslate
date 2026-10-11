"""CPU regressions; no game, network, or visible windows required."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

import wptrans as w


class FakeOCR:
    def __init__(self):
        self.calls = 0
        self.text_rec = self.recognize

    def recognize(self, crops):
        return [("Ann: hello", 0.99) for _ in crops], 0.0

    def get_crop_img_list(self, arr, boxes):
        return [arr[10:40, 10:190] for _ in boxes]

    def __call__(self, arr, **kwargs):
        self.calls += 1
        box = [[10, 10], [190, 10], [190, 40], [10, 40]]
        if kwargs.get("use_rec") is False:
            return [box], [0.0]
        return [[box, "Ann: hello", 0.99]], [0.0]


class FakeCapture:
    def __init__(self):
        self.image = Image.new("RGB", (400, 300), "black")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def grab(self, region):
        class Shot:
            pass
        shot = Shot()
        shot.size = self.image.size
        shot.bgra = self.image.tobytes("raw", "BGRX")
        return shot


class OCRCacheTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeOCR()
        self.capture = FakeCapture()
        self.patches = [patch.object(w, "_get_ocr_engines", return_value=(self.engine, None)),
                        patch("mss.mss", return_value=self.capture)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        # Clear caches between independent screens, when present.
        for name in ("_chat_frame_cache", "_title_frame_cache"):
            cache = getattr(w, name, None)
            if cache is not None:
                cache.clear()

    def test_unchanged_chat_does_not_repeat_inference(self):
        first = w.ocr_lines((0, 0, 400, 300))
        second = w.ocr_lines((0, 0, 400, 300))
        self.assertEqual(first, ["Ann: hello"])
        self.assertEqual(second, first)
        self.assertEqual(self.engine.calls, 1)

    def test_single_pixel_change_triggers_inference(self):
        w.ocr_lines((0, 0, 400, 300))
        self.capture.image.putpixel((111, 123), (255, 255, 255))
        w.ocr_lines((0, 0, 400, 300))
        self.assertEqual(self.engine.calls, 2)

    def test_region_move_invalidates_cached_screen(self):
        w.ocr_lines((0, 0, 400, 300))
        w.ocr_lines((10, 0, 400, 300))
        self.assertEqual(self.engine.calls, 2)

    def test_unchanged_title_does_not_repeat_inference(self):
        first = w.ocr_all_texts((0, 0, 400, 300))
        self.assertEqual(w.ocr_all_texts((0, 0, 400, 300)), first)
        self.assertEqual(self.engine.calls, 1)

    def test_confirmation_can_force_an_independent_second_inference(self):
        first = w._ocr_chat_frame((0, 0, 400, 300))
        second = w._ocr_chat_frame((0, 0, 400, 300), force=True)
        self.assertEqual(second[0], ["Ann: hello"])
        self.assertNotEqual(first[2], second[2])
        self.assertEqual(self.engine.calls, 2)

    def test_idle_cache_refreshes_after_five_seconds(self):
        with patch.object(w.time, "monotonic", return_value=100.0):
            w.ocr_lines((0, 0, 400, 300))
        with patch.object(w.time, "monotonic", return_value=106.0):
            w.ocr_lines((0, 0, 400, 300))
        self.assertEqual(self.engine.calls, 2)


class EngineTests(unittest.TestCase):
    def test_ocr_sessions_do_not_create_machine_wide_thread_pools(self):
        ch, th = w._get_ocr_engines()
        self.assertEqual(ch.text_det.infer.session.get_session_options().intra_op_num_threads, 1)
        self.assertEqual(ch.text_rec.session.session.get_session_options().intra_op_num_threads, 1)

    def test_thai_recognizer_uses_thai_model(self):
        _, th = w._get_ocr_engines()
        self.assertIsNotNone(th)
        rec = getattr(th, "text_rec", th)
        self.assertEqual(os.path.normcase(rec.session.session._model_path),
                         os.path.normcase(w.TH_REC_ONNX))


class SmartPollingTests(unittest.TestCase):
    def make_app(self):
        # Geometry callbacks may persist during update(); isolate all config writes.
        config_dir = tempfile.TemporaryDirectory()
        self.addCleanup(config_dir.cleanup)
        config_patch = patch.object(w, "CFG", os.path.join(config_dir.name, "config.json"))
        config_patch.start()
        self.addCleanup(config_patch.stop)
        # Real Tk timers, hidden window; OCR alone is substituted.
        with patch.object(w, "load_cfg", return_value=(None, "320x200+0+0", {
                "smart_mode": False})), patch.object(w.App, "_persist"):
            app = w.App()
        app.withdraw()
        app.region = (0, 0, 400, 300)
        def close_app():
            for timer in app.tk.call("after", "info"):
                app.after_cancel(timer)
            app.on_close()
            if app._worker_thread is not None:
                app._worker_thread.join(0.5)
        self.addCleanup(close_app)
        return app

    def test_repeated_smart_toggle_does_not_accumulate_pollers(self):
        app = self.make_app()
        with patch.object(w.App, "_persist"):
            for _ in range(8):
                app.toggle_smart()
                app.toggle_smart()
            app.toggle_smart()
        smart_timers = [timer for timer in app.tk.call("after", "info")
                        if "_smart_tick" in str(app.tk.call("after", "info", timer))]
        self.assertEqual(len(smart_timers), 1)

    def test_smart_ocr_does_not_block_ui_thread(self):
        app = self.make_app()
        app.smart_mode = True
        def slow_ocr(region):
            time.sleep(0.3)
            return []
        with patch.object(w, "ocr_all_texts", side_effect=slow_ocr):
            start = time.perf_counter()
            app._smart_tick()
            elapsed = time.perf_counter() - start
            time.sleep(0.35)
        self.assertLess(elapsed, 0.15)

    def test_rapid_stop_start_keeps_one_ocr_worker(self):
        app = self.make_app()
        release = threading.Event()
        entered = threading.Event()
        active = [0, 0]
        lock = threading.Lock()
        def blocked_frame(*args, **kwargs):
            with lock:
                active[0] += 1
                active[1] = max(active)
            entered.set()
            release.wait(1)
            with lock:
                active[0] -= 1
            return [], 0, 1
        with patch.object(w, "_ocr_chat_frame", side_effect=blocked_frame), \
             patch.object(w, "ocr_lines", side_effect=lambda *a: blocked_frame()[0]):
            app.on_toggle(True)
            self.assertTrue(entered.wait(0.5))
            for _ in range(4):
                app.on_toggle(False)
                app.on_toggle(True)
            time.sleep(0.08)
            app.on_toggle(False)
            release.set()
            time.sleep(0.1)
        self.assertEqual(active[1], 1)

    def test_reused_frame_is_not_a_second_ocr_confirmation(self):
        app = self.make_app()
        app.POLL_MS = 10
        with patch.object(w, "_ocr_chat_frame", return_value=(["Ann: hello"], 1, 7)), \
             patch.object(w, "ocr_lines", return_value=["Ann: hello"]), \
             patch.object(w, "translate", return_value="Ann: 你好") as translate:
            app.on_toggle(True)
            deadline = time.monotonic() + 0.12
            while time.monotonic() < deadline:
                app.update()
                time.sleep(0.005)
            app.on_toggle(False)
            time.sleep(0.04)
            self.assertEqual(translate.call_count, 0)

    def test_restart_during_translation_retries_the_undelivered_row(self):
        app = self.make_app()
        app.POLL_MS = 10
        entered = threading.Event()
        release = threading.Event()
        serial = [0]
        def frame(*args, **kwargs):
            serial[0] += 1
            return ["Ann: hello"], 1, serial[0]
        calls = []
        def translate(line):
            calls.append(line)
            if len(calls) == 1:
                entered.set()
                release.wait(1)
            return "Ann: 你好"
        # This test checks retry state; UI delivery is covered by the real app smoke test.
        with patch.object(w, "_ocr_chat_frame", side_effect=frame), \
             patch.object(w, "translate", side_effect=translate), \
             patch.object(app, "after", return_value=None):
            app.on_toggle(True)
            self.assertTrue(entered.wait(0.5))
            app.on_toggle(False)
            app.on_toggle(True)
            release.set()
            deadline = time.monotonic() + 0.3
            while len(calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            app.on_toggle(False)
            time.sleep(0.03)
        self.assertEqual(calls, ["Ann: hello", "Ann: hello"])


if __name__ == "__main__":
    unittest.main()
