// The raw result. The readable report is Phase 4; what this screen owes the
// candidate is the level, how many answers it was computed from, and the JSON
// underneath so nothing is hidden.
export async function render(state, {api}) {
  const app = document.getElementById("app");
  const result = await api.get(`/api/sessions/${state.id}/result`);

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
  for (const [dimension, value] of Object.entries(result.dimensions)) {
    const line = document.createElement("li");
    line.textContent = `${dimension}: ${value}`;
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

  app.append(level, based, caveat, dimensions, details, again);
}
