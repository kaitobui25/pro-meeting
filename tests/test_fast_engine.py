"""Verify local-fast meets the contract without opening ChatGPT or uploading audio."""
from pathlib import Path
from unittest.mock import patch
import unittest

from meeting.chatgpt_web import ChatGPTWeb


class LocalFastFlowTests(unittest.TestCase):
    def test_local_fast_does_not_open_browser_and_keeps_two_sections(self):
        status = []
        settings = {'PRO_MEETING_BROWSER': 'neo',
                    'PRO_MEETING_ENGINE': 'local_fast',
                    'PRO_MEETING_CHATGPT_MODE': 'instant'}
        with (patch.dict('os.environ', settings),
              patch('meeting.chatgpt_web.LocalSpeechRecognizer') as asr_factory,
              patch('meeting.chatgpt_web.LocalJapaneseVietnamese') as translator_factory):
            asr_factory.return_value.transcribe.return_value = 'こんにちは。'
            translator_factory.return_value.translate.return_value = 'Xin chào.'
            with (ChatGPTWeb(status.append) as chat,
                  patch('meeting.chatgpt_web.NeoBrowser.prepare') as browser_prepare):
                    chat.await_login(lambda: False)
                    response = chat.transcribe_translate(Path('segment-1.wav'), 1)
                    browser_prepare.assert_not_called()
            self.assertIn('NGUYÊN VĂN:\nこんにちは。', response)
            self.assertIn('BẢN DỊCH TIẾNG VIỆT:\nXin chào.', response)
            self.assertIsNone(chat.neo)
            self.assertIsNone(chat.bridge)
            self.assertEqual(chat.last_timing['mode'], 'local_fast')
            self.assertTrue(any('Đã hoàn thành đoạn 1' in note for note in status))
            asr_factory.return_value.transcribe.assert_called_once()
            translator_factory.return_value.translate.assert_called_once_with('こんにちは。')


if __name__ == '__main__':
    unittest.main()
