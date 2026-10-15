"""Regression tests for the Neo MCP response watcher (no browser required)."""

from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from meeting.neo_browser import NeoBrowser


class NeoBrowserTests(unittest.TestCase):
    def test_waits_for_completed_answer_and_tracks_navigated_page(self):
        reply = "NGUYÊN VĂN:\nこんにちは\nBẢN DỊCH TIẾNG VIỆT:\nXin chào"
        with TemporaryDirectory() as temporary:
            audio = Path(temporary) / "segment-1.wav"
            audio.write_bytes(b"RIFFtest")
            browser = NeoBrowser()
            browser.page_id = 5
            states = iter([
                {"attached": True},
                {"filled": True},
                {"sent": True},
                {"found": False},
                {"found": True, "pageId": 9, "hasAnswer": True, "text": reply, "generating": True},
                {"found": True, "pageId": 9, "hasAnswer": True, "text": reply, "generating": False},
            ])
            with (patch.object(browser, "_run", side_effect=lambda _: next(states)) as runner,
                  patch("meeting.neo_browser.time.monotonic", side_effect=count(step=10).__next__),
                  patch("meeting.neo_browser.time.sleep")):
                self.assertEqual(browser.transcribe_translate(audio, "Translate", timeout=300), reply)
            self.assertEqual(browser.page_id, 9)
            self.assertEqual(runner.call_count, 6)

    def test_timeout_does_not_send_again(self):
        with TemporaryDirectory() as temporary:
            audio = Path(temporary) / "segment-2.wav"
            audio.write_bytes(b"RIFFtest")
            browser = NeoBrowser()
            browser.page_id = 7
            states = iter([{"attached": True}, {"filled": True}, {"sent": True}, {"found": False}])
            with (patch.object(browser, "_run", side_effect=lambda _: next(states)) as runner,
                  patch("meeting.neo_browser.time.monotonic", side_effect=count(step=5).__next__),
                  patch("meeting.neo_browser.time.sleep")):
                with self.assertRaises(TimeoutError):
                    browser.transcribe_translate(audio, "Translate", timeout=15)
            self.assertEqual(runner.call_count, 4)


if __name__ == "__main__":
    unittest.main()
