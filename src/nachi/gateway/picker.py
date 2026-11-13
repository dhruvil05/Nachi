"""Choose what to study next: the weakest concept whose prerequisites are in place."""

from __future__ import annotations

from collections.abc import Mapping

from nachi.curriculum import Curriculum

READY_THRESHOLD = 0.6  # every prerequisite at least this good
MASTERED_THRESHOLD = 0.9  # concepts at or above this are done


def is_ready(curriculum: Curriculum, concept_id: str, mastery: Mapping[str, float]) -> bool:
    concept = curriculum.concept(concept_id)
    return all(mastery.get(p, 0.0) >= READY_THRESHOLD for p in concept.prerequisites)


def next_concept(curriculum: Curriculum, mastery: Mapping[str, float]) -> str | None:
    """Lowest-mastery ready concept, earliest in prerequisite order on ties; None when done."""
    order = {cid: i for i, cid in enumerate(curriculum.order)}
    candidates = [
        cid
        for cid in curriculum.order
        if mastery.get(cid, 0.0) < MASTERED_THRESHOLD and is_ready(curriculum, cid, mastery)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda cid: (mastery.get(cid, 0.0), order[cid]))
