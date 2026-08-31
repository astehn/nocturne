"""The ladder filter: build what the run reads, not what the archive holds."""
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import build_dataset as B  # noqa: E402


@dataclass
class G:
    target_dir: str


ARCHIVE = [G("IC 1396A_sub"), G("NGC 6888_sub"), G("NGC281_sub"),
           G("NGC 7000 LP"), G("M 8_sub")]


def test_no_filter_leaves_the_archive_alone():
    """Every config written before 2026-08-30 omits the key, and each must
    keep building exactly what it built before."""
    assert B._keep_only_targets(ARCHIVE, None) == ARCHIVE
    assert B._keep_only_targets(ARCHIVE, []) == ARCHIVE


def test_the_filter_matches_across_the_archive_naming():
    """'NGC6888' in the split lists is 'NGC 6888_sub' on disk. Comparing those
    by equality is the exact bug that let all four held-out targets into
    training material on 2026-08-30 — so this filter must not repeat it."""
    kept = B._keep_only_targets(ARCHIVE, ["NGC6888", "NGC7000"])
    assert [g.target_dir for g in kept] == ["NGC 6888_sub", "NGC 7000 LP"]


def test_a_name_matching_nothing_is_refused_not_silently_dropped():
    """The failure this prevents is remote from its cause: a typo here yields
    an empty test split, and the run dies at the gate after hours of training
    with 'no held-out pairs found'."""
    with pytest.raises(ValueError, match="match nothing"):
        B._keep_only_targets(ARCHIVE, ["NGC6888", "NCG7000"])


def test_a_partial_match_does_not_satisfy_a_missing_one():
    """One good name must not mask one bad one — otherwise the gate quietly
    judges on half the targets it was told to."""
    with pytest.raises(ValueError, match="NCG7000|ncg7000"):
        B._keep_only_targets(ARCHIVE, ["NGC6888", "NCG7000"])


def test_the_two_gate_targets_are_what_S30_TEST_names():
    """The point of tonight's filter: what the gate reads is S30_TEST, so the
    filter and the split must not drift apart. If someone adds a third test
    target, this fails and the config gets updated with it."""
    import data as D
    kept = B._keep_only_targets(ARCHIVE, list(D.S30_TEST))
    assert {g.target_dir for g in kept} == {"NGC 6888_sub", "NGC 7000 LP"}
