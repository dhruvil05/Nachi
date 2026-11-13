"""Load a curriculum's concepts and prerequisites into the database (idempotent)."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from nachi.curriculum import Curriculum
from nachi.learner.models import Concept, ConceptPrerequisite


async def seed_curriculum(session: AsyncSession, curriculum: Curriculum) -> int:
    """Insert or update every concept, and replace its prerequisite links.

    Returns the number of concepts written. Safe to run again after editing the YAML.
    """
    for item in curriculum.concepts:
        await session.merge(
            Concept(
                id=item.id,
                curriculum=curriculum.curriculum,
                title=item.title,
                summary=item.summary,
            )
        )
    await session.flush()
    ids = [c.id for c in curriculum.concepts]
    await session.execute(
        delete(ConceptPrerequisite).where(ConceptPrerequisite.concept_id.in_(ids))
    )
    for item in curriculum.concepts:
        for prereq in item.prerequisites:
            session.add(ConceptPrerequisite(concept_id=item.id, prerequisite_id=prereq))
    await session.commit()
    return len(curriculum.concepts)
