import re

from lifegit.i18n import LANGS, MESSAGES, t
from lifegit.models import STAT_NAMES
from lifegit.narrator import LABELS, NARRATION, QUIPS
from lifegit.params import default_params


def placeholders(s: str) -> set[str]:
    return set(re.findall(r"\{(\w+)", s))


def test_every_message_has_every_language_with_same_placeholders():
    for key, texts in MESSAGES.items():
        assert set(texts) == set(LANGS), key
        assert len({frozenset(placeholders(s)) for s in texts.values()}) == 1, key


def test_every_stat_has_a_display_name():
    for stat in STAT_NAMES:
        for lang in LANGS:
            assert t(f"stat.{stat}", lang)


def test_mock_text_covers_every_action_and_language():
    assert set(LABELS) == set(default_params().actions)
    assert set(NARRATION) == set(LANGS)
    for by_lang in QUIPS.values():
        assert set(by_lang) == set(LANGS) and all(by_lang.values())
