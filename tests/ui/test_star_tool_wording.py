"""What the help and the receipt say happens with no star tool set up.

Kept in step with core/receipt._FALLBACKS — the receipt's per-step answer was
verified against each step's apply(), so the help is checked against IT rather
than against a second, hand-kept list (review 2026-10-16).
"""
import re

import pytest

pytest.importorskip("PySide6")
from nocturne.core import receipt  # noqa: E402
from nocturne.settings import Settings  # noqa: E402
from nocturne.ui import help_content as h  # noqa: E402

# What each fallback is called in the help's "Without it" sentence.
_PHRASE = {
    "Nocturne (free star split)": "Nocturne's own separator",
    "Nocturne (star mask)": "star mask",
    "Nocturne (whole image, no split)": "whole image",
}


def _without_it_clauses() -> list[str]:
    body = re.sub(r"<[^>]+>", "", h.topic("tools").body)
    para = body[body.index("StarNet2 (free, optional)"):body.index("RC-Astro (paid, optional)")]
    sentence = para[para.index("Without it"):]
    sentence = sentence[:sentence.index(".") + 1]
    return sentence.split(";")


@pytest.mark.parametrize("sid", sorted(receipt.SPLIT_STAGES))
def test_the_starnet2_help_says_what_each_star_step_does_without_it(sid):
    name = receipt._PREFERS[sid][0]
    phrase = _PHRASE[receipt._FALLBACKS[sid]]
    clauses = [c for c in _without_it_clauses() if name in c]
    assert clauses, f"{name} is not in the 'Without it' sentence"
    assert all(phrase in c for c in clauses), (name, phrase, clauses)


def test_every_fallback_has_a_phrase():
    assert {receipt._FALLBACKS[s] for s in receipt.SPLIT_STAGES} <= set(_PHRASE)


def test_colour_balance_help_qualifies_the_stars_promise():
    body = re.sub(r"<[^>]+>", "", h.topic("color_balance").body)
    first = body[:body.index("stars are")]
    sentence = first[first.rfind(".") + 1:] + body[body.index("stars are"):].split(".")[0]
    assert "star tool" in sentence or "StarNet2" in sentence, sentence


@pytest.mark.parametrize("sid", sorted(receipt.SPLIT_STAGES))
def test_with_no_tool_the_reason_names_both_star_tools(sid):
    note = receipt.engine_for(sid, Settings())
    assert note.reason == "no star tool set up (StarXTerminator or StarNet2)", note


@pytest.mark.parametrize("sid", ["deconvolution", "noise_sharpen"])
def test_the_other_rc_astro_steps_still_name_rc_astro(sid):
    note = receipt.engine_for(sid, Settings())
    assert "RC-Astro" in note.reason or "not configured" in note.reason, note
