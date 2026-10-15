"""Verify direct Python launch and the legacy browser switches."""

import unittest
from unittest.mock import patch

from meeting.chatgpt_web import ChatGPTWeb
from meeting.config import browser_mode, processing_mode


class ModesTests(unittest.TestCase):
    def test_direct_python_launch_defaults_to_local(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(browser_mode(), 'neo')
            self.assertEqual(processing_mode(), 'local_fast')
            with ChatGPTWeb(lambda _msg: None) as app:
                self.assertEqual(app.engine, 'local_fast')
                self.assertIsNone(app.neo)
                self.assertIsNone(app.bridge)

    def test_chrome_browser_defaults_to_legacy_web_flow(self):
        with patch.dict('os.environ', {'PRO_MEETING_BROWSER': 'chrome'}, clear=True):
            self.assertEqual(processing_mode(), 'web_audio')
            app = ChatGPTWeb(lambda _msg: None)
            self.assertEqual(app.browser, 'chrome')
            self.assertIsNotNone(app.bridge)

    def test_local_engine_ignores_browser_setting(self):
        with patch.dict('os.environ', {'PRO_MEETING_BROWSER': 'chrome',
                                        'PRO_MEETING_ENGINE': 'local_fast'}, clear=True):
            app = ChatGPTWeb(lambda _msg: None)
            self.assertEqual(app.engine, 'local_fast')
            self.assertIsNone(app.bridge)
            self.assertIsNone(app.neo)

    def test_hybrid_must_use_neo(self):
        with patch.dict('os.environ', {'PRO_MEETING_BROWSER': 'chrome',
                                        'PRO_MEETING_ENGINE': 'hybrid'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'neo'):
                ChatGPTWeb(lambda _msg: None)


if __name__ == '__main__':
    unittest.main()
