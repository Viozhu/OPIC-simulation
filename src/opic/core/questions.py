from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from opic.core.rubric import ActflLevel
from opic.core.selfassess import target_level
from opic.core.survey import SurveyAnswers, TopicGroup, selected_items, validate_survey


class QuestionType(Enum):
    SELF_INTRO = "self_intro"
    DESCRIPTION = "description"
    HABIT = "habit"
    EXPERIENCE = "experience"
    ROLEPLAY_SETUP = "roleplay_setup"
    ROLEPLAY_FOLLOWUP = "roleplay_followup"


@dataclass(frozen=True, slots=True)
class QuestionSlot:
    index: int
    qtype: QuestionType
    topic_id: str | None
    combo_id: int | None
    advanced: bool
    target: ActflLevel


@dataclass(frozen=True, slots=True)
class Question:
    """A slot once its English text exists.

    The blueprint says what to ask about; this says what was actually asked. The
    report quotes it, so it is domain data and belongs here rather than in
    whichever adapter happened to generate the wording.
    """

    slot: QuestionSlot
    text_en: str


COMBO_TYPES: tuple[QuestionType, ...] = (
    QuestionType.DESCRIPTION,
    QuestionType.HABIT,
    QuestionType.EXPERIENCE,
)
COMBO_COUNT = len(TopicGroup)
EXAM_LENGTH = 1 + COMBO_COUNT * len(COMBO_TYPES) + 2


def build_blueprint(
    answers: SurveyAnswers,
    self_assess_level: int,
    seed: int,
) -> tuple[QuestionSlot, ...]:
    """Lay out the whole exam before a single question is generated.

    Building the shape up front keeps the LLM off the critical path: by the time
    the test-taker reaches Setup, every question is known and its audio can be
    synthesised in advance. Combo topics are drawn one per survey group so the
    exam always exercises every group the test-taker opted into.
    """
    issues = validate_survey(answers)
    if issues:
        detail = ", ".join(f"{issue.error.value}({issue.detail})" for issue in issues)
        raise ValueError(f"invalid survey: {detail}")

    base = target_level(self_assess_level)
    stretched = ActflLevel.from_rank(base.rank + 1)

    rng = random.Random(seed)
    chosen = selected_items(answers)
    by_group: dict[TopicGroup, list[str]] = {group: [] for group in TopicGroup}
    for item in chosen:
        by_group[item.group].append(item.id)

    combo_topics = [rng.choice(by_group[group]) for group in TopicGroup]
    rng.shuffle(combo_topics)

    pool = [item.id for item in chosen]

    remaining = [topic for topic in pool if topic not in combo_topics]
    roleplay_topic = rng.choice(remaining or pool)

    slots: list[QuestionSlot] = [
        QuestionSlot(
            index=0,
            qtype=QuestionType.SELF_INTRO,
            topic_id=None,
            combo_id=None,
            advanced=False,
            target=base,
        )
    ]

    for combo_id, topic_id in enumerate(combo_topics):
        advanced = combo_id == COMBO_COUNT - 1
        for qtype in COMBO_TYPES:
            slots.append(
                QuestionSlot(
                    index=len(slots),
                    qtype=qtype,
                    topic_id=topic_id,
                    combo_id=combo_id,
                    advanced=advanced,
                    target=stretched if advanced else base,
                )
            )

    for qtype in (QuestionType.ROLEPLAY_SETUP, QuestionType.ROLEPLAY_FOLLOWUP):
        slots.append(
            QuestionSlot(
                index=len(slots),
                qtype=qtype,
                topic_id=roleplay_topic,
                combo_id=None,
                advanced=False,
                target=base,
            )
        )

    return tuple(slots)
