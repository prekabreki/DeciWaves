from deciwaves.engine.text_normalize import normalize


def test_normalize():
    assert normalize("I'LL, find  a Way!") == "ill find a way"


def test_normalize_strips_subtitle_markup():
    """Subtitle directives (<subtitle-delay=..>, <split..>) are not spoken -> stripped."""
    assert normalize("<subtitle-delay=0.4>Nora!<split50>Make way for Aloy!") == "nora make way for aloy"
