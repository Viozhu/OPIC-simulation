from __future__ import annotations

from dataclasses import dataclass

from opic.core.rubric import ActflLevel


@dataclass(frozen=True, slots=True)
class SelfAssessOption:
    level: int
    description_ko: str
    sample_audio_id: str


SELF_ASSESS_OPTIONS: tuple[SelfAssessOption, ...] = (
    SelfAssessOption(
        1,
        "나는 10단어 이하의 단어로 말할 수 있습니다.",
        "sample_1",
    ),
    SelfAssessOption(
        2,
        "나는 기본적인 물건, 색깔, 요일, 음식, 의류, 숫자 등을 말할 수 있습니다. "
        "나는 항상 완벽한 문장을 구사하지는 못하고 간단한 질문도 하기 어렵습니다.",
        "sample_2",
    ),
    SelfAssessOption(
        3,
        "나는 나 자신, 직장, 친숙한 사람과 장소, 일상에 대한 기본적인 정보를 "
        "간단한 문장으로 전달할 수 있습니다. 간단한 질문을 할 수 있습니다.",
        "sample_3",
    ),
    SelfAssessOption(
        4,
        "나는 나 자신, 일상, 일/학교, 취미에 대해 간단한 대화를 할 수 있습니다. "
        "나는 이런 친숙한 주제와 일상에 대해 일련의 간단한 문장들을 쉽게 만들어 "
        "낼 수 있습니다. 내가 필요한 것을 얻기 위한 질문도 할 수 있습니다.",
        "sample_4",
    ),
    SelfAssessOption(
        5,
        "나는 친숙한 주제와 가정, 일/학교, 개인 및 사회적 관심사에 대해 대화할 수 "
        "있습니다. 나는 일어난 일과 일어나고 있는 일, 일어날 일에 대해 문장을 "
        "연결하여 말할 수 있습니다. 필요한 경우 설명도 할 수 있습니다. 일상 "
        "생활에서 예기치 못한 상황이 발생하더라도 임기응변으로 대처할 수 있습니다.",
        "sample_5",
    ),
    SelfAssessOption(
        6,
        "나는 일/학교, 개인적인 관심사, 시사 문제에 대한 어떤 대화나 토론에도 "
        "자신 있게 참여할 수 있습니다. 나는 대부분의 주제에 관해 높은 수준의 "
        "정확성과 폭넓은 어휘로 상세히 설명할 수 있습니다.",
        "sample_6",
    ),
)

LEVEL_TO_TARGET: dict[int, ActflLevel] = {
    1: ActflLevel.NL,
    2: ActflLevel.NM,
    3: ActflLevel.NH,
    4: ActflLevel.IM1,
    5: ActflLevel.IH,
    6: ActflLevel.AL,
}


def target_level(level: int) -> ActflLevel:
    """The proficiency the generated questions aim at, given the self assessment."""
    if level not in LEVEL_TO_TARGET:
        raise ValueError(f"self assessment level must be 1..6, got {level!r}")
    return LEVEL_TO_TARGET[level]
