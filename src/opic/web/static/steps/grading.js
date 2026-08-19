// 채점 중. The wait is long by nature — about five minutes per answer — so this
// screen has to be honest about it: how many are done, roughly how long is
// left, and the fact that the tab can be closed.
import {render as renderDone} from "./done.js";

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
  const connection = document.createElement("p");
  connection.className = "issues";

  app.append(heading, note, bar, eta, failures, connection);

  while (true) {
    try {
      const progress = await api.get(`/api/sessions/${state.id}/progress`);
      // A previous iteration may have left the connection warning up; a
      // successful fetch means the server is reachable again.
      connection.textContent = "";

      const settled = progress.scored + progress.failed;
      bar.textContent = `채점 완료: ${settled} / ${progress.expected}`;
      const left = Math.max(0, progress.expected - settled) * SECONDS_PER_ANSWER;
      eta.textContent = `남은 예상 시간: 약 ${Math.ceil(left / 60)}분`;
      failures.textContent =
        progress.failed > 0 ? `채점하지 못한 답변: ${progress.failed}개` : "";

      if (progress.done) {
        await goToResult(state, api, show);
        return;
      }
      if (settled === progress.expected) {
        if (progress.scored === 0) {
          // Nothing was scored, so no result will ever be written, and
          // nothing on the server will retry a FAILED answer on its own —
          // only a RECORDED one gets requeued on restart. Saying a restart
          // will finish the job would be a promise the server cannot keep,
          // so this says only what is true: nothing more will happen here,
          // the recordings are not lost, and Ollama not running is the
          // usual reason.
          heading.textContent = "채점하지 못했습니다";
          note.textContent = "";
          eta.textContent = "";
          failures.textContent =
            "채점 가능한 답변이 없어 결과를 계산할 수 없습니다. 녹음한 답변은 이 컴퓨터의 세션 폴더에 그대로 남아 있으니 사라지지 않았습니다. 대부분 Ollama가 실행되고 있지 않을 때 일어나며, 지금은 자동으로 다시 시도되지 않습니다.";
          return;
        }
        eta.textContent = "결과를 정리하는 중…";
      }
    } catch (error) {
      // A dropped connection here looks identical to a screen that is
      // legitimately slow for up to 35 minutes, so say so explicitly rather
      // than freezing on stale numbers or letting the loop die silently.
      connection.textContent = "서버와 연결할 수 없습니다. 계속 다시 시도합니다…";
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}

// `progress.done` means `result.json` exists, but the session's own `step`
// can still read "grading" for a moment after that — the worker's last
// EVALUATE can settle and aggregate before the browser's own POST has moved
// the session TEST -> GRADING, and older servers may never advance it at
// all. Calling `show()` on a state still stuck at "grading" would just
// re-render this very screen: an infinite loop with nothing left to poll,
// since `done` is already true. Give the server one short chance to catch
// up, then render the result directly — the result exists and the
// candidate is entitled to see it regardless of what `step` says.
async function goToResult(state, api, show) {
  let latest = await api.get(`/api/sessions/${state.id}`);
  if (latest.step === "grading") {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    latest = await api.get(`/api/sessions/${state.id}`);
  }
  if (latest.step === "grading") {
    // `show()` is what normally updates the step label; bypassing it to
    // avoid the re-render loop means doing that one bit of its job by hand.
    document.getElementById("step-label").textContent = "결과";
    await renderDone(latest, {api});
    return;
  }
  await show(latest);
}
