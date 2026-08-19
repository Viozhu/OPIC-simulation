from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Occupation(Enum):
    BUSINESS = "business"
    HOME_OFFICE = "home_office"
    TEACHER = "teacher"
    NO_EXPERIENCE = "no_experience"


class Housing(Enum):
    ALONE = "alone"
    WITH_ROOMMATE = "with_roommate"
    WITH_FAMILY = "with_family"
    DORM = "dorm"
    BARRACKS = "barracks"


class RecentCourse(Enum):
    """Part 2 of the survey: the last course a non-student took."""

    DEGREE = "degree"
    PROFESSIONAL = "professional"
    LANGUAGE = "language"
    OVER_FIVE_YEARS_AGO = "over_5y"


RECENT_COURSE_LABELS_KO: dict[RecentCourse, str] = {
    RecentCourse.DEGREE: "학위 과정 수업",
    RecentCourse.PROFESSIONAL: "전문 기술 향상을 위한 평생 학습",
    RecentCourse.LANGUAGE: "어학수업",
    RecentCourse.OVER_FIVE_YEARS_AGO: "수강 후 5년 이상 지남",
}


OCCUPATION_LABELS_KO: dict[Occupation, str] = {
    Occupation.BUSINESS: "사업/회사",
    Occupation.HOME_OFFICE: "재택근무/재택사업",
    Occupation.TEACHER: "교사/교육자",
    Occupation.NO_EXPERIENCE: "일 경험 없음",
}

HOUSING_LABELS_KO: dict[Housing, str] = {
    Housing.ALONE: "개인주택이나 아파트에 홀로 거주",
    Housing.WITH_ROOMMATE: "친구나 룸메이트와 함께 주택이나 아파트에 거주",
    Housing.WITH_FAMILY: "가족(배우자/자녀/기타 가족 일원)과 함께 주택이나 아파트에 거주",
    Housing.DORM: "학교 기숙사",
    Housing.BARRACKS: "군대 막사",
}


class TopicGroup(Enum):
    LEISURE = "leisure"
    HOBBY = "hobby"
    SPORT = "sport"
    TRAVEL = "travel"


@dataclass(frozen=True, slots=True)
class SurveyItem:
    id: str
    group: TopicGroup
    label_ko: str
    label_en: str


SURVEY_ITEMS: tuple[SurveyItem, ...] = (
    SurveyItem("movies", TopicGroup.LEISURE, "영화보기", "watching movies"),
    SurveyItem("clubbing", TopicGroup.LEISURE, "클럽/나이트클럽 가기", "going to clubs"),
    SurveyItem("live_shows", TopicGroup.LEISURE, "공연보기", "seeing live performances"),
    SurveyItem("concerts", TopicGroup.LEISURE, "콘서트보기", "going to concerts"),
    SurveyItem("museums", TopicGroup.LEISURE, "박물관가기", "visiting museums"),
    SurveyItem("parks", TopicGroup.LEISURE, "공원가기", "going to parks"),
    SurveyItem("camping", TopicGroup.LEISURE, "캠핑하기", "camping"),
    SurveyItem("beach", TopicGroup.LEISURE, "해변가기", "going to the beach"),
    SurveyItem("watching_sports", TopicGroup.LEISURE, "스포츠 관람", "watching sports"),
    SurveyItem("home_improvement", TopicGroup.LEISURE, "주거 개선", "home improvement"),
    SurveyItem("reading_to_kids", TopicGroup.HOBBY, "아이에게 책 읽어주기", "reading to children"),
    SurveyItem("listening_music", TopicGroup.HOBBY, "음악 감상하기", "listening to music"),
    SurveyItem("playing_instrument", TopicGroup.HOBBY, "악기 연주하기", "playing an instrument"),
    SurveyItem("singing", TopicGroup.HOBBY, "혼자 노래부르거나 합창하기", "singing"),
    SurveyItem("dancing", TopicGroup.HOBBY, "춤추기", "dancing"),
    SurveyItem("writing", TopicGroup.HOBBY, "글쓰기(편지, 단문, 시 등)", "writing"),
    SurveyItem("drawing", TopicGroup.HOBBY, "그림 그리기", "drawing"),
    SurveyItem("cooking", TopicGroup.HOBBY, "요리하기", "cooking"),
    SurveyItem("pets", TopicGroup.HOBBY, "애완동물 기르기", "keeping pets"),
    SurveyItem("cricket", TopicGroup.SPORT, "크리켓", "cricket"),
    SurveyItem("golf", TopicGroup.SPORT, "골프", "golf"),
    SurveyItem("volleyball", TopicGroup.SPORT, "배구", "volleyball"),
    SurveyItem("tennis", TopicGroup.SPORT, "테니스", "tennis"),
    SurveyItem("badminton", TopicGroup.SPORT, "배드민턴", "badminton"),
    SurveyItem("table_tennis", TopicGroup.SPORT, "탁구", "table tennis"),
    SurveyItem("swimming", TopicGroup.SPORT, "수영", "swimming"),
    SurveyItem("cycling", TopicGroup.SPORT, "자전거", "cycling"),
    SurveyItem("skiing", TopicGroup.SPORT, "스키/스노우보드", "skiing or snowboarding"),
    SurveyItem("ice_skating", TopicGroup.SPORT, "아이스 스케이트", "ice skating"),
    SurveyItem("jogging", TopicGroup.SPORT, "조깅", "jogging"),
    SurveyItem("walking", TopicGroup.SPORT, "걷기", "walking"),
    SurveyItem("yoga", TopicGroup.SPORT, "요가", "yoga"),
    SurveyItem("hiking", TopicGroup.SPORT, "하이킹/트레킹", "hiking"),
    SurveyItem("fishing", TopicGroup.SPORT, "낚시", "fishing"),
    SurveyItem("gym", TopicGroup.SPORT, "헬스", "working out at a gym"),
    SurveyItem("no_sport", TopicGroup.SPORT, "운동을 전혀 하지 않음", "no sports at all"),
    SurveyItem("domestic_business_trip", TopicGroup.TRAVEL, "국내출장", "domestic business trips"),
    SurveyItem("overseas_business_trip", TopicGroup.TRAVEL, "해외출장", "overseas business trips"),
    SurveyItem("staycation", TopicGroup.TRAVEL, "집에서 보내는 휴가", "vacations at home"),
    SurveyItem("domestic_travel", TopicGroup.TRAVEL, "국내 여행", "domestic travel"),
    SurveyItem("overseas_travel", TopicGroup.TRAVEL, "해외 여행", "overseas travel"),
)

ITEMS_BY_ID: dict[str, SurveyItem] = {item.id: item for item in SURVEY_ITEMS}

MIN_TOTAL_ITEMS = 12

GROUP_MINIMUMS: dict[TopicGroup, int] = {
    TopicGroup.LEISURE: 2,
    TopicGroup.HOBBY: 1,
    TopicGroup.SPORT: 1,
    TopicGroup.TRAVEL: 1,
}

GROUP_LABELS_KO: dict[TopicGroup, str] = {
    TopicGroup.LEISURE: "여가 활동",
    TopicGroup.HOBBY: "취미나 관심사",
    TopicGroup.SPORT: "운동",
    TopicGroup.TRAVEL: "휴가나 출장",
}

# The four question stems the survey form asks, keyed by the field they
# answer. The front end fetches these at runtime; it carries no copy of its
# own, so this dict is the one place the wording can change.
QUESTION_LABELS_KO: dict[str, str] = {
    "occupation": "현재 귀하는 어느 분야에 종사하고 계십니까?",
    "is_student": "현재 학생이십니까?",
    "recent_course": "최근 어떤 강의를 수강했습니까?",
    "housing": "현재 귀하는 어디에 살고 계십니까?",
}

YES_NO_LABELS_KO: dict[bool, str] = {
    True: "예",
    False: "아니오",
}


@dataclass(frozen=True, slots=True)
class SurveyAnswers:
    occupation: Occupation
    is_student: bool
    housing: Housing
    selected_item_ids: tuple[str, ...]
    recent_course: RecentCourse | None = None


class SurveyError(Enum):
    UNKNOWN_ITEM = "unknown_item"
    DUPLICATE_ITEM = "duplicate_item"
    TOO_FEW_ITEMS = "too_few_items"
    GROUP_MINIMUM = "group_minimum"
    MISSING_COURSE = "missing_course"
    UNEXPECTED_COURSE = "unexpected_course"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    error: SurveyError
    detail: str


def validate_survey(answers: SurveyAnswers) -> tuple[ValidationIssue, ...]:
    """Return every rule the selection breaks. An empty tuple means valid."""
    issues: list[ValidationIssue] = []

    unknown = [
        item_id for item_id in answers.selected_item_ids if item_id not in ITEMS_BY_ID
    ]
    for item_id in unknown:
        issues.append(ValidationIssue(SurveyError.UNKNOWN_ITEM, item_id))

    seen: set[str] = set()
    for item_id in answers.selected_item_ids:
        if item_id in seen:
            issues.append(ValidationIssue(SurveyError.DUPLICATE_ITEM, item_id))
        seen.add(item_id)

    known = [
        ITEMS_BY_ID[item_id]
        for item_id in dict.fromkeys(answers.selected_item_ids)
        if item_id in ITEMS_BY_ID
    ]

    if len(known) < MIN_TOTAL_ITEMS:
        issues.append(
            ValidationIssue(
                SurveyError.TOO_FEW_ITEMS,
                f"{len(known)}/{MIN_TOTAL_ITEMS}",
            )
        )

    for group, minimum in GROUP_MINIMUMS.items():
        chosen = sum(1 for item in known if item.group is group)
        if chosen < minimum:
            issues.append(
                ValidationIssue(
                    SurveyError.GROUP_MINIMUM,
                    f"{group.value}: {chosen}/{minimum}",
                )
            )

    if answers.is_student and answers.recent_course is not None:
        issues.append(
            ValidationIssue(
                SurveyError.UNEXPECTED_COURSE,
                answers.recent_course.value,
            )
        )
    elif not answers.is_student and answers.recent_course is None:
        issues.append(ValidationIssue(SurveyError.MISSING_COURSE, "not a student"))

    return tuple(issues)


def describe_issue_ko(issue: ValidationIssue) -> str:
    """A full Korean sentence a candidate can act on.

    Never the enum name and never a raw item id or group id — those are
    internal identifiers, not something a candidate reads. `detail` carries
    the specifics `validate_survey` produced; this derives the message from
    those same fields rather than surfacing them verbatim.
    """
    if issue.error is SurveyError.UNKNOWN_ITEM:
        return "선택한 항목 중 존재하지 않는 항목이 있습니다. 항목을 다시 선택해 주세요."

    if issue.error is SurveyError.DUPLICATE_ITEM:
        item = ITEMS_BY_ID.get(issue.detail)
        name = item.label_ko if item is not None else "동일한 항목"
        return f"{name}을(를) 두 번 선택했습니다. 한 번만 선택해 주세요."

    if issue.error is SurveyError.TOO_FEW_ITEMS:
        chosen, _, total = issue.detail.partition("/")
        needed = int(total) - int(chosen)
        return f"관심 항목을 최소 {total}개 선택해야 합니다. {needed}개 더 선택해 주세요."

    if issue.error is SurveyError.GROUP_MINIMUM:
        group_part, _, counts = issue.detail.partition(":")
        group = TopicGroup(group_part.strip())
        chosen, _, minimum = counts.strip().partition("/")
        return (
            f"{GROUP_LABELS_KO[group]} 항목을 최소 {minimum}개 선택해야 합니다. "
            f"현재 {chosen}개를 선택했습니다."
        )

    if issue.error is SurveyError.MISSING_COURSE:
        return "학생이 아닌 경우에는 최근 수강한 강의를 선택해야 합니다."

    if issue.error is SurveyError.UNEXPECTED_COURSE:
        return "학생인 경우에는 최근 수강한 강의를 선택할 수 없습니다."

    raise AssertionError(f"unhandled survey error: {issue.error}")


def selected_items(answers: SurveyAnswers) -> tuple[SurveyItem, ...]:
    """Resolve the selection to catalog entries, preserving selection order."""
    return tuple(ITEMS_BY_ID[item_id] for item_id in answers.selected_item_ids)
