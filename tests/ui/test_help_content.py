import pytest

pytest.importorskip("PySide6")
from nocturne.ui import help_content as hc  # noqa: E402
from nocturne.ui.pipeline import path_stages  # noqa: E402


def test_every_stage_has_a_topic():
    for stage in path_stages():
        tid = hc.stage_topic_id(stage.id)
        assert tid is not None, f"stage {stage.id} has no topic"
        t = hc.topic(tid)
        assert t is not None and t.title and t.summary and t.body


def test_sections_reference_only_real_topics():
    for section in hc.SECTIONS:
        assert section.title
        for tid in section.topic_ids:
            assert tid in hc.TOPICS, f"TOC references missing topic {tid}"


def test_concept_topics_exist():
    for tid in ("getting-started", "linear-vs-stretched", "dualband",
                "tools", "stacking", "recipes", "troubleshooting"):
        assert tid in hc.TOPICS


def test_unknown_lookups_are_none():
    assert hc.topic("nope") is None
    assert hc.stage_topic_id("nope") is None


def test_bodies_are_substantial():
    for t in hc.TOPICS.values():
        assert len(t.body) > 120, f"topic {t.id} body too short"
