// The report: rendered by `core/page.py`, served whole by
// `/api/sessions/{id}/page`, and shown here inside a frame. This screen used
// to draw the report itself, worse than the page did — two renderers of one
// model, and the browser got the poorer one.
//
// What survives from that version is the fallback ladder underneath, rung for
// rung: no page but a `result.json` still shows a level (`renderMinimal`), and
// neither shows the retry screen (`renderRetry`). The top rung is the only one
// that changed.
//
// The route answers `200` for the written page and `202` for the same report
// rendered without the narrative — the only page that exists for the minute
// the worker spends on that model call. Framing the `202` would hand the
// candidate the poorer document permanently, since this screen asks once and
// nothing refreshes it. So a `202` waits for the `200` instead, with a way
// out for the sessions where the better page is never coming.
const PAGE_POLL_MS = 3000;
const PAGE_WAIT_MS = 150000;

export async function render(state, {api}) {
  const app = document.getElementById("app");
  await load(app, state, api);
}

async function load(app, state, api) {
  const url = `/api/sessions/${state.id}/page`;
  const page = await fetchPage(url);
  if (page.ready) {
    renderFrame(app, url, page.html, state, api);
    return;
  }
  if (page.html !== null) {
    await waitForWrittenPage(app, url, page.html, state, api);
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
  renderMinimal(app, raw, state, api);
}

// One GET, and the page's own text comes back with it. Pointing an iframe's
// `src` at the URL instead would ask the server for the same page a second
// time — and would frame whatever came back, so a session with no report
// would put a JSON 404 body on screen where a report should be, with no
// usable way to notice from out here.
async function fetchPage(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      return {ready: false, html: null};
    }
    // 202: a report, but the provisional one. Everything else in the 2xx
    // range is the written page.
    return {ready: response.status !== 202, html: await response.text()};
  } catch (error) {
    return {ready: false, html: null};
  }
}

// The narrative call takes about a minute after grading ends, so this waits
// rather than showing a report the candidate would have to be told to reload.
// It is a bounded wait with a door in it: a session graded before the written
// page existed, or one whose narrative call failed, has nothing better coming
// and must not trap anyone behind a spinner. Either exit frames the page —
// the provisional one is a whole report, only missing the judged sections.
async function waitForWrittenPage(app, url, provisional, state, api) {
  const heading = document.createElement("h2");
  heading.textContent = "리포트를 마무리하는 중입니다";
  const note = document.createElement("p");
  note.textContent =
    "채점은 끝났습니다. 지금은 답변마다 AL 목표 답변과 총평을 쓰는 중이며, 보통 1분쯤 걸립니다.";
  const skip = document.createElement("button");
  skip.className = "secondary";
  skip.textContent = "기다리지 않고 결과 보기";
  const actions = document.createElement("p");
  actions.className = "actions";
  actions.append(skip);
  app.replaceChildren(heading, note, actions);
  app.setAttribute("aria-busy", "true");
  heading.tabIndex = -1;
  heading.focus({preventScroll: true});

  let skipped = false;
  skip.addEventListener("click", () => {
    skipped = true;
  });

  const deadline = Date.now() + PAGE_WAIT_MS;
  let latest = provisional;
  while (!skipped && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, PAGE_POLL_MS));
    if (skipped) {
      break;
    }
    const page = await fetchPage(url);
    if (page.ready) {
      app.removeAttribute("aria-busy");
      renderFrame(app, url, page.html, state, api);
      return;
    }
    if (page.html !== null) {
      latest = page.html;
    }
  }
  app.removeAttribute("aria-busy");
  renderFrame(app, url, latest, state, api);
}

function renderFrame(app, url, html, state, api) {
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

  app.replaceChildren(frame, actions, feedbackCard(state, api));
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
function renderMinimal(app, raw, state, api) {
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
    feedbackCard(state, api),
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

// El examen ya terminó, así que esto no es un paso más de la máquina de
// estados: es una tarjeta debajo del informe. Se envía una vez y se sustituye
// por el agradecimiento; un candidato que insista puede recargar, y el
// servidor se limitará a sobrescribir su propia fila pendiente.
function feedbackCard(state, api) {
  const card = document.createElement("form");
  card.className = "feedback";

  const heading = document.createElement("h3");
  heading.textContent = "이 모의고사는 어땠나요?";

  const scale = document.createElement("fieldset");
  const legend = document.createElement("legend");
  legend.textContent = "1점(별로) – 5점(아주 좋음)";
  scale.append(legend);
  for (const value of [1, 2, 3, 4, 5]) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "rating";
    input.value = String(value);
    input.required = true;
    label.append(input, ` ${value}`);
    scale.append(label);
  }

  const commentLabel = document.createElement("label");
  const comment = document.createElement("textarea");
  comment.name = "comment";
  comment.rows = 4;
  comment.maxLength = 2000;
  comment.placeholder = "자유롭게 남겨 주세요. (선택)";
  commentLabel.append("의견 ", comment);

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "보내기";

  const status = document.createElement("p");
  status.className = "issues";

  card.append(heading, scale, commentLabel, submit, status);

  card.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    status.textContent = "";
    const data = new FormData(card);
    try {
      await api.send("POST", `/api/sessions/${state.id}/feedback`, {
        rating: Number(data.get("rating")),
        comment: String(data.get("comment") ?? ""),
      });
      const thanks = document.createElement("p");
      thanks.textContent = "의견 감사합니다.";
      card.replaceChildren(heading, thanks);
    } catch (error) {
      const issues = error.payload?.issues;
      status.textContent = issues?.length
        ? issues.map((issue) => issue.message_ko).join(" ")
        : "의견을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.";
      submit.disabled = false;
    }
  });

  return card;
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
