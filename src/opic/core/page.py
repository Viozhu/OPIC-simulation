"""The report as a standalone page, built from the same `Report` as everything else.

The third renderer of one model. `render_text` prints it to a terminal,
`done.js` draws it in the browser during the exam, and this writes a file the
candidate can keep, reread and hand to a teacher. None of the three decides a
score; all three read what `report.py` derived.

The page is self-contained apart from webfonts: one `<style>`, no script, no
image. Both themes are defined, because a report opened in six months should
not depend on what the machine's appearance setting was when it was written.

A `Narrative` is optional. Without one the page keeps every section a second
reading of `result.json` can support and drops the ones that require judgement
— the named error patterns, the weakest-question-type finding, and the
AL-level rewrites. It never fills them with prose that would be true of any
exam.
"""

from __future__ import annotations

import html
from collections import Counter
from dataclasses import dataclass

from opic.core.metrics import LOW_CONFIDENCE_THRESHOLD
from opic.core.narrative import Narrative
from opic.core.report import (
    METRIC_LABELS_KO,
    AnswerReport,
    Report,
    format_metrics,
)
from opic.core.rubric import ActflLevel, Dimension, DIMENSION_LABELS_KO

# The order the five levels are printed in, everywhere on the page: the table
# columns, the chips on an answer, and the legend that names them. One tuple so
# a reader who learns the order once can rely on it.
CHIP_ORDER: tuple[Dimension, ...] = (
    Dimension.RELEVANCE,
    Dimension.VOCABULARY,
    Dimension.COHERENCE,
    Dimension.FLUENCY,
    Dimension.GRAMMAR,
)

BANDS: tuple[ActflLevel, ...] = tuple(sorted(ActflLevel, key=lambda b: b.rank))

LEVEL_NOTES_KO: dict[ActflLevel, str] = {
    ActflLevel.NL: "초급 하. 아직 단어와 짧은 구로 답하는 단계입니다.",
    ActflLevel.NM: "초급 중. 익숙한 소재에서 짧은 문장이 나오는 단계입니다.",
    ActflLevel.NH: "초급 상. 문장이 이어지기 시작하지만 아직 끊어집니다.",
    ActflLevel.IL: "중급 하. 익숙한 주제라면 문장으로 답할 수 있는 단계입니다.",
    ActflLevel.IM1: "중급 중, 첫 번째 단계입니다. 대화가 되는 선은 넘었고, "
    "문법이 더 이상 발목을 잡지 않는 지점에는 아직 못 미쳤습니다.",
    ActflLevel.IM2: "중급 중, 두 번째 단계입니다. 문장이 길어지고 "
    "이야기를 이어갈 수 있습니다.",
    ActflLevel.IM3: "중급 중, 세 번째 단계입니다. 문단으로 말하기에 가까워졌습니다.",
    ActflLevel.IH: "중급 상. 문단으로 말하고, 예상 밖의 질문도 처리합니다.",
    ActflLevel.AL: "고급 하. 시제를 모두 다루고, 복잡한 상황을 설명할 수 있습니다.",
}

PRONUNCIATION_CAVEAT_KO = (
    "리포트의 <code>mean_confidence</code>와 <code>low_confidence_rate</code>는 "
    "음성 인식기 Whisper의 확신도입니다 — 기계가 얼마나 확실하게 알아들었는지를 "
    "재는 값이고, 발음과 상관관계는 있지만 발음을 평가하지는 않습니다. "
    "점수로 읽지 마세요."
)

INVENTED_WARNING_KO = (
    "이 답변에는 원래 답변에 없던 <b>지어낸 내용</b>이 들어 있습니다 — "
    "질문이 요구한 구체적인 경험이거나, 문장을 채우기 위해 더한 세부 사항입니다. "
    "문장 구조만 참고하고, 내용은 본인에게 실제로 있었던 일로 바꿔 넣으세요."
)


@dataclass(frozen=True, slots=True)
class Meta:
    """What the page says about the exam that the report itself does not carry."""

    session_id: str
    seed: int | None = None
    self_assessed_ko: str | None = None
    target_level: str | None = None


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def render_html(
    report: Report, meta: Meta, narrative: Narrative | None = None
) -> str:
    """The whole page, as one string."""
    parts: list[str] = [
        _HEAD,
        f"<title>OPIc {report.final_level.name} 리포트</title>",
        "<style>",
        PAGE_CSS,
        "</style>",
        '',
        '<div class="wrap">',
        _mast(report, meta),
        _verdict(report, narrative),
        _dimensions(report, narrative),
        _distribution(report, narrative),
    ]
    if narrative is not None and narrative.analysis is not None:
        parts.append(_patterns(narrative))
        parts.append(_gap(report, narrative))
    parts.append(_splits(report, narrative))
    parts.append(_sound(report, narrative))
    parts.append(_table(report))
    parts.append(_answers(report, narrative))
    parts.append(_closing(report, narrative))
    parts.append(_caveats(report, narrative))
    parts.append(_footer(report, meta))
    parts.append("</div>")
    parts.append("</html>")
    return "\n".join(part for part in parts if part)


# ------------------------------------------------------------------ components


def _gauge(level: ActflLevel, small: bool = False) -> str:
    """The nine-band scale with one band lit.

    Every band is drawn, including the ones nobody reached — the same reason
    `report.scale` keeps its empty rungs. "IM1" says nothing until you can see
    it sits fifth of nine.
    """
    segments = []
    for band in BANDS:
        if band is level:
            state = "is-hit"
        elif band.rank < level.rank:
            state = "is-under"
        else:
            state = "is-over"
        segments.append(f'<span class="gauge__seg {state}"></span>')
    classes = "gauge gauge--sm" if small else "gauge"
    return (
        f'<div class="{classes}" role="img" aria-label="ACTFL {level.name}">'
        + "".join(segments)
        + "</div>"
    )


def _chip(level: ActflLevel) -> str:
    return f'<span class="chip chip--{level.name.lower()}">{level.name}</span>'


def _prose(text: str | None, klass: str = "col") -> str:
    """A narrative paragraph, or nothing at all.

    The prose arrives already written in Korean and may carry the small amount
    of inline markup the schema allows (`<b>`, `<code>`), so it is not escaped
    here; the adapter is what decides a narrative is acceptable.
    """
    return f'<p class="{klass}">{text}</p>' if text else ""


def _sec_head(title: str, blurb: str | None = None) -> str:
    inner = f"<h2>{title}</h2>"
    if blurb:
        inner += f"\n    <p>{blurb}</p>"
    return f'  <div class="sec-head">\n    {inner}\n  </div>'


def _analysis(narrative: Narrative | None):
    return narrative.analysis if narrative is not None else None


# -------------------------------------------------------------------- sections


def _mast(report: Report, meta: Meta) -> str:
    spoken = sum(
        a.metrics.duration_s for a in report.answers if a.metrics is not None
    )
    strip = [f"세션 <b>{esc(meta.session_id)}</b>"]
    strip.append(f"답변 <b>{report.scored_answers}/{report.expected_answers}</b>")
    strip.append(f"발화 <b>{spoken / 60:.0f}분</b>")
    if meta.self_assessed_ko:
        strip.append(f"자기 평가 <b>{esc(meta.self_assessed_ko)}</b>")
    if meta.target_level:
        strip.append(f"문항 목표 <b>{esc(meta.target_level)}</b>")
    spans = "\n    ".join(f"<span>{item}</span>" for item in strip)
    graded = sum(len(a.scores) for a in report.answers)
    return f"""
<header class="mast">
  <div class="mast__strip">
    {spans}
  </div>
  <h1>OPIc 모의고사 결과</h1>
  <p class="mast__sub">{report.expected_answers}개 문항, 문항마다 {len(CHIP_ORDER)}개 영역 —
  ACTFL {len(BANDS)}단계 척도 위의 {graded}개 평가입니다.</p>
</header>"""


def _verdict(report: Report, narrative: Narrative | None) -> str:
    analysis = _analysis(narrative)
    note = (
        analysis.verdict_ko
        if analysis is not None
        else LEVEL_NOTES_KO[report.final_level]
    )
    labels = "".join(
        f'<span class="ladder__lab{" is-cur" if band is report.final_level else ""}">'
        f"{band.name}</span>"
        for band in BANDS
    )
    return f"""
<div class="verdict">
  <div class="verdict__top">
    <div class="verdict__lvl">{report.final_level.name}</div>
    <p class="verdict__note">{note}</p>
  </div>
  <div class="ladder">
    <div class="eyebrow">전체 척도</div>
    {_gauge(report.final_level)}
    <div class="ladder__labs">{labels}</div>
  </div>
</div>"""


def _dimensions(report: Report, narrative: Narrative | None) -> str:
    analysis = _analysis(narrative)
    rows = []
    for dimension in report.dimensions:
        comment = _first_comment(report, dimension.dimension)
        rows.append(
            f"""    <div class="dim">
      <div class="dim__top">
        <div class="dim__name"><span class="dim__ko">{esc(dimension.label_ko)}</span>"""
            f"""<span class="dim__es">{dimension.weight:.0%}</span></div>
        {_gauge(dimension.level, small=True)}
        {_chip(dimension.level)}
      </div>
      {comment}
    </div>"""
        )
    limiting = ""
    if report.limiting is not None:
        limiting = _prose(
            f"최종 등급은 {esc(report.limiting.label_ko)}에 의해 한 단계 "
            f"낮아졌습니다. 그 제한이 없었다면 "
            f"<b>{report.limiting.without_cap.name}</b>입니다."
        )
    lede = analysis.dimensions_lede_ko if analysis is not None else None
    close = _prose(analysis.dimensions_close_ko) if analysis is not None else ""
    body = "\n".join(rows)
    return f"""
<section>
{_sec_head("영역별 등급", lede)}
  <div class="dims">
{body}
  </div>
  {limiting}
  {close}
</section>"""


def _first_comment(report: Report, dimension: Dimension) -> str:
    """The rater's own sentence for this dimension, from the earliest answer.

    Already on disk, so the page quotes it rather than asking a model to
    summarise five things a model already said.
    """
    for answer in report.answers:
        for score in answer.scores:
            if score.dimension is dimension and score.comment_ko:
                return (
                    f'<p class="dim__cm"><b>{answer.index:02d}번</b>'
                    f"{esc(score.comment_ko)}</p>"
                )
    return ""


def _distribution(report: Report, narrative: Narrative | None) -> str:
    analysis = _analysis(narrative)
    counts = Counter(
        score.level for answer in report.answers for score in answer.scores
    )
    total = sum(counts.values())
    top = max(counts.values()) if counts else 0
    rows = []
    for band in BANDS:
        count = counts.get(band, 0)
        width = (count / top * 100) if top else 0.0
        zero = " is-zero" if count == 0 else ""
        rows.append(
            f"""    <div class="dist__row{zero}">
      <span class="dist__lab">{band.name}</span>
      <span class="dist__bar"><span style="width:{width:.1f}%"></span></span>
      <span class="dist__n">{count}</span></div>"""
        )
    body = "\n".join(rows)
    note = _prose(analysis.distribution_ko) if analysis is not None else ""
    return f"""
<section>
{_sec_head(f"{total}개 평가가 어디에 떨어졌는가")}
  <div class="dist">
{body}
  </div>
  {note}
</section>"""


def _patterns(narrative: Narrative) -> str:
    analysis = narrative.analysis
    if analysis is None or not analysis.patterns:
        return ""
    total = sum(len(pattern.items) for pattern in analysis.patterns)
    cards = []
    for pattern in analysis.patterns:
        items = "".join(
            f'<li class="ev"><span class="ev__n">{item.answer_index:02d}</span>'
            f'<span class="ev__bad">{esc(item.quote)}</span>'
            f'<span class="ev__arrow" aria-hidden="true">→</span>'
            f'<span class="ev__good">{esc(item.correction_en)}</span>'
            f'<span class="ev__ko">{esc(item.issue_ko)}</span></li>'
            for item in pattern.items
        )
        cards.append(
            f"""      <article class="pat">
        <header class="pat__head">
          <h3 class="pat__title">{pattern.title_ko}</h3>
          <span class="pat__count">{total}개 중 <b>{len(pattern.items)}</b></span>
        </header>
        <p class="pat__blurb">{pattern.blurb_ko}</p>
        <ul class="ev-list">{items}</ul>
      </article>"""
        )
    body = "\n".join(cards)
    return f"""
<section>
{_sec_head(
    f"{total}개의 오류는 {len(analysis.patterns)}가지 유형입니다",
    "공부할 것이 하나씩 흩어져 있지 않습니다. 평가자가 지적한 오류는 "
    "답변마다 반복되는 몇 개의 유형 안에 들어갑니다.",
)}
  <div class="pats">
{body}</div>
  {_prose(analysis.patterns_close_ko)}
</section>"""


def _gap(report: Report, narrative: Narrative) -> str:
    analysis = narrative.analysis
    if analysis is None or analysis.gap is None:
        return ""
    gap = analysis.gap
    by_index = {answer.index: answer for answer in report.answers}
    blocks = []
    for index in gap.answer_indexes:
        answer = by_index.get(index)
        if answer is None or answer.state != "scored":
            continue
        relevance = next(
            (s for s in answer.scores if s.dimension is Dimension.RELEVANCE), None
        )
        comment = ""
        if relevance is not None:
            comment = (
                f'<p class="qa__ko"><span class="qa__tag">평가자 코멘트 · '
                f"{esc(DIMENSION_LABELS_KO[Dimension.RELEVANCE])}</span>"
                f"{esc(relevance.comment_ko)}</p>"
            )
        chip = _chip(relevance.level) if relevance is not None else ""
        blocks.append(
            f"""      <div class="qa">
        <div class="qa__meta"><span class="qa__n">{answer.index:02d}</span>
          <span class="qa__slot">{esc(_slot_label(answer))}</span>
          {chip}</div>
        <p class="qa__q"><span class="qa__tag">질문</span>"""
            f"""{esc(answer.question_en)}</p>
        <p class="qa__a"><span class="qa__tag">답변</span>"""
            f"""{esc(answer.transcript_text)}</p>
        {comment}
      </div>"""
        )
    body = "\n".join(blocks)
    return f"""
<section>
{_sec_head(gap.title_ko, gap.blurb_ko)}
{body}
  {_prose(gap.close_ko)}
</section>"""


def _slot_label(answer: AnswerReport) -> str:
    label = answer.qtype_label_ko
    if answer.topic_label_ko:
        label += f" · {answer.topic_label_ko}"
    return label


def _splits(report: Report, narrative: Narrative | None) -> str:
    analysis = _analysis(narrative)

    def mini(rows) -> str:
        return "".join(
            f'<div class="mini"><span class="mini__k">{esc(label)}</span>'
            f"{_gauge(level, small=True)}{_chip(level)}</div>"
            for _, label, level in rows
        )

    close = _prose(analysis.splits_close_ko) if analysis is not None else ""
    return f"""
<section>
{_sec_head("유형별 · 주제별")}
  <div class="splits">
    <div class="split"><h3>문항 유형별</h3>{mini(report.by_type)}</div>
    <div class="split"><h3>주제별</h3>{mini(report.by_topic)}</div>
  </div>
  {close}
</section>"""


def _sound(report: Report, narrative: Narrative | None) -> str:
    analysis = _analysis(narrative)
    if report.averages is None:
        return ""
    scored = [a for a in report.answers if a.metrics is not None]
    words = sum(a.metrics.word_count for a in scored)
    display = format_metrics(report.averages)
    stats = [
        (f"{report.averages.words_per_minute:.0f}", "분당 단어 수", "원어민 140–160"),
        (f"{report.averages.pause_ratio:.0%}", "침묵 비율", "말하지 않은 시간"),
        (
            f"{report.averages.mean_utterance_length:.1f}",
            "평균 발화 길이",
            "한 번에 이어 말한 단어",
        ),
        (f"{words:,.0f}", "총 발화 단어", f"{len(scored)}개 답변 합계"),
    ]
    tiles = "\n    ".join(
        f'<div class="stat"><span class="stat__v">{value}</span>'
        f'<span class="stat__k">{key}</span>'
        f'<span class="stat__n">{note}</span></div>'
        for value, key, note in stats
    )

    weak = _weak_indexes(narrative)
    top = max((a.metrics.words_per_minute for a in scored), default=0) or 1
    bars = "".join(
        f'<div class="bar{" is-weak" if a.index in weak else ""}" '
        f'style="--h:{a.metrics.words_per_minute / top * 100:.1f}%" '
        f'title="{a.index:02d}: {a.metrics.words_per_minute:.0f} wpm">'
        f'<span class="bar__n">{a.index:02d}</span></div>'
        for a in scored
    )
    mean_at = report.averages.words_per_minute / top * 100
    foot = (
        "빨간 점선 = 위에서 짚은 답변"
        if weak
        else f"점선 = 평균 {report.averages.words_per_minute:.0f} wpm"
    )
    plot_columns = len(scored) or 1
    unclear = _unclear_block(report)
    note = _prose(analysis.sound_ko) if analysis is not None else ""
    metrics_note = " · ".join(
        f"{label} {display[field]}" for field, label in METRIC_LABELS_KO.items()
    )
    return f"""
<section>
{_sec_head("어떻게 들리는가", "평가자의 판단이 아니라, 음성에서 직접 측정한 수치입니다.")}
  <div class="stats">
    {tiles}
  </div>
  <div class="chart">
    <div class="eyebrow">답변별 발화 속도</div>
    <div class="chart__plot" style="--cols:{plot_columns}">
      <div class="chart__mean" style="bottom:{mean_at:.1f}%"><span>평균 {report.averages.words_per_minute:.0f}</span></div>
      {bars}
    </div>
    <div class="chart__foot">{foot}</div>
  </div>
  <p class="col metrics-line">{esc(metrics_note)}</p>
{unclear}
  {note}
</section>"""


def _weak_indexes(narrative: Narrative | None) -> frozenset[int]:
    analysis = _analysis(narrative)
    if analysis is None or analysis.gap is None:
        return frozenset()
    return frozenset(analysis.gap.answer_indexes)


def _unclear_block(report: Report) -> str:
    if not report.unclear:
        return ""
    rows = "".join(
        f'<li class="unc"><span class="unc__w">{esc(word.text.strip())}</span>'
        f'<span class="unc__p">{word.probability:.0%}</span>'
        f'<span class="unc__c">…{esc(word.context.strip())}…</span>'
        f'<span class="unc__n">{word.answer_index:02d}</span></li>'
        for word in report.unclear
    )
    return f"""  <div class="unclear">
    <div class="eyebrow">또렷하게 인식되지 않은 단어</div>
    <ul class="unc-list">{rows}</ul>
  </div>"""


def _table(report: Report) -> str:
    heads = "".join(
        f"<th>{esc(DIMENSION_LABELS_KO[dimension])}</th>" for dimension in CHIP_ORDER
    )
    rows = []
    for answer in report.answers:
        if answer.state != "scored" or answer.metrics is None:
            rows.append(
                f"""      <tr>
      <td class="num">{answer.index:02d}</td>
      <td class="ty">{esc(answer.qtype_label_ko)}</td>
      <td class="tp">{esc(answer.topic_label_ko or "—")}</td>
      <td colspan="{len(CHIP_ORDER) + 3}" class="tp">"""
                f"""{esc(answer.state_label_ko)}</td></tr>"""
            )
            continue
        levels = {score.dimension: score.level for score in answer.scores}
        chips = "".join(
            f"<td>{_chip(levels[d])}</td>" if d in levels else "<td>—</td>"
            for d in CHIP_ORDER
        )
        ranks = [level.rank for level in levels.values()]
        mean = sum(ranks) / len(ranks) if ranks else 0
        rows.append(
            f"""      <tr>
      <td class="num">{answer.index:02d}</td>
      <td class="ty">{esc(answer.qtype_label_ko)}</td>
      <td class="tp">{esc(answer.topic_label_ko or "—")}</td>
      {chips}
      <td class="num">{answer.metrics.words_per_minute:.0f}</td>
      <td class="num">{answer.metrics.duration_s:.0f}s</td>
      <td class="num avg">{mean:.1f}</td></tr>"""
        )
    body = "\n".join(rows)
    return f"""
<section>
{_sec_head(
    f"{report.expected_answers}개 답변 전체",
    "평가자가 매긴 그대로의 등급입니다. 마지막 열은 "
    f"{len(BANDS)}단계 척도 위의 평균 순위입니다.",
)}
  <div class="tablewrap">
    <table>
      <thead><tr>
        <th class="num">#</th><th>유형</th><th>주제</th>
        {heads}
        <th class="num">wpm</th><th class="num">길이</th><th class="num">평균</th>
      </tr></thead>
      <tbody>
{body}
      </tbody>
    </table>
  </div>
</section>"""


def _marked(answer: AnswerReport) -> str:
    """The transcript, word for word, with the recogniser's doubts visible.

    Built from the word stream rather than `transcript_text` so a low
    confidence can be shown where it happened. The words concatenate back to
    exactly the text the rater read — the page never edits what was said.
    """
    if not answer.transcript_words:
        return esc(answer.transcript_text)
    out: list[str] = []
    for word in answer.transcript_words:
        body = word.text.lstrip()
        out.append(word.text[: len(word.text) - len(body)])
        if word.probability < LOW_CONFIDENCE_THRESHOLD:
            out.append(
                f'<span class="lo" title="확신도 {word.probability:.0%}">'
                f"{esc(body)}</span>"
            )
        else:
            out.append(esc(body))
    return "".join(out).strip()


def _answers(report: Report, narrative: Narrative | None) -> str:
    rewrites = narrative is not None and narrative.rewrites
    words = sum(len(a.transcript_words) for a in report.answers)
    low = sum(
        1
        for a in report.answers
        for w in a.transcript_words
        if w.probability < LOW_CONFIDENCE_THRESHOLD
    )
    blurb = (
        "평가자가 본 것은 음성이 아니라 이 텍스트입니다. Whisper가 받아쓴 문자열 "
        "그대로이며, 문장 부호와 띄어쓰기도 손대지 않았습니다. 점선 밑줄은 "
        f"인식기의 확신도가 {LOW_CONFIDENCE_THRESHOLD:.0%} 미만인 단어 — "
        f"{words:,}단어 중 <b>{low}개</b>입니다. 발음 평가가 아니라, 기계가 "
        "어디서 망설였는지를 보여주는 표시입니다."
    )
    if rewrites:
        blurb += (
            f" 세 번째 블록은 같은 내용을 <b>{ActflLevel.AL.name}</b>"
            f"({len(BANDS)}단계 중 가장 높은 등급)을 목표로 다시 쓴 예시입니다. "
            "채점된 답변이 아니라 학습용 예시입니다."
        )
    legend = "".join(
        f"<span><b>{position}</b> {esc(DIMENSION_LABELS_KO[dimension])}</span>"
        for position, dimension in enumerate(CHIP_ORDER, start=1)
    )
    blocks = []
    for answer in report.answers:
        blocks.append(_answer_block(answer, narrative))
    body = "\n".join(blocks)
    title = "질문 · 답변 · AL 목표 답변" if rewrites else "질문과 답변, 인식된 그대로"
    return f"""
<section>
{_sec_head(title, blurb)}
  <div class="legend"><span>등급 순서</span>{legend}</div>
  <div class="txs">
{body}
  </div>
</section>"""


def _answer_block(answer: AnswerReport, narrative: Narrative | None) -> str:
    if answer.state != "scored":
        return f"""    <article class="tx tx--dead">
      <div class="tx__meta">
        <span class="tx__n">{answer.index:02d}</span>
        <span class="tx__slot">{esc(_slot_label(answer))}</span>
        <span class="tx__num">{esc(answer.state_label_ko)}</span>
      </div>
      <p class="tx__q"><span class="qa__tag">질문</span>{esc(answer.question_en)}</p>
    </article>"""

    levels = {score.dimension: score.level for score in answer.scores}
    chips = "".join(_chip(levels[d]) for d in CHIP_ORDER if d in levels)
    numbers = ""
    if answer.metrics is not None:
        numbers = (
            f"{answer.metrics.words_per_minute:.0f} wpm · "
            f"{answer.metrics.duration_s:.0f}s · "
            f"{answer.metrics.word_count:.0f}단어"
        )
    rewrite = narrative.rewrite_for(answer.index) if narrative is not None else None
    extra = ""
    if rewrite is not None:
        warning = (
            f'<p class="tx__made">{INVENTED_WARNING_KO}</p>'
            if rewrite.invented
            else ""
        )
        extra = (
            f'\n      <p class="tx__al"><span class="qa__tag">AL 목표 답변</span>'
            f"{esc(rewrite.text_en)}</p>{warning}"
            f'\n      <p class="tx__why"><span class="qa__tag">무엇이 달라졌나</span>'
            f"{rewrite.why_ko}</p>"
        )
    return f"""    <article class="tx">
      <div class="tx__meta">
        <span class="tx__n">{answer.index:02d}</span>
        <span class="tx__slot">{esc(_slot_label(answer))}</span>
        {chips}
        <span class="tx__num">{numbers}</span>
      </div>
      <p class="tx__q"><span class="qa__tag">질문</span>{esc(answer.question_en)}</p>
      <p class="tx__a"><span class="qa__tag">인식된 답변</span>{_marked(answer)}</p>{extra}
    </article>"""


def _closing(report: Report, narrative: Narrative | None) -> str:
    """The last word: the report read back, and the arithmetic behind the band.

    Both halves are derived, so this section is here whether or not a model
    wrote anything. A narrative adds the two things the arithmetic cannot say —
    what the exam showed, and which of the steps actually decided the outcome —
    around the same numbers rather than instead of them.
    """
    analysis = _analysis(narrative)
    closing = report.closing
    highlights = "\n".join(
        f"    <li>{esc(item)}</li>" for item in closing.highlights
    )
    steps = "\n".join(
        f"""      <div class="step{' step--final' if step is closing.steps[-1] else ''}">
        <span class="step__k">{esc(step.label_ko)}</span>
        <span class="step__v">{esc(step.detail_ko)}</span>
      </div>"""
        for step in closing.steps
    )
    recap = _prose(analysis.closing_recap_ko) if analysis is not None else ""
    why = _prose(analysis.closing_why_ko) if analysis is not None else ""
    return f"""
<section>
{_sec_head(
    "요약과 이 등급이 나온 이유",
    "위에서 나온 것들을 한 번에 다시 읽고, 최종 등급이 어떻게 계산되었는지 봅니다.",
)}
  {recap}
  <ul class="recap">
{highlights}
  </ul>
  <div class="why">
    <div class="why__head">
      <div class="eyebrow">계산 과정</div>
      <div class="why__lvl">{closing.final_level.name}</div>
      {_gauge(closing.final_level, small=True)}
    </div>
    <div class="why__steps">
{steps}
    </div>
  </div>
  {why}
</section>"""


def _caveats(report: Report, narrative: Narrative | None) -> str:
    analysis = _analysis(narrative)
    items = [("발음은 점수가 아닙니다", PRONUNCIATION_CAVEAT_KO)]
    if analysis is not None:
        items.extend((c.title_ko, c.body_ko) for c in analysis.caveats)
    body = "\n".join(
        f"""    <div class="cav">
      <h3>{title}</h3>
      <p>{text}</p>
    </div>"""
        for title, text in items
    )
    return f"""
<section>
{_sec_head(
    "이 리포트에 대한 유의사항",
    "시험이 아니라, 측정 도구 자체의 한계입니다.",
)}
  <div class="caveats">
{body}
  </div>
</section>"""


def _mean_confidence(report: Report) -> float | None:
    """What the recogniser was, on average, sure of.

    Computed here from the word stream rather than read from a field, because
    the report model does not carry it and should not: it is a property of the
    recording, not of the grade. Printed in the footer as provenance, never as
    a score — see `PRONUNCIATION_CAVEAT_KO`.
    """
    probabilities = [
        word.probability for answer in report.answers for word in answer.transcript_words
    ]
    if not probabilities:
        return None
    return sum(probabilities) / len(probabilities)


def _footer(report: Report, meta: Meta) -> str:
    bits = [f"세션 {esc(meta.session_id)}"]
    if meta.seed is not None:
        bits.append(f"시드 {meta.seed}")
    bits.append("ACTFL · " + " · ".join(band.name for band in BANDS))
    confidence = _mean_confidence(report)
    if confidence is not None:
        bits.append(f"인식 확신도 {confidence:.3f}")
    spans = "\n  ".join(f"<span>{bit}</span>" for bit in bits)
    return f"""
<footer>
  {spans}
</footer>"""


# The document opening lives here and not in a caller: this page is written to
# a file the candidate keeps, and a file opened from a desktop over file:// has
# nobody to declare its encoding for it. The doctype earns its keep too — an
# iframe with no doctype renders in quirks mode.
_HEAD = """<!doctype html>
<html lang="ko">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?\
family=JetBrains+Mono:wght@400;500;700&family=Noto+Sans+KR:wght@400;500;700\
&family=Noto+Serif+KR:wght@400;600&display=swap">"""


# The colour tokens, rules and shadows below are copied into
# `static/style.css`'s own `:root` block, values and names both, so the exam
# and this report read as one product even though the exam serves that file
# standalone (no server, no import — see the comment there). Change one,
# change the other.
#
# The type is where the two are allowed to diverge, deliberately, and it is
# the only such divergence: this page is a document and reads as one, so it
# keeps a serif body and hosted webfonts. `static/style.css` is an interface,
# not a document, and stays sans-serif with system fonts only — a decision
# made there, not a gap here.
PAGE_CSS = """
:root {
  --ground:#F6F8F7; --surface:#FFFFFF; --sunk:#EEF2F1;
  --ink:#10201E; --ink-2:#4A5C5A; --ink-3:#7C8C8A;
  --rule:#DCE4E2; --rule-2:#C6D2D0;
  --accent:#0F6E6E; --accent-soft:#DDECEB; --accent-ink:#0B5252;
  --crit:#9B382C; --warn:#8A5806; --good:#2C6B4F;
  --shadow:0 1px 2px rgba(16,32,30,.05), 0 8px 24px -16px rgba(16,32,30,.18);
  --display:"Noto Sans KR", ui-sans-serif, system-ui, sans-serif;
  --body:"Noto Serif KR", Georgia, serif;
  --mono:"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  color-scheme: light dark;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground:#0C1312; --surface:#131D1C; --sunk:#0F1817;
    --ink:#E6EDEC; --ink-2:#9FB1AF; --ink-3:#6F817E;
    --rule:#253331; --rule-2:#33443F;
    --accent:#48B3AE; --accent-soft:#15302F; --accent-ink:#7FD0CB;
    --crit:#D9776A; --warn:#D0973A; --good:#62B98C;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"] {
  --ground:#0C1312; --surface:#131D1C; --sunk:#0F1817;
  --ink:#E6EDEC; --ink-2:#9FB1AF; --ink-3:#6F817E;
  --rule:#253331; --rule-2:#33443F;
  --accent:#48B3AE; --accent-soft:#15302F; --accent-ink:#7FD0CB;
  --crit:#D9776A; --warn:#D0973A; --good:#62B98C;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -16px rgba(0,0,0,.7);
}

* { box-sizing:border-box; }
body {
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--body); font-size:16.5px; line-height:1.85;
  word-break:keep-all; overflow-wrap:break-word;
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:1080px; margin:0 auto; padding:0 24px 96px; }
.col { max-width:40em; }
h1,h2,h3,h4 { font-family:var(--display); margin:0; word-break:keep-all;
  letter-spacing:-.02em; line-height:1.4; }
p { margin:0; }
code { font-family:var(--mono); font-size:.86em; background:var(--sunk);
  padding:.1em .35em; border-radius:3px; word-break:break-all; }
b, strong { font-weight:700; }

.mast { border-bottom:1px solid var(--rule); padding:40px 0 28px; margin-bottom:44px;
  display:flex; flex-direction:column; gap:22px; }
.mast__strip { display:flex; flex-wrap:wrap; gap:8px 22px; font-family:var(--mono);
  font-size:11.5px; letter-spacing:.06em; color:var(--ink-3); }
.mast__strip b { color:var(--ink-2); font-weight:500; }
.mast h1 { font-size:clamp(28px,4.4vw,44px); font-weight:700; line-height:1.2; }
.mast__sub { color:var(--ink-2); font-size:17.5px; max-width:34em; }

.verdict { background:var(--surface); border:1px solid var(--rule); border-radius:4px;
  box-shadow:var(--shadow); padding:30px 30px 24px;
  display:flex; flex-direction:column; gap:26px; }
.verdict__top { display:flex; flex-wrap:wrap; align-items:baseline; gap:14px 24px; }
.verdict__lvl { font-family:var(--mono); font-size:clamp(48px,7.5vw,70px); font-weight:700;
  letter-spacing:-.04em; line-height:.95; color:var(--accent); }
.verdict__note { color:var(--ink-2); font-size:16px; max-width:30em; }
.eyebrow { font-family:var(--mono); font-size:11px; letter-spacing:.12em;
  text-transform:uppercase; color:var(--ink-3); }

.ladder { display:flex; flex-direction:column; gap:9px; }
.gauge { display:grid; grid-template-columns:repeat(9,1fr); gap:3px; }
.gauge__seg { height:30px; border-radius:2px; background:var(--sunk);
  border:1px solid transparent; }
.gauge__seg.is-under { background:var(--accent-soft); }
.gauge__seg.is-hit { background:var(--accent); box-shadow:0 0 0 1px var(--accent); }
.gauge__seg.is-over { background:transparent; border-color:var(--rule); }
.gauge--sm { gap:2px; min-width:150px; }
.gauge--sm .gauge__seg { height:11px; border-radius:1px; }
.ladder__labs { display:grid; grid-template-columns:repeat(9,1fr); gap:3px; }
.ladder__lab { font-family:var(--mono); font-size:11px; color:var(--ink-3);
  text-align:center; }
.ladder__lab.is-cur { color:var(--accent-ink); font-weight:700; }

section { margin-top:64px; display:flex; flex-direction:column; gap:22px; }
.sec-head { display:flex; flex-direction:column; gap:9px;
  border-top:2px solid var(--ink); padding-top:14px; }
.sec-head h2 { font-size:clamp(21px,2.9vw,28px); font-weight:700; }
.sec-head p { color:var(--ink-2); max-width:38em; }

.dims { display:flex; flex-direction:column;
  border:1px solid var(--rule); border-radius:4px; background:var(--surface);
  overflow:hidden; }
.dim { padding:16px 20px; border-bottom:1px solid var(--rule);
  display:flex; flex-direction:column; gap:9px; }
.dim:last-child { border-bottom:0; }
.dim__top { display:grid; grid-template-columns:minmax(120px,1fr) minmax(160px,1.3fr) auto;
  align-items:center; gap:18px; }
.dim__name { display:flex; flex-direction:column; gap:0; }
.dim__ko { font-family:var(--display); font-weight:700; font-size:17px; }
.dim__es { font-family:var(--mono); font-size:10.5px; letter-spacing:.06em;
  color:var(--ink-3); }
.dim__cm { font-size:14.5px; color:var(--ink-2); max-width:44em; }
.dim__cm b { font-family:var(--mono); font-size:10.5px; color:var(--ink-3);
  font-weight:500; letter-spacing:.06em; margin-right:7px; }
@media (max-width:620px) {
  .dim__top { grid-template-columns:1fr auto; }
  .dim__top .gauge--sm { grid-column:1 / -1; }
}

.chip { font-family:var(--mono); font-size:11.5px; font-weight:700; letter-spacing:.04em;
  padding:3px 8px; border-radius:3px; background:var(--sunk); color:var(--ink-2);
  border:1px solid var(--rule); display:inline-block; line-height:1.5; }
.chip--al, .chip--ih { background:var(--accent-soft); color:var(--accent-ink);
  border-color:transparent; }
.chip--im3, .chip--im2 { color:var(--good); border-color:var(--rule-2); }
.chip--il, .chip--nh, .chip--nm, .chip--nl { background:transparent; color:var(--crit);
  border-color:var(--crit); }

.dist { display:flex; flex-direction:column; gap:5px; font-family:var(--mono);
  font-size:12px; }
.dist__row { display:grid; grid-template-columns:34px 1fr 28px; align-items:center;
  gap:12px; }
.dist__row.is-zero { opacity:.4; }
.dist__lab { color:var(--ink-2); }
.dist__bar { height:9px; background:var(--sunk); border-radius:2px; overflow:hidden; }
.dist__bar span { display:block; height:100%; background:var(--accent); border-radius:2px; }
.dist__n { text-align:right; color:var(--ink-3); font-variant-numeric:tabular-nums; }

.pats { display:flex; flex-direction:column; gap:14px; }
.pat { background:var(--surface); border:1px solid var(--rule); border-radius:4px;
  padding:20px 22px; display:flex; flex-direction:column; gap:12px; }
.pat__head { display:flex; align-items:baseline; justify-content:space-between;
  gap:16px; flex-wrap:wrap; }
.pat__title { font-size:18px; font-weight:700; }
.pat__count { font-family:var(--mono); font-size:11px; letter-spacing:.06em;
  color:var(--ink-3); white-space:nowrap; }
.pat__count b { color:var(--accent-ink); font-weight:700; font-size:13px; }
.pat__blurb { color:var(--ink-2); font-size:15px; max-width:40em; }
.ev-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; }
.ev { display:grid; grid-template-columns:auto 1fr auto 1fr; align-items:baseline;
  gap:5px 12px; padding:10px 0; border-top:1px solid var(--rule);
  font-family:var(--mono); font-size:12.5px; line-height:1.55; }
.ev__n { color:var(--ink-3); font-size:10.5px; }
.ev__bad { color:var(--crit); }
.ev__arrow { color:var(--ink-3); }
.ev__good { color:var(--good); }
.ev__ko { grid-column:2 / -1; font-family:var(--body); font-size:13.5px;
  color:var(--ink-3); line-height:1.7; }
@media (max-width:680px) {
  .ev { grid-template-columns:auto 1fr; }
  .ev__arrow { display:none; }
  .ev__good, .ev__ko { grid-column:2; }
}

.qa { background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid var(--crit); border-radius:4px; padding:18px 22px;
  display:flex; flex-direction:column; gap:12px; }
.qa__meta { display:flex; align-items:center; gap:11px; flex-wrap:wrap; }
.qa__n { font-family:var(--mono); font-size:11px; color:var(--ink-3); }
.qa__slot { font-family:var(--mono); font-size:11px; letter-spacing:.06em;
  color:var(--ink-2); }
.qa__tag { display:block; font-family:var(--mono); font-size:10px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--ink-3); margin-bottom:4px; }
.qa__q { font-family:var(--mono); font-size:14px; line-height:1.65; }
.qa__a { font-family:var(--mono); font-size:13px; line-height:1.65; color:var(--ink-2); }
.qa__ko { font-size:15px; color:var(--ink); border-top:1px solid var(--rule);
  padding-top:11px; }

.chart { background:var(--surface); border:1px solid var(--rule); border-radius:4px;
  padding:22px 22px 14px; display:flex; flex-direction:column; gap:14px; }
.chart__plot { position:relative; display:grid;
  grid-template-columns:repeat(var(--cols,15),1fr); gap:5px; align-items:end;
  height:150px; }
.bar { position:relative; height:var(--h); background:var(--accent-soft);
  border-top:2px solid var(--accent); border-radius:1px 1px 0 0; }
.bar.is-weak { background:transparent; border-top-color:var(--crit);
  outline:1px dashed var(--crit); outline-offset:-1px; }
.bar__n { position:absolute; top:100%; left:0; right:0; text-align:center;
  font-family:var(--mono); font-size:9.5px; color:var(--ink-3); padding-top:5px; }
.chart__mean { position:absolute; left:0; right:0;
  border-top:1px dashed var(--rule-2); }
.chart__mean span { position:absolute; right:0; bottom:2px; font-family:var(--mono);
  font-size:10px; color:var(--ink-3); background:var(--surface); padding:0 4px; }
.chart__foot { font-family:var(--mono); font-size:10.5px; letter-spacing:.05em;
  color:var(--ink-3); padding-top:14px; }
.metrics-line { font-family:var(--mono); font-size:11px; color:var(--ink-3);
  max-width:none; }

.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); border-radius:4px;
  overflow:hidden; }
.stat { background:var(--surface); padding:16px 18px; display:flex;
  flex-direction:column; gap:3px; }
.stat__v { font-family:var(--mono); font-size:26px; font-weight:700;
  letter-spacing:-.03em; font-variant-numeric:tabular-nums; line-height:1.2; }
.stat__k { font-family:var(--display); font-size:13px; font-weight:500;
  color:var(--ink-2); }
.stat__n { font-family:var(--mono); font-size:10.5px; color:var(--ink-3); }

.unclear { display:flex; flex-direction:column; gap:10px; }
.unc-list { list-style:none; margin:0; padding:0; display:flex;
  flex-direction:column; }
.unc { display:grid; grid-template-columns:auto auto 1fr auto; align-items:baseline;
  gap:12px; padding:7px 0; border-top:1px solid var(--rule);
  font-family:var(--mono); font-size:12px; }
.unc__w { color:var(--warn); font-weight:700; }
.unc__p { color:var(--ink-3); font-variant-numeric:tabular-nums; }
.unc__c { color:var(--ink-2); }
.unc__n { color:var(--ink-3); font-size:10.5px; }
@media (max-width:680px) {
  .unc { grid-template-columns:auto auto 1fr; }
  .unc__c { grid-column:1 / -1; }
}

.splits { display:grid; grid-template-columns:repeat(auto-fit,minmax(290px,1fr));
  gap:26px; }
.split { display:flex; flex-direction:column; gap:10px; }
.split h3 { font-size:13.5px; font-weight:700; color:var(--ink-2); }
.mini { display:grid; grid-template-columns:1fr auto auto; align-items:center;
  gap:12px; padding:7px 0; border-top:1px solid var(--rule); }
.mini__k { font-family:var(--mono); font-size:12.5px; color:var(--ink-2); }

.tablewrap { overflow-x:auto; border:1px solid var(--rule); border-radius:4px;
  background:var(--surface); }
table { border-collapse:collapse; width:100%; font-family:var(--mono); font-size:12px; }
th { text-align:left; font-family:var(--display); font-weight:500; font-size:11px;
  color:var(--ink-3); padding:12px 11px; border-bottom:1px solid var(--rule-2);
  white-space:nowrap; }
td { padding:8px 11px; border-bottom:1px solid var(--rule); white-space:nowrap; }
tr:last-child td { border-bottom:0; }
.num { text-align:right; font-variant-numeric:tabular-nums; color:var(--ink-2); }
.avg { color:var(--ink); font-weight:700; }
.ty { color:var(--ink); }
.tp { color:var(--ink-3); }

.legend { display:flex; flex-wrap:wrap; gap:5px 13px; font-family:var(--mono);
  font-size:10.5px; letter-spacing:.06em; color:var(--ink-3); }
.legend b { color:var(--ink-2); font-weight:500; }

.txs { display:flex; flex-direction:column; gap:14px; }
.tx { background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid var(--rule-2); border-radius:4px; padding:16px 20px;
  display:flex; flex-direction:column; gap:11px; }
.tx--dead { border-left-color:var(--crit); opacity:.75; }
.tx__meta { display:flex; align-items:center; gap:9px; flex-wrap:wrap; }
.tx__n { font-family:var(--mono); font-size:13px; font-weight:700; color:var(--ink); }
.tx__slot { font-family:var(--mono); font-size:11px; letter-spacing:.06em;
  color:var(--ink-2); }
.tx__num { font-family:var(--mono); font-size:10.5px; color:var(--ink-3);
  margin-left:auto; white-space:nowrap; }
.tx__q { font-family:var(--mono); font-size:13.5px; line-height:1.65; color:var(--ink); }
.tx__a { font-family:var(--mono); font-size:13px; line-height:1.8; color:var(--ink-2);
  border-top:1px solid var(--rule); padding-top:11px; }
.tx__al { font-family:var(--mono); font-size:13px; line-height:1.8; color:var(--ink);
  background:var(--accent-soft); border-radius:3px; padding:13px 15px; }
.tx__al .qa__tag { color:var(--accent-ink); }
.tx__made { font-size:13px; line-height:1.7; color:var(--warn);
  border-left:2px solid var(--warn); padding-left:12px; }
.tx__why { font-size:13.5px; line-height:1.7; color:var(--ink-3); }
.tx__why b { color:var(--crit); font-weight:700; }
@media (max-width:620px) {
  .tx__num { margin-left:0; flex-basis:100%; }
}

.recap { list-style:none; margin:0 0 18px; padding:0;
  display:flex; flex-direction:column; gap:7px; max-width:44em; }
.recap li { position:relative; padding-left:17px; color:var(--ink-2); font-size:15px; }
.recap li::before { content:"—"; position:absolute; left:0; color:var(--ink-3); }
.why { background:var(--surface); border:1px solid var(--rule); border-radius:4px;
  padding:20px 22px; display:flex; flex-direction:column; gap:14px; }
.why__head { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.why__lvl { font-family:var(--mono); font-size:20px; font-weight:700;
  color:var(--accent-ink); letter-spacing:-.01em; }
.why__steps { display:flex; flex-direction:column; gap:11px; }
.step { display:grid; grid-template-columns:minmax(112px,140px) 1fr;
  gap:4px 18px; align-items:baseline; }
.step__k { font-family:var(--mono); font-size:11.5px; letter-spacing:.05em;
  color:var(--ink-3); }
.step__v { font-size:14.5px; line-height:1.7; color:var(--ink-2); }
.step--final .step__v { color:var(--ink); font-weight:700; }
@media (max-width:640px) {
  .step { grid-template-columns:1fr; }
}

.caveats { display:flex; flex-direction:column; gap:16px; }
.cav { border-left:2px solid var(--warn); padding:2px 0 2px 18px;
  display:flex; flex-direction:column; gap:6px; }
.cav h3 { font-size:16px; font-weight:700; }
.cav p { color:var(--ink-2); font-size:15px; max-width:40em; }

footer { margin-top:72px; padding-top:20px; border-top:1px solid var(--rule);
  font-family:var(--mono); font-size:11px; letter-spacing:.05em;
  color:var(--ink-3); display:flex; flex-wrap:wrap; gap:6px 20px; }
@media (prefers-reduced-motion:no-preference) {
  .gauge__seg.is-hit { animation:land .5s cubic-bezier(.2,.7,.3,1) both; }
}
@keyframes land { from { transform:scaleY(.28); opacity:.3; } to { transform:scaleY(1); opacity:1; } }

/* Printing, which on this machine is how a PDF gets made.
 *
 * Two things here are not cosmetic. The first is the palette: this block
 * restates the light values and names `[data-theme="dark"]` explicitly,
 * because that selector outranks a bare `:root` and would otherwise win
 * whatever the order. A report printed on a dark background wastes ink on
 * paper and reads worse either way.
 *
 * The second is `print-color-adjust`. The ladder marks the candidate's band
 * with a background, the chips are backgrounds, the chart is bars. A browser
 * that helpfully drops backgrounds turns all of that into blank boxes — a
 * ladder with no rung lit, which is not a duller report but a wrong one.
 */
@media print {
  :root,
  :root[data-theme="dark"],
  :root:not([data-theme="light"]) {
    /* `--ground` on paper is white, not the light theme's own off-white: on
       screen that shade sits deliberately under white cards, but printed
       with `print-color-adjust: exact` it lays down as a tinted rectangle
       inside white page margins — ink spent on nothing, and a report that
       reads like a printing fault instead of a design. Do not "correct"
       this back to the screen value. */
    --ground:#FFFFFF; --surface:#FFFFFF; --sunk:#EEF2F1;
    --ink:#10201E; --ink-2:#4A5C5A; --ink-3:#7C8C8A;
    --rule:#DCE4E2; --rule-2:#C6D2D0;
    --accent:#0F6E6E; --accent-soft:#DDECEB; --accent-ink:#0B5252;
    --crit:#9B382C; --warn:#8A5806; --good:#2C6B4F;
    --shadow:none;
  }

  html {
    /* Inherited, so one declaration covers the ladder, the chips and the
       chart at once. */
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  @page { margin: 14mm; }

  body { font-size: 11pt; }
  .wrap { max-width: none; padding: 0; }
  section { margin-top: 28px; }

  /* A finding split across a page break is a finding somebody misses. But
   * Chromium honours `break-inside: avoid` on block boxes and routinely
   * ignores it on flex containers — and every one of these cards is a flex
   * column on screen. Printing them as blocks is what makes the rule bind
   * at all. Their children already stack in source order, so `gap` is the
   * only casualty, and it comes back as a margin between children.
   */
  .qa, .pat, .verdict, .chart, .dim, .split, .cav, .tx, .why {
    break-inside: avoid;
    display: block;
  }
  .verdict > * + * { margin-top: 26px; }
  .dim > * + *     { margin-top: 9px; }
  .pat > * + *     { margin-top: 12px; }
  .qa > * + *      { margin-top: 12px; }
  .chart > * + *   { margin-top: 14px; }
  .split > * + *   { margin-top: 10px; }
  .cav > * + *     { margin-top: 6px; }
  .why > * + *     { margin-top: 12px; }
  .recap > * + *   { margin-top: 6px; }
  .tx > * + *      { margin-top: 11px; }

  h1, h2, h3, .sec-head { break-after: avoid; }
}
"""
