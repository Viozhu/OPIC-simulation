// Step 5 — the exam. One question at a time, no going back, no re-recording,
// and 재생 exactly once. The upload does not block the next question: the
// server queues the evaluation and answers straight away.
import {askAndRecord, uploadWithRetries, waitUntilReady} from "../question.js";
import {recordingPanel} from "../panel.js";

// `opic.web.app.post_answer` returns 409 for two different reasons: the
// answer is already recorded, or the session has left the test step. The
// server attaches a machine-readable `reason` alongside its human sentence
// precisely so this does not have to guess from prose — that field is
// authoritative. The substring match on the English sentence is only a
// fallback for an older server that predates the `reason` field; it must
// never be trusted over a `reason` that is actually present.
function answerAlreadyExists(payload) {
  const detail = payload?.detail;
  const reason = detail && typeof detail === "object" ? detail.reason : undefined;
  if (reason) return reason === "answer_already_recorded";
  const text = detail && typeof detail === "object" ? detail.detail : detail;
  return typeof text === "string" && text.includes("already");
}

export async function render(state, {api, show}) {
  const app = document.getElementById("app");

  if (!state.questions_ready) {
    state = await waitForQuestions(app, api, state.id);
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

  let panel = null;

  const machine = askAndRecord({
    audioUrl: `/api/sessions/${state.id}/questions/${index}/audio`,
    onState: (phase, info) => {
      status.textContent = {
        playing: "질문 재생 중…",
        recording: "녹음 중…",
        uploading: "전송 중…",
      }[phase] ?? "";
      status.className = phase === "recording" ? "recording" : "";
      if (phase === "recording" && panel === null && info.stream) {
        panel = recordingPanel(info.stream);
        status.after(panel.element);
      }
      if (phase === "uploading" && panel !== null) {
        panel.stop();
        panel.element.remove();
        panel = null;
      }
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
    let blob, filename;
    try {
      ({blob, filename} = await machine.stop());
    } catch (error) {
      // The recording itself never finalized, so there is nothing captured
      // to upload and nothing here worth retrying in place. Nothing was ever
      // sent to the server either, so this answer is still `pending` there —
      // reloading re-renders this exact question with a fresh microphone
      // session, instead of leaving 재생 and 다음 both dead for the rest of
      // the exam. `machine.stop()` has already torn its own panel down by
      // the time this runs.
      console.error(error);
      status.textContent =
        "녹음을 저장하지 못했습니다. 새로고침한 뒤 이 문제를 다시 녹음해 주세요.";
      status.className = "issues";
      const reload = document.createElement("button");
      reload.textContent = "새로고침";
      reload.addEventListener("click", () => window.location.reload());
      app.append(reload);
      return;
    }

    const send = async () => {
      retry.hidden = true;
      try {
        const updated = await uploadWithRetries(
          api, `/api/sessions/${state.id}/answers/${index}`, blob, filename,
        );
        await show(updated);
      } catch (error) {
        if (error.status === 409 && answerAlreadyExists(error.payload)) {
          // The server already holds this answer — most likely our own
          // earlier attempt landed and only its response was lost in
          // transit. That is a success, not a failure, so move on instead of
          // reporting an error that never actually happened.
          await show(await api.get(`/api/sessions/${state.id}`));
          return;
        }
        if (error.status === 409) {
          // The session itself has moved past the test step — most likely
          // this exact exam is also open in another tab that already
          // finished it. There is no earlier success to fall back on here,
          // and retrying will only 409 again, so say so plainly instead of
          // silently advancing into a state this tab never asked for.
          status.textContent =
            "이 시험은 이미 다른 탭에서 진행되어 채점 단계로 넘어갔습니다. 새로고침하여 현재 상태를 확인해 주세요.";
          status.className = "issues";
          const reload = document.createElement("button");
          reload.textContent = "새로고침";
          reload.addEventListener("click", () => window.location.reload());
          app.append(reload);
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

  await tryToPlay(app, status, machine);
}

// `waitUntilReady` gives up after a generous timeout rather than polling
// forever. On that timeout, tell the candidate preparation is taking longer
// than expected and let them choose to keep waiting, instead of leaving them
// looking at a screen that appears to have simply stopped.
async function waitForQuestions(app, api, sessionId) {
  const waiting = document.createElement("p");
  waiting.textContent = "문제를 준비하고 있습니다. 잠시만 기다려 주세요…";
  app.append(waiting);
  try {
    return await waitUntilReady(api, sessionId);
  } catch (error) {
    if (!error.timedOut) throw error;
    app.replaceChildren();
    const stuck = document.createElement("p");
    stuck.textContent = "문제 준비가 예상보다 오래 걸리고 있습니다.";
    stuck.className = "issues";
    const keepWaiting = document.createElement("button");
    keepWaiting.textContent = "계속 기다리기";
    app.append(stuck, keepWaiting);
    return new Promise((resolve, reject) => {
      keepWaiting.addEventListener("click", () => {
        app.replaceChildren();
        waitForQuestions(app, api, sessionId).then(resolve, reject);
      });
    });
  }
}

// The question audio can fail to load (a missing or corrupt TTS file). One
// retry is offered; if that also fails, recording starts anyway rather than
// leaving the candidate on a screen where 재생 and 다음 are both permanently
// disabled — losing the spoken prompt for one question is recoverable, being
// trapped for the rest of the 40-minute exam is not.
async function tryToPlay(app, status, machine, attempt = 1) {
  try {
    await machine.play();
  } catch (error) {
    console.error(error);
    if (attempt < 2) {
      status.textContent = "질문 음성을 재생할 수 없습니다.";
      status.className = "issues";
      const tryAgain = document.createElement("button");
      tryAgain.textContent = "다시 시도";
      tryAgain.addEventListener(
        "click",
        () => {
          tryAgain.remove();
          tryToPlay(app, status, machine, attempt + 1);
        },
        {once: true},
      );
      app.append(tryAgain);
      return;
    }
    status.textContent = "질문 음성을 재생할 수 없습니다. 답변을 바로 녹음해 주세요.";
    status.className = "issues";
    try {
      await machine.skip();
    } catch (micError) {
      console.error(micError);
      status.textContent = micError.message ?? "마이크를 사용할 수 없습니다.";
    }
  }
}
