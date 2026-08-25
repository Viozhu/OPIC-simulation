// The report: rendered by `core/page.py`, served whole by
// `/api/sessions/{id}/page`, and shown here inside a frame. This screen used
// to draw the report itself, worse than the page did — two renderers of one
// model, and the browser got the poorer one.
//
// What survives from that version is the fallback ladder underneath, rung for
// rung: no page but a `result.json` still shows a level (`renderMinimal`), and
// neither shows the retry screen (`renderRetry`). The top rung is the only one
// that changed.
export async function render(state, {api}) {
  const app = document.getElementById("app");
  await load(app, state, api);
}

async function load(app, state, api) {
  const url = `/api/sessions/${state.id}/page`;
  const html = await fetchPage(url);
  if (html !== null) {
    renderFrame(app, url, html);
    return;
  }
  // No rendered page. `result.json` may still be there — it is written before
  // the page and by a path that cannot fail the same way.
  let raw = null;
  try {
    raw = await api.get(`/api/sessions/${state.id}/result`);
  } catch (error) {
    renderRetry(app, state, api);
    return;
  }
  renderMinimal(app, raw);
}

// One GET, and the page's own text comes back with it. Pointing an iframe's
// `src` at the URL instead would ask the server for the same page a second
// time — and would frame whatever came back, so a session with no report
// would put a JSON 404 body on screen where a report should be, with no
// usable way to notice from out here.
async function fetchPage(url) {
  try {
    const response = await fetch(url);
    return response.ok ? await response.text() : null;
  } catch (error) {
    return null;
  }
}

function renderFrame(app, url, html) {
  const frame = document.createElement("iframe");
  frame.className = "report-frame";
  // `srcdoc`, not `src`: the document is already here. The page is
  // self-contained apart from its webfonts, so nothing in it needs the origin
  // it would have had.
  frame.srcdoc = html;
  frame.title = "OPIc 리포트";

  const save = document.createElement("button");
  save.className = "secondary";
  save.textContent = "PDF로 저장";
  save.addEventListener("click", () => {
    // Printing the frame prints the report by itself: the app's header and
    // these buttons live in a different document and never reach the page.
    // The browser's print dialog is where a PDF actually gets written — this
    // only opens it, and the page's own @media print rules are what make the
    // result worth keeping.
    try {
      frame.contentWindow.focus();
      frame.contentWindow.print();
    } catch (error) {
      // A frame whose document is not reachable is not a reason to lose the
      // feature: the same page is one navigation away, and the candidate can
      // print it from there.
      console.error(error);
      window.open(url, "_blank", "noopener");
    }
  });

  const open = document.createElement("a");
  open.href = url;
  open.target = "_blank";
  open.rel = "noopener";
  open.className = "report-open";
  open.textContent = "새 탭에서 열기 (인쇄·저장)";

  const actions = document.createElement("p");
  actions.className = "actions";
  actions.append(save, open, restartButton());

  app.replaceChildren(frame, actions);
}

// Both fetches failed: nothing to show, so the candidate gets the retry
// button that exists today. Retrying re-runs `load` instead of leaving the
// candidate stuck on a blank page.
function renderRetry(app, state, api) {
  const message = document.createElement("p");
  message.className = "issues";
  message.textContent =
    "결과를 불러오지 못했습니다. 서버 연결을 확인한 뒤 다시 시도해 주세요.";
  const retry = document.createElement("button");
  retry.textContent = "다시 시도";
  retry.addEventListener("click", () => load(app, state, api), {once: true});
  app.replaceChildren(message, retry);
}

// `/report` could not be built — every `answer-NN.json` was unreadable —
// but `result.json` still holds the level `/result` computed at grading
// time. This is the phase-3 view: level, how many answers it rests on, the
// per-dimension list, the raw JSON, and a way to start over, plus one
// honest sentence that the detailed report is the part that is missing.
function renderMinimal(app, raw) {
  const level = document.createElement("h2");
  level.textContent = `최종 등급: ${raw.final_level}`;

  const based = document.createElement("p");
  based.textContent =
    `${raw.expected_answers}개 중 ${raw.scored_answers}개의 답변으로 산출되었습니다.`;
  if (raw.scored_answers < raw.expected_answers) {
    based.className = "issues";
  }

  const caveat = document.createElement("p");
  caveat.textContent =
    "이 등급은 공식 점수가 아니며 실제 시험 결과를 예측하지 않습니다.";

  const missing = document.createElement("p");
  missing.className = "issues";
  missing.textContent =
    "저장된 답변에서 상세 리포트를 만들지 못했습니다. 등급과 기본 정보만 표시합니다.";

  const dimensions = document.createElement("ul");
  for (const info of Object.values(raw.dimensions)) {
    const line = document.createElement("li");
    line.textContent = `${info.label_ko}: ${info.level}`;
    dimensions.append(line);
  }

  app.replaceChildren(
    level,
    based,
    caveat,
    missing,
    dimensions,
    rawDetailsFor(raw),
    restartButton(),
  );
}

function rawDetailsFor(raw) {
  const rawDetails = document.createElement("details");
  const rawSummary = document.createElement("summary");
  rawSummary.textContent = "전체 결과 (JSON)";
  const rawPre = document.createElement("pre");
  rawPre.textContent = JSON.stringify(raw, null, 2);
  rawDetails.append(rawSummary, rawPre);
  return rawDetails;
}

function restartButton() {
  const again = document.createElement("button");
  again.textContent = "새 시험 시작";
  again.addEventListener("click", () => {
    localStorage.removeItem("opic.session");
    location.reload();
  });
  return again;
}
