import unittest

from meeting.chatgpt_web import PROMPT, clean_transcript


class TranscriptCleanupTests(unittest.TestCase):
    def test_replaces_all_requested_phrases_both_sections(self):
        output = clean_transcript(
            'NGUYÊN VĂN:\nHello [Không nghe rõ] good morning.\n'
            '“[Không nhận diện được nội dung.]”\n'
            'BẢN DỊCH TIẾNG VIỆT:\nXin chào. '
            '[Phần lớn âm thanh không đủ rõ để phiên âm và dịch chính xác.]'
        )
        self.assertEqual(output, 'NGUYÊN VĂN:\nHello .... good morning.\n....\n'
                         'BẢN DỊCH TIẾNG VIỆT:\nXin chào. ....')

    def test_keeps_actual_transcript(self):
        original = 'NGUYÊN VĂN:\nHello team.\nBẢN DỊCH TIẾNG VIỆT:\nXin chào mọi người.'
        self.assertEqual(clean_transcript(original), original)

    def test_prompt_asks_for_dots_and_no_explanatory_placeholder(self):
        self.assertIn('chỉ viết chính xác ....', PROMPT)


if __name__ == '__main__':
    unittest.main()
