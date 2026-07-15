# tests/test_text_lang.py
"""TDD tests for the plausibly-English text heuristic shared by speakers.py
and sentence_core.py (Task 6 / issue #3: empty-English-slot shift bug)."""


class TestIsPlausiblyEnglish:
    def test_plain_ascii_name_accepted(self):
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("Sam") is True

    def test_ascii_sentence_with_punctuation_accepted(self):
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("Hello, world! It's Sam.") is True

    def test_latin1_accented_name_accepted(self):
        """Latin-1 Supplement letters (e.g. u-umlaut) must be accepted -- an
        English/European display name like "Muller" is legitimate text, not
        a wrong-language shift."""
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("Müller") is True  # "Müller"

    def test_latin_extended_a_name_accepted(self):
        """Latin Extended-A (e.g. Polish l-stroke) must be accepted."""
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("Wałęsa") is True  # "Wałęsa"

    def test_japanese_text_rejected(self):
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("サム") is False  # Katakana "Samu"

    def test_kana_hiragana_rejected(self):
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("こんにちは") is False

    def test_cjk_ideograph_rejected(self):
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("你好") is False  # Chinese "Ni hao"

    def test_cyrillic_rejected(self):
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("Привет") is False  # "Privet"

    def test_empty_string_rejected(self):
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("") is False

    def test_whitespace_only_rejected(self):
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("   \t\n") is False

    def test_punctuation_only_rejected(self):
        """Punctuation/whitespace strip to empty -- not acceptable text."""
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("...!?") is False

    def test_mixed_english_and_japanese_rejected(self):
        """A string mixing scripts (e.g. a mistaken concatenation) is rejected
        -- any character at/above the Latin Extended-B boundary disqualifies it."""
        from deciwaves.engine.text_lang import is_plausibly_english
        assert is_plausibly_english("Sam サム") is False
