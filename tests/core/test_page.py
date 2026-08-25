"""The standalone page, rendered from a real graded exam.

Same fixture as `test_report_real_data.py`: fifteen answers from a completed
acceptance run. The page is the artefact the candidate keeps, so the tests here
are about it not lying — the transcript it prints is the transcript that was
rated, and the sections that need a model are absent rather than invented when
no model ran.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from opic.core.metrics import LOW_CONFIDENCE_THRESHOLD
from opic.core.narrative import (
    Analysis,
    AnswerRewrite,
    Caveat,
    ErrorPattern,
    GapSection,
    Narrative,
    PatternItem,
    quotes_in_report,
)
from opic.core.page import INVENTED_WARNING_KO, Meta, render_html
from opic.core.report import build_report
from core.test_report_real_data import (
    aggregate_available_from,
    load_assessments,
)

META = Meta(session_id="20260821-140338", seed=1787288618, target_level="IH")


def real_report():
    assessments = load_assessments()
    questions = [a.question for a in assessments]
    return build_report(aggregate_available_from(questions, assessments), questions)


def answer_blocks(page: str) -> list[str]:
    return re.findall(r'<article class="tx">.*?</article>', page, re.S)


def field(block: str, klass: str) -> str:
    match = re.search(
        r'<p class="' + klass + r'">.*?</span>(.*?)</p>', block, re.S
    )
    assert match, f"{klass} missing from the answer block"
    return match.group(1)


def spoken(markup: str) -> str:
    """The text of a transcript block, with the low-confidence marks removed."""
    return html.unescape(
        re.sub(r'<span class="lo"[^>]*>(.*?)</span>', r"\1", markup, flags=re.S)
    )


def a_narrative(report) -> Narrative:
    quote, correction = sorted(quotes_in_report(report))[0]
    return Narrative(
        analysis=Analysis(
            verdict_ko="판정 문장",
            dimensions_lede_ko="영역 도입",
            dimensions_close_ko="영역 마무리",
            distribution_ko="분포 설명",
            patterns=(
                ErrorPattern(
                    title_ko="관사",
                    blurb_ko="관사 설명",
                    items=(
                        PatternItem(
                            answer_index=1,
                            quote=quote,
                            correction_en=correction,
                            issue_ko="설명",
                        ),
                    ),
                ),
            ),
            patterns_close_ko="유형 마무리",
            gap=GapSection(
                title_ko="가장 큰 구멍",
                blurb_ko="구멍 설명",
                answer_indexes=(6, 9),
                close_ko="구멍 마무리",
            ),
            splits_close_ko="분할 마무리",
            sound_ko="소리 설명",
            caveats=(Caveat(title_ko="유의", body_ko="유의 본문"),),
        ),
        rewrites=(
            AnswerRewrite(
                answer_index=0, text_en="A better answer.", why_ko="이유", invented=False
            ),
            AnswerRewrite(
                answer_index=6,
                text_en="An invented Saturday.",
                why_ko="이유",
                invented=True,
            ),
        ),
    )


# ------------------------------------------------------- what the page must not do


def test_the_page_prints_the_transcript_that_was_rated():
    report = real_report()

    page = render_html(report, META)

    blocks = answer_blocks(page)
    assert len(blocks) == len(report.answers) == 15
    for block, answer in zip(blocks, report.answers, strict=True):
        assert spoken(field(block, "tx__a")) == answer.transcript_text
        assert html.unescape(field(block, "tx__q")) == answer.question_en


def test_every_doubtful_word_is_marked_and_no_other_word_is():
    report = real_report()

    page = render_html(report, META)

    expected = sum(
        1
        for answer in report.answers
        for word in answer.transcript_words
        if word.probability < LOW_CONFIDENCE_THRESHOLD
    )
    assert expected > 0
    assert page.count('<span class="lo"') == expected


def test_content_is_escaped_not_injected():
    report = real_report()

    page = render_html(report, META)

    # The fixture's questions and answers are full of apostrophes; none of them
    # may reach the page as markup.
    assert "&#x27;" in page
    assert "<script" not in page.lower()
    assert "onerror=" not in page.lower()


def test_the_page_parses_with_every_tag_closed():
    report = real_report()

    page = render_html(report, META, a_narrative(report))

    class Balance(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.stack: list[str] = []
            self.bad: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag in {"link", "br", "img", "meta", "input"}:
                return
            self.stack.append(tag)

        def handle_endtag(self, tag):
            if not self.stack or self.stack[-1] != tag:
                self.bad.append(tag)
                return
            self.stack.pop()

    balance = Balance()
    balance.feed(page)
    assert balance.bad == []
    assert balance.stack == []


# -------------------------------------------------- with a narrative and without


def test_without_a_narrative_the_judged_sections_are_absent():
    report = real_report()

    page = render_html(report, META)

    assert "AL 목표 답변" not in page
    assert "가장 큰 구멍" not in page
    assert 'class="pat"' not in page
    # and the derived ones are all still there
    for expected in (
        "OPIc 모의고사 결과",
        "영역별 등급",
        "개 평가가 어디에 떨어졌는가",
        "유형별 · 주제별",
        "어떻게 들리는가",
        "개 답변 전체",
        "질문과 답변, 인식된 그대로",
        "발음은 점수가 아닙니다",
    ):
        assert expected in page, expected


def test_with_a_narrative_the_judged_sections_appear():
    report = real_report()

    page = render_html(report, META, a_narrative(report))

    assert "판정 문장" in page
    assert "가장 큰 구멍" in page
    assert "관사" in page
    assert "유의 본문" in page
    assert "질문 · 답변 · AL 목표 답변" in page
    assert "A better answer." in page


def test_an_invented_episode_is_labelled_and_a_real_one_is_not():
    report = real_report()
    narrative = a_narrative(report)

    page = render_html(report, META, narrative)

    assert page.count('class="tx__made"') == 1
    assert INVENTED_WARNING_KO in page

    blocks = answer_blocks(page)
    assert "tx__made" in blocks[6], "the invented rewrite carries the warning"
    assert "tx__made" not in blocks[0], "the faithful rewrite does not"


def test_answers_without_a_rewrite_keep_their_question_and_transcript():
    report = real_report()

    page = render_html(report, META, a_narrative(report))

    blocks = answer_blocks(page)
    assert page.count('class="tx__al"') == 2
    for index in (1, 2, 3):
        assert "tx__al" not in blocks[index]
        assert spoken(field(blocks[index], "tx__a")) == report.answers[
            index
        ].transcript_text


# ------------------------------------------------------------------- the chrome


def test_both_themes_are_defined_so_the_page_survives_being_reopened():
    page = render_html(real_report(), META)

    assert "prefers-color-scheme: dark" in page
    assert ':root[data-theme="dark"]' in page


def test_the_page_is_a_whole_document():
    """Not a fragment. A fragment renders in quirks mode in an iframe, and a
    fragment of Korean saved to disk has nothing on it that says UTF-8 — this
    file gets opened from a desktop months later, with no server involved."""
    page = render_html(real_report(), META)

    assert page.startswith('<!doctype html>\n<html lang="ko">')
    assert '<meta charset="utf-8">' in page
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in page
    assert page.rstrip().endswith("</html>")
    assert page.count("<html") == 1
    assert page.count("</html>") == 1
    assert page.count("<title>") == 1


def test_the_scale_is_drawn_whole_with_the_final_level_marked():
    report = real_report()

    page = render_html(report, META)

    ladder = re.search(r'<div class="ladder__labs">(.*?)</div>', page, re.S)
    assert ladder
    assert ladder.group(1).count("<span") == 9
    assert f'is-cur">{report.final_level.name}<' in ladder.group(1)


def test_the_speed_chart_has_one_bar_per_scored_answer():
    report = real_report()

    page = render_html(report, META)

    plot = re.search(r'<div class="chart__plot".*?</div>\s*</div>', page, re.S)
    assert plot
    bars = re.findall(r'class="bar(?:\s[^"]*)?"', plot.group(0))
    assert len(bars) == report.scored_answers
