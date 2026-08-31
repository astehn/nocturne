"""Training-data generation helpers for Nocturne-native models.

This package deliberately contains dataset preparation, not model training.
The generated manifests are the boundary between Nocturne's image pipeline and
an independent training environment.
"""

from .pairs import (
    FrameGroup,
    FrameInfo,
    PairConfig,
    PreparedStack,
    RawStack,
    discover_frame_groups,
    generate_training_pairs,
    partition_pair,
    prepare_stack,
)

__all__ = [
    "FrameGroup",
    "FrameInfo",
    "PairConfig",
    "PreparedStack",
    "RawStack",
    "discover_frame_groups",
    "generate_training_pairs",
    "partition_pair",
    "prepare_stack",
]
