import unittest

from voiceassist.meaning import variants


class MeaningTests(unittest.TestCase):
    def test_polite_and_infinitive_forms(self):
        self.assertIn("открой блокнот", variants("можешь открыть блокнот пожалуйста"))
        self.assertIn("включи звук", variants("давай включить звук"))

    def test_verb_said_last(self):
        self.assertIn("открой блокнот", variants("блокнот открой"))

    def test_wants(self):
        self.assertIn("включи песню высоцкого", variants("хочу послушать высоцкого"))
        self.assertIn("включи фильм человек паук на кинокраде", variants("хочу посмотреть фильм человек паук"))

    def test_reverse_and_again_use_the_last_command(self):
        self.assertEqual(variants("а теперь наоборот", "скопируй все с первой на вторую")[0], "скопируй все со второй на первую")
        self.assertEqual(variants("наоборот", "сделай громче")[0], "сделай тише")
        self.assertEqual(variants("сделай то же самое", "открой загрузки")[0], "открой загрузки")
        self.assertNotIn(None, variants("наоборот", ""))
