// 채점 중. The wait is long by nature — about five minutes per answer — so this
// screen has to be honest about it: how many are done, roughly how long is
// left, and the fact that the tab can be closed.
const POLL_MS = 3000;
const SECONDS_PER_ANSWER = 300;

export async function render(state, {api, show}) {
  const app = document.getElementById("app");
  const heading = document.createElement("h2");
  heading.textContent = "채점 중입니다";
  const note = document.createElement("p");
  note.textContent =
    "채점은 이 컴퓨터에서 진행됩니다. 창을 닫아도 계속되며, 나중에 다시 열면 진행 상황을 볼 수 있습니다.";
  const bar = document.createElement("p");
  bar.className = "counter";
  const eta = document.createElement("p");
  const failures = document.createElement("p");
  failures.className = "issues";

  app.append(heading, note, bar, eta, failures);

  while (true) {
    const progress = await api.get(`/api/sessions/${state.id}/progress`);
    const settled = progress.scored + progress.failed;
    bar.textContent = `채점 완료: ${settled} / ${progress.expected}`;
    const left = Math.max(0, progress.expected - settled) * SECONDS_PER_ANSWER;
    eta.textContent = `남은 예상 시간: 약 ${Math.ceil(left / 60)}분`;
    failures.textContent =
      progress.failed > 0 ? `채점하지 못한 답변: ${progress.failed}개` : "";

    if (progress.done) {
      await show(await api.get(`/api/sessions/${state.id}`));
      return;
    }
    if (settled === progress.expected) {
      if (progress.scored === 0) {
        // Nothing was scored, so no result will ever be written. Saying so
        // beats a spinner that never stops.
        heading.textContent = "채점하지 못했습니다";
        eta.textContent = "";
        failures.textContent =
          "모든 답변의 채점에 실패했습니다. Ollama가 실행 중인지 확인한 뒤 서버를 다시 시작하면 남은 답변부터 이어서 채점합니다.";
        return;
      }
      eta.textContent = "결과를 정리하는 중…";
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}
