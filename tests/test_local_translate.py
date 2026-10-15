"""Deterministic clause grouping and local translator edge cases."""
import unittest

from meeting.local_translate import translation_groups, LocalJapaneseVietnamese


class GroupingTests(unittest.TestCase):
    def test_preserves_text_without_giant_monologues(self):
        sample = '最初にやりましょう\nそれから考えます。次はどうですか？\n準備します'
        groups = translation_groups(sample, max_chars=23)
        self.assertTrue(all(len(group) <= 23 for group in groups))
        self.assertEqual(''.join(group.replace(' ', '') for group in groups),
                         sample.replace('\n', ''))

    def test_single_long_clause_is_bounded(self):
        groups = translation_groups('カ' * 80, max_chars=20)
        self.assertEqual([20, 20, 20, 20], [len(g) for g in groups])

    def test_rejects_absurd_group_size(self):
        with self.assertRaises(ValueError):
            translation_groups('こんにちは', max_chars=3)

    def test_unknown_speech_skips_model(self):
        translator = object.__new__(LocalJapaneseVietnamese)
        self.assertEqual(translator.translate('....'), '....')


if __name__ == '__main__':
    unittest.main()
