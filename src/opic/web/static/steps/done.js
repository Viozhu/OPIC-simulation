// The report: level, why, the words the recogniser struggled with, the
// breakdowns, and the answer-by-answer detail — plus the raw JSON and a way
// to start over. This screen decides nothing: it iterates
// `GET /api/sessions/{id}/report` and appends what it finds. Every string it
// prints comes from that payload, except the fixed section headings and the
// caveat below.
export async function render(state, {api}) {
  const app = document.getElementById("app");
  await load(app, state, api);
}

// A failed fetch here would otherwise leave a blank page — `show()` already
// cleared `#app` before calling this — which is the worst possible ending to
// a 40-minute exam. Retrying re-runs this same function instead of leaving
// the candidate stuck.
async function load(app, state, api) {
  let report, raw;
  try {
    [report, raw] = await Promise.all([
      api.get(`/api/sessions/${state.id}/report`),
      api.get(`/api/sessions/${state.id}/result`),
    ]);
  } catch (error) {
    const message = document.createElement("p");
    message.className = "issues";
    message.textContent =
      "결과를 불러오지 못했습니다. 서버 연결을 확인한 뒤 다시 시도해 주세요.";
    const retry = document.createElement("button");
    retry.textContent = "다시 시도";
    retry.addEventListener("click", () => load(app, state, api), {once: true});
    app.replaceChildren(message, retry);
    return;
  }

  const rawDetails = document.createElement("details");
  const rawSummary = document.createElement("summary");
  rawSummary.textContent = "전체 결과 (JSON)";
  const rawPre = document.createElement("pre");
  rawPre.textContent = JSON.stringify(raw, null, 2);
  rawDetails.append(rawSummary, rawPre);

  const again = document.createElement("button");
  again.textContent = "새 시험 시작";
  again.addEventListener("click", () => {
    localStorage.removeItem("opic.session");
    location.reload();
  });

  app.replaceChildren(
    ...summarySection(report),
    ...whySection(report),
    ...unclearSection(report),
    ...breakdownSection(report),
    ...detailSection(report),
    rawDetails,
    again,
  );
}

// §1 — the level, how many answers it rests on, and the caveat. The
// pronunciation sentence that used to live here is gone: the unclear-words
// section now carries that job.
function summarySection(report) {
  const level = document.createElement("h2");
  level.textContent = `최종 등급: ${report.final_level}`;

  const based = document.createElement("p");
  based.textContent =
    `${report.expected_answers}개 중 ${report.scored_answers}개의 답변으로 산출되었습니다.`;
  if (report.scored_answers < report.expected_answers) {
    based.className = "issues";
  }

  const caveat = document.createElement("p");
  caveat.textContent =
    "이 등급은 공식 점수가 아니며 실제 시험 결과를 예측하지 않습니다.";

  return [level, based, caveat];
}

// §2 — the limiting dimension (if any), then every dimension with its weight,
// level, and the quotes behind it.
function whySection(report) {
  const elements = [];
  const heading = document.createElement("h2");
  heading.textContent = "왜 이 등급인가";
  elements.push(heading);

  if (report.limiting) {
    const limiting = document.createElement("p");
    limiting.textContent =
      `최종 등급은 ${report.limiting.label_ko}에 의해 한 단계 낮아졌습니다. ` +
      `그 제한이 없었다면 ${report.limiting.without_cap}입니다.`;
    elements.push(limiting);
  }

  for (const dimension of report.dimensions) {
    const block = document.createElement("div");
    block.className = "dimension";
    const title = document.createElement("h3");
    title.textContent =
      `${dimension.label_ko} (${Math.round(dimension.weight * 100)}%): ${dimension.level}`;
    block.append(title);

    const evidence = document.createElement("ul");
    evidence.className = "evidence";
    for (const item of dimension.evidence) {
      evidence.append(evidenceItem(item, true));
    }
    block.append(evidence);
    elements.push(block);
  }

  return elements;
}

// One quote / issue / correction, with the question it came from when the
// caller asks for it (the exam-level summary needs that pointer back to the
// answer; the per-answer detail is already inside that answer, so it does not).
function evidenceItem(item, withAnswerIndex) {
  const li = document.createElement("li");
  li.className = "evidence-item";
  const quote = document.createElement("p");
  quote.className = "quote";
  quote.textContent = `"${item.quote}"`;
  const issue = document.createElement("p");
  issue.textContent = item.issue_ko;
  const correction = document.createElement("p");
  correction.className = "correction";
  correction.textContent = `→ ${item.correction_en}`;
  li.append(quote, issue, correction);
  if (withAnswerIndex) {
    const ref = document.createElement("p");
    ref.className = "answer-ref";
    ref.textContent = `질문 ${item.answer_index + 1}`;
    li.append(ref);
  }
  return li;
}

// §3 — every word the recogniser gave low confidence to, with its question
// and surrounding context, or the one line saying there were none.
function unclearSection(report) {
  const elements = [];
  const heading = document.createElement("h2");
  heading.textContent = "또렷하게 인식되지 않은 단어";
  elements.push(heading);

  if (report.unclear.length === 0) {
    const none = document.createElement("p");
    none.textContent = "또렷하게 인식되지 않은 단어는 없습니다.";
    elements.push(none);
    return elements;
  }

  const list = document.createElement("ul");
  for (const word of report.unclear) {
    const li = document.createElement("li");
    li.textContent =
      `${word.text} (질문 ${word.answer_index + 1}): …${word.context}…`;
    list.append(li);
  }
  elements.push(list);
  return elements;
}

// §4 — level by question type and by topic, each as its own list, skipped
// entirely when the API sent nothing for it.
function breakdownSection(report) {
  const elements = [];
  const heading = document.createElement("h2");
  heading.textContent = "유형별 · 주제별";
  elements.push(heading);

  for (const group of [report.by_type, report.by_topic]) {
    if (group.length === 0) continue;
    const list = document.createElement("ul");
    for (const item of group) {
      const li = document.createElement("li");
      li.textContent = `${item.label_ko}: ${item.level}`;
      list.append(li);
    }
    elements.push(list);
  }

  return elements;
}

// §5 — one collapsible per answer. An answer that never got scored carries
// only its summary line; a scored one opens onto the question, transcript,
// speed/pause against the exam average, and each dimension's comment and
// evidence.
function detailSection(report) {
  const elements = [];
  const heading = document.createElement("h2");
  heading.textContent = "답변별 상세";
  elements.push(heading);

  for (const answer of report.answers) {
    elements.push(answerDetails(answer, report.averages));
  }

  return elements;
}

function answerDetails(answer, averages) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");

  if (answer.state !== "scored") {
    const note = answer.state === "unreadable" ? "읽을 수 없는 파일" : "채점하지 못한 답변";
    summary.textContent = `질문 ${answer.index + 1} — ${note}`;
    details.append(summary);
    return details;
  }

  summary.textContent = `질문 ${answer.index + 1} (${answer.qtype_label_ko})`;
  details.append(summary);

  const question = document.createElement("p");
  question.className = "question-en";
  question.textContent = answer.question_en;
  details.append(question);

  const transcript = document.createElement("p");
  transcript.className = "transcript";
  transcript.textContent = answer.transcript_text;
  details.append(transcript);

  if (answer.metrics && averages) {
    const metrics = document.createElement("p");
    metrics.className = "metrics-line";
    metrics.textContent =
      `말하기 속도 ${Math.round(answer.metrics.words_per_minute)} ` +
      `(평균 ${Math.round(averages.words_per_minute)}) · ` +
      `침묵 비율 ${Math.round(answer.metrics.pause_ratio * 100)}% ` +
      `(평균 ${Math.round(averages.pause_ratio * 100)}%)`;
    details.append(metrics);
  }

  for (const score of answer.scores) {
    const block = document.createElement("div");
    block.className = "dimension";
    const title = document.createElement("h4");
    title.textContent = `${score.label_ko}: ${score.level}`;
    const comment = document.createElement("p");
    comment.textContent = score.comment_ko;
    block.append(title, comment);

    if (score.evidence.length > 0) {
      const evidence = document.createElement("ul");
      evidence.className = "evidence";
      for (const item of score.evidence) {
        evidence.append(evidenceItem(item, false));
      }
      block.append(evidence);
    }
    details.append(block);
  }

  return details;
}
