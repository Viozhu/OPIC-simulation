// The raw result. The readable report is Phase 4; what this screen owes the
// candidate is the level, how many answers it was computed from, and the JSON
// underneath so nothing is hidden.
export async function render(state, {api}) {
  const app = document.getElementById("app");
  await load(app, state, api);
}

// A failed fetch here would otherwise leave a blank page — `show()` already
// cleared `#app` before calling this — which is the worst possible ending to
// a 40-minute exam. Retrying re-runs this same function instead of leaving
// the candidate stuck.
async function load(app, state, api) {
  let result;
  try {
    result = await api.get(`/api/sessions/${state.id}/result`);
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

  const level = document.createElement("h2");
  level.textContent = `최종 등급: ${result.final_level}`;

  const based = document.createElement("p");
  based.textContent =
    `${result.expected_answers}개 중 ${result.scored_answers}개의 답변으로 산출되었습니다.`;
  if (result.scored_answers < result.expected_answers) {
    based.className = "issues";
  }

  const caveat = document.createElement("p");
  caveat.textContent =
    "이 등급은 공식 점수가 아니며 실제 시험 결과를 예측하지 않습니다. 발음 지표는 참고용입니다.";

  const dimensions = document.createElement("ul");
  for (const info of Object.values(result.dimensions)) {
    const line = document.createElement("li");
    line.textContent = `${info.label_ko}: ${info.level}`;
    dimensions.append(line);
  }

  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "전체 결과 (JSON)";
  const raw = document.createElement("pre");
  raw.textContent = JSON.stringify(result, null, 2);
  details.append(summary, raw);

  const again = document.createElement("button");
  again.textContent = "새 시험 시작";
  again.addEventListener("click", () => {
    localStorage.removeItem("opic.session");
    location.reload();
  });

  app.replaceChildren(level, based, caveat, dimensions, details, again);
}
