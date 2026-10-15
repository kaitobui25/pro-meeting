"""Keep recognizer hallucination mitigation conservative and testable."""
import unittest

from meeting.local_asr import reduce_decoder_loops


class DecoderLoopTests(unittest.TestCase):
    def test_repeated_word_is_marked_instead_of_sent_to_translate(self):
        self.assertEqual(reduce_decoder_loops('うち、うち、うち、うち、うち、うち、次へ'),
                         'うち ....、次へ')

    def test_normal_repeated_confirmation_is_not_removed(self):
        self.assertEqual(reduce_decoder_loops('はい、はい、そうですね'), 'はい、はい、そうですね')


if __name__ == '__main__':
    unittest.main()
