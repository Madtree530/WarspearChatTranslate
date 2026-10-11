"""System announcements and OCR language-selection regressions."""
import os
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

import wptrans as w


def row(text, score, y=10, x=10, right=900):
    return y, x, text, score, x, right


class ChatFilterTests(unittest.TestCase):
    def test_system_announcement_is_not_a_player_chat(self):
        for text in ("信息: Biatiger已将[+7长靴]强化到[+8长靴]!",
                     "信 息 ： Biatiger已将[+7长靴]强化到[+8长靴]!",
                     "信息: Biatiger +7 helmet +8 helmet",
                     "系统：Player 已上线", "公告：维护提醒"):
            with self.subTest(text=text):
                self.assertFalse(w.is_chat_shaped(text))

    def test_system_announcement_never_reaches_translation(self):
        with patch.object(w, "bing_translate", side_effect=AssertionError("System message sent to Bing")):
            for text in ("信息: Biatiger +7 helmet +8 helmet",
                         "信息: Biatiger已强化【表情】", "系统: hello world"):
                with self.subTest(text=text):
                    self.assertEqual(w.translate(text), "")

    def test_chinese_announcement_is_not_replaced_by_thai_garbage(self):
        ch = [row("信息：Biatiger已将[+7长靴]强化到[+8长靴]！", 0.96)]
        th = [row("1อE:BiatigerEK7A XHTBlKp]3E1E[8 H1EHBUKp]!", 0.58)]
        merged = w._merge_line_boxes(w._prefer_thai_merge(ch, th))
        self.assertEqual(w.filter_dense_chat_rows(merged), [])

    def test_high_confidence_chinese_cannot_be_overridden_by_false_thai(self):
        ch = [row("公告：维护提醒", 0.97)]
        th = [row("Ann: ขาย", 0.99)]
        merged = w._merge_line_boxes(w._prefer_thai_merge(ch, th))
        self.assertEqual(w.filter_dense_chat_rows(merged), [])

    def test_thai_in_misread_speaker_does_not_make_the_body_thai(self):
        ch = [row("Ann: hello world", 0.96)]
        th = [row("1อE: hello world", 0.83)]
        self.assertEqual(w._prefer_thai_merge(ch, th), ch)

    def test_low_confidence_thai_noise_does_not_replace_real_chat(self):
        ch = [row("Daggerz: tyyy", 0.98)]
        th = [row("Daggerz: ขาย", 0.59)]
        self.assertEqual(w._prefer_thai_merge(ch, th), ch)

    def test_good_thai_body_replaces_latin_misrecognition(self):
        ch = [row("Yojo: uaJASw", 0.75)]
        th = [row("Yojo: ของคราฟ", 0.99)]
        self.assertEqual(w._prefer_thai_merge(ch, th), th)

    def test_good_thai_body_is_retained_when_primary_ocr_misses_it(self):
        th = [row("Yojo: ของคราฟ", 0.99)]
        self.assertEqual(w._prefer_thai_merge([], th), th)

    def test_missing_primary_does_not_admit_thai_garbage(self):
        th = [row("1อE: Biatiger[+7KTF0A]E1E[+8TFnA!", 0.58)]
        self.assertEqual(w._prefer_thai_merge([], th), [])

    def test_regular_player_chat_is_still_accepted(self):
        for text in ("Ann: hello world", "Ann: 信息是什么？", "สมชาย: ขาย"):
            self.assertTrue(w.is_chat_shaped(text))

    def test_player_between_announcements_keeps_its_position_in_chat_cluster(self):
        texts = ["Ann: hello", "Bob: hello", "Cat: hello", "信息：强化公告",
                 "信息：强化公告", "Kamal: tpt pm", "信息：强化公告",
                 "信息：强化公告", "Dag: hello", "Eel: hello", "Finn: hello"]
        ch = [row(text, 0.99, y=10 + 20 * i) for i, text in enumerate(texts)]
        merged = w._merge_line_boxes(w._prefer_thai_merge(ch, []))
        self.assertEqual(w.filter_dense_chat_rows(merged),
                         ["Ann: hello", "Bob: hello", "Cat: hello", "Kamal: tpt pm",
                          "Dag: hello", "Eel: hello", "Finn: hello"])

    def test_thai_row_matches_its_own_box_and_not_its_neighbor(self):
        ch = [row("Ann: hello", 0.99, x=10, right=200),
              row("Yojo: uaJASw", 0.75, x=300, right=700)]
        th = [row("Yojo: ของคราฟ", 0.99, x=300, right=700)]
        self.assertEqual(w._prefer_thai_merge(ch, th), [ch[0], th[0]])


class ScreenshotOCRTests(unittest.TestCase):
    def test_supplied_system_message_screenshot_has_no_chat_candidates(self):
        path = os.path.join(w.HERE, "tests", "fixtures", "system_messages.png")
        with Image.open(path) as source:
            image = source.convert("RGB")
        with patch.object(w, "_capture_region", return_value=image):
            lines, raw_count, _ = w._ocr_chat_frame((0, 0, *image.size), force=True)
        self.assertGreaterEqual(raw_count, 2)
        self.assertEqual(lines, [])

    def test_real_recognizers_keep_english_and_thai_chat(self):
        image = Image.new("RGB", (800, 500), (24, 24, 24))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("C:/Windows/Fonts/tahoma.ttf", 30)
        for y, text in [(90, "Ann: hello world"), (145, "Bob: sell chest 43k"),
                        (200, "Yojo: ของคราฟ"), (255, "Ninesixzo: ได้แน่ครับ")]:
            draw.text((20, y), text, font=font, fill="white")
        with patch.object(w, "_capture_region", return_value=image):
            lines, _, _ = w._ocr_chat_frame((0, 0, 800, 500), force=True)
        self.assertEqual(lines, ["Ann: hello world", "Bob: sell chest 43k",
                                 "Yojo: ของคราฟ", "Ninesixzo: ได้แน่ครับ"])


if __name__ == "__main__":
    unittest.main()
