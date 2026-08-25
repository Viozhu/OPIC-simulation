// The whole exam is one page. This module owns the session id, talks to the
// API, and hands the current state to whichever step module renders it.
const steps = {};

export const api = {
  async get(path) {
    const response = await fetch(path);
    if (!response.ok) throw Object.assign(new Error(path), {status: response.status});
    return response.json();
  },
  async send(method, path, body) {
    const response = await fetch(path, {
      method,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(path), {status: response.status, payload});
    return payload;
  },
  async upload(path, blob, filename) {
    const form = new FormData();
    form.append("audio", blob, filename);
    const response = await fetch(path, {method: "POST", body: form});
    const payload = await response.json().catch(() => ({}));
    // The `detail` in this payload is what lets a caller tell "someone else
    // already recorded this answer" apart from "this session has moved past
    // the test step" — both are a 409, and they call for different UI.
    if (!response.ok) throw Object.assign(new Error(path), {status: response.status, payload});
    return payload;
  },
};

const LABELS = {
  survey: "1단계 · 배경 설문",
  level: "2단계 · 자기 평가",
  setup: "3단계 · 마이크 점검",
  sample: "4단계 · 예시 문항",
  test: "5단계 · 시험",
  grading: "채점 중",
  done: "결과",
};

export const root = document.getElementById("app");

export async function show(state) {
  document.getElementById("step-label").textContent = LABELS[state.step] ?? "";
  showProgress(state);
  const step = steps[state.step];
  if (!step) {
    root.textContent = `알 수 없는 단계: ${state.step}`;
    return;
  }
  root.replaceChildren();
  await step.render(state, {show, api});
}

// The bar is the glance; the "질문 3 / 15" heading inside the step is the
// fact. Only the two steps with a real denominator get one — a survey has no
// meaningful fraction, and a bar that means nothing teaches a candidate to
// ignore the bar that does.
function showProgress(state) {
  const bar = document.getElementById("step-progress");
  if (state.step !== "test") {
    bar.hidden = true;
    return;
  }
  const answered = state.answers.filter((answer) => answer.state !== "pending").length;
  bar.max = state.questions.length;
  bar.value = answered;
  bar.hidden = false;
}

export async function reload(sessionId) {
  return show(await api.get(`/api/sessions/${sessionId}`));
}

async function boot() {
  const stored = localStorage.getItem("opic.session");
  let state = null;
  if (stored) {
    try {
      state = await api.get(`/api/sessions/${stored}`);
    } catch (error) {
      localStorage.removeItem("opic.session");
    }
  }
  if (!state) {
    try {
      state = await api.send("POST", "/api/sessions", {});
      localStorage.setItem("opic.session", state.id);
    } catch (error) {
      // The server is unreachable at load — leaving "불러오는 중…" up forever
      // would look identical to a page that just never loaded.
      root.textContent = "서버와 연결할 수 없습니다. ";
      const reload = document.createElement("button");
      reload.textContent = "새로고침";
      reload.addEventListener("click", () => window.location.reload());
      root.append(reload);
      return;
    }
  }
  await show(state);
}

for (const name of ["survey", "level", "setup", "sample", "test", "grading", "done"]) {
  try {
    steps[name] = await import(`/static/steps/${name}.js`);
  } catch (error) {
    // A step not written yet simply has no module; `show` reports it.
  }
}

boot();
