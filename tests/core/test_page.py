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

from opic.adapters.narrative import parse_analysis, parse_rewrites
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
            closing_recap_ko="리포트 요약 문장",
            closing_why_ko="이 등급이 나온 이유",
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


# ------------------------------------------------- the sanitizer/page seam


def _hostile_prose() -> str:
    """Four attacks in one string, the ones named in issue #17: an executable
    tag, an event handler riding an otherwise-inert tag, an allowed tag
    carrying an attribute, and stray quotes — plus the three bare allowed
    tags, so the same string that tries to break `_prose` also proves it
    still renders what it should."""
    return (
        "<script>alert(1)</script>"
        "<img src=x onerror=alert(1)>"
        '<b onclick="alert(1)">clickme</b>'
        """ she said "hi" and it's fine """
        "<b>bold</b><i>italic</i><code>snippet</code>"
    )


def a_hostile_analysis_payload(report) -> dict:
    """Every `_ko` field `parse_analysis` reads, filled with `_hostile_prose`.

    `page.py` inserts each of these into the page without escaping, on the
    promise that `clean_markup` already ran on it. A field left out here would
    leave that promise unchecked for that one spot.
    """
    quote, correction = sorted(quotes_in_report(report))[0]
    hostile = _hostile_prose()
    return {
        "verdict_ko": hostile,
        "dimensions_lede_ko": hostile,
        "dimensions_close_ko": hostile,
        "distribution_ko": hostile,
        "patterns": [
            {
                "title_ko": hostile,
                "blurb_ko": hostile,
                "items": [
                    {
                        "answer_index": 1,
                        "quote": quote,
                        "correction_en": correction,
                        "issue_ko": hostile,
                    }
                ],
            }
        ],
        "patterns_close_ko": hostile,
        "gap": {
            "title_ko": hostile,
            "blurb_ko": hostile,
            "answer_indexes": [1],
            "close_ko": hostile,
        },
        "splits_close_ko": hostile,
        "sound_ko": hostile,
        "caveats": [{"title_ko": hostile, "body_ko": hostile}],
        "closing_recap_ko": hostile,
        "closing_why_ko": hostile,
    }


def test_the_model_cannot_reach_the_page_with_a_script():
    """The seam between the sanitizer and `page.py`, not either half alone.

    `tests/adapters/test_narrative.py` already proves `clean_markup` escapes
    a `<script>` and an `onerror` in isolation — that is not what is missing.
    What ties nothing together is the other half: `_prose` trusts
    `ALLOWED_TAGS` to have kept the markup inert, and nothing fails if that
    trust becomes wrong. So this sends hostile prose through the real
    adapter (`parse_analysis`, `parse_rewrites`) — the path a model's output
    actually takes — and inspects the HTML `render_html` produced, not the
    sanitizer's return value. Widen `ALLOWED_TAGS`, or let a tag keep an
    attribute, and this is the test that goes red.
    """
    report = real_report()
    analysis = parse_analysis(a_hostile_analysis_payload(report), report)
    rewrites = parse_rewrites(
        {
            "rewrites": [
                {
                    "answer_index": 1,
                    "text_en": "x" * 200,
                    "why_ko": _hostile_prose(),
                    "invented": False,
                }
            ]
        },
        report,
    )
    narrative = Narrative(analysis=analysis, rewrites=rewrites)

    page = render_html(report, META, narrative)

    tags: list[tuple[str, list[tuple[str, str | None]]]] = []

    class Collector(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append((tag, attrs))

    Collector().feed(page)

    names = [tag for tag, _ in tags]
    # the page's own docstring is explicit: "no script, no image" — so any
    # parsed instance of either can only have come from the narrative
    assert "script" not in names, "a <script> tag reached the rendered page"
    assert "img" not in names, "an <img> tag reached the rendered page"

    for tag, attrs in tags:
        for attr_name, _ in attrs:
            assert not attr_name.lower().startswith("on"), (
                f"<{tag} {attr_name}=...> is a live event handler in the report"
            )
        if tag in ("b", "i", "code"):
            assert attrs == [], f"<{tag}> carries an attribute: {attrs}"

    # the three legitimate tags still render as tags, not as escaped text —
    # the failure mode this guards against is silence, not a missing feature
    assert "<b>bold</b>" in page
    assert "<i>italic</i>" in page
    assert "<code>snippet</code>" in page

    # the attack text is still visible, just inert — clean_markup neutralises
    # markup, it does not delete the model's words
    assert "alert(1)" in page


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
    assert "리포트 요약 문장" in page
    assert "이 등급이 나온 이유" in page


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


def test_the_page_prints_as_a_document_that_still_says_the_level():
    """The ladder, the chips and the chart carry their meaning in background
    colour. A browser that drops backgrounds when printing would produce a
    nine-rung ladder with no rung marked — a report that does not say what
    level anyone reached. `print-color-adjust` is what forbids that."""
    page = render_html(real_report(), META)

    assert "@media print" in page
    assert "print-color-adjust: exact" in page
    assert "-webkit-print-color-adjust: exact" in page


def test_the_printed_page_is_light_whatever_the_screen_was():
    """Both dark blocks have to be overridden, and the `[data-theme]` one has
    higher specificity than a bare `:root`, so the print block must name it.

    The printed `--ground` is `#FFFFFF`, not the light theme's own `#F6F8F7`:
    with `print-color-adjust: exact` forcing it onto paper, the screen's
    off-white ground lays down as a tinted rectangle inside white page
    margins — ink spent on nothing, and cards that should read by their
    borders instead read as a printing fault. This is deliberate; do not
    "correct" it back to the screen value."""
    page = render_html(real_report(), META)
    printed = page.split("@media print", 1)[1]

    assert ':root[data-theme="dark"]' in printed
    assert "--ground:#FFFFFF" in printed


def test_an_answer_block_is_not_split_across_pages():
    """Chromium honours `break-inside: avoid` on block boxes and routinely
    ignores it on flex containers — and `.tx`, the class the transcript
    cards actually render with (`real_report()` has no narrative, so `.qa`
    never even appears in this document), is a flex column on screen. The
    rule only binds if these are also forced to `display: block` for
    print."""
    page = render_html(real_report(), META)
    printed = page.split("@media print", 1)[1]

    assert "break-inside: avoid" in printed
    assert ".tx" in printed
    assert "display: block" in printed


# ---------------------------------------------------- the closing is not optional


def test_the_closing_is_on_the_page_with_no_model_at_all():
    """The arithmetic behind the band is derived, so it survives `--no-llm`.

    This is the section a candidate reads to find out why the letter at the top
    is that letter, and it must not be one of the parts that disappears when
    nothing was available to write prose.
    """
    report = real_report()

    page = render_html(report, META)

    assert "요약과 이 등급이 나온 이유" in page
    assert '<div class="why">' in page
    for step in report.closing.steps:
        assert html.escape(step.detail_ko, quote=True) in page
    for highlight in report.closing.highlights:
        assert html.escape(highlight, quote=True) in page


def test_the_closing_ends_on_the_band_the_masthead_opened_with():
    report = real_report()

    page = render_html(report, META)

    closing = page.split("요약과 이 등급이 나온 이유", 1)[1]
    assert f'<div class="why__lvl">{report.final_level.name}</div>' in closing
