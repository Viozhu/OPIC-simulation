// Step 5 — the exam. One question at a time, no going back, no re-recording,
// and 재생 exactly once. The upload does not block the next question: the
// server queues the evaluation and answers straight away.
import {askAndRecord, uploadWithRetries, waitUntilReady} from "../question.js";

export async function render(state, {api, show}) {
  const app = document.getElementById("app");

  if (!state.questions_ready) {
    const waiting = document.createElement("p");
    waiting.textContent = "문제를 준비하고 있습니다. 잠시만 기다려 주세요…";
    app.append(waiting);
    state = await waitUntilReady(api, state.id);
    app.replaceChildren();
  }

  const pending = state.answers.filter((answer) => answer.state === "pending");
  if (pending.length === 0) {
    await show(await api.send("POST", `/api/sessions/${state.id}/step`, {step: "grading"}));
    return;
  }

  const index = pending[0].index;
  const total = state.questions.length;

  const heading = document.createElement("h2");
  heading.textContent = `질문 ${index + 1} / ${total}`;
  const status = document.createElement("p");
  const warning = document.createElement("p");
  warning.textContent =
    "답변은 다시 녹음할 수 없으며, 녹음 중 페이지를 새로 고치면 그 답변은 사라집니다.";
  const replay = document.createElement("button");
  replay.className = "secondary";
  replay.textContent = "재생 (1회)";
  replay.disabled = true;
  const next = document.createElement("button");
  next.textContent = "다음";
  next.disabled = true;

  app.append(heading, status, warning, replay, next);

  const machine = askAndRecord({
    audioUrl: `/api/sessions/${state.id}/questions/${index}/audio`,
    onState: (phase) => {
      status.textContent = {
        playing: "질문 재생 중…",
        recording: "녹음 중…",
        uploading: "전송 중…",
      }[phase] ?? "";
      status.className = phase === "recording" ? "recording" : "";
      replay.disabled = phase !== "recording" || machine.replaysLeft() === 0;
      next.disabled = phase !== "recording";
    },
  });

  replay.addEventListener("click", async () => {
    replay.disabled = true;
    await machine.replay();
  });

  const retry = document.createElement("button");
  retry.textContent = "다시 전송";
  retry.hidden = true;

  next.addEventListener("click", async () => {
    next.disabled = true;
    replay.disabled = true;
    const {blob, filename} = await machine.stop();

    const send = async () => {
      retry.hidden = true;
      try {
        const updated = await uploadWithRetries(
          api, `/api/sessions/${state.id}/answers/${index}`, blob, filename,
        );
        await show(updated);
      } catch (error) {
        if (error.status === 409) {
          // The server already holds this answer — most likely our own
          // earlier attempt landed and only its response was lost in
          // transit. That is a success, not a failure, so move on instead of
          // reporting an error that never actually happened.
          await show(await api.get(`/api/sessions/${state.id}`));
          return;
        }
        status.textContent = "전송에 실패했습니다. 다시 시도해 주세요.";
        status.className = "issues";
        retry.hidden = false;
      }
    };

    retry.addEventListener("click", send);
    await send();
  });

  app.append(retry);

  await machine.play();
}
