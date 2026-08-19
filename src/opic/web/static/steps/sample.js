// Step 4 — Sample Question. Not scored, not uploaded, and never sent to a
// model: the question is spoken by the browser's own voice so the sample costs
// nothing. What it rehearses is the mechanic — question plays, recording starts
// by itself, 다음 ends it.
import {askForMicrophone, startRecording} from "../recorder.js";

const SAMPLE_TEXT = "Let's start the interview. Tell me a little about yourself.";

export async function render(state, {api, show}) {
  const app = document.getElementById("app");
  const heading = document.createElement("h2");
  heading.textContent = "예시 문항 (점수에 반영되지 않습니다)";
  const note = document.createElement("p");
  note.textContent =
    "질문이 재생된 뒤 자동으로 녹음이 시작됩니다. 답변을 마치면 다음을 누르세요.";
  const status = document.createElement("p");
  const start = document.createElement("button");
  start.textContent = "시작";
  const next = document.createElement("button");
  next.textContent = "시험 시작";
  next.className = "secondary";
  next.disabled = true;

  let session = null;

  start.addEventListener("click", async () => {
    start.disabled = true;
    status.textContent = "질문 재생 중…";

    const speech = new SpeechSynthesisUtterance(SAMPLE_TEXT);
    speech.lang = "en-US";
    await new Promise((resolve) => {
      speech.onend = resolve;
      speech.onerror = resolve;
      speechSynthesis.speak(speech);
    });

    let stream;
    try {
      stream = await askForMicrophone();
    } catch (error) {
      status.textContent = error.message;
      status.className = "issues";
      start.disabled = false;
      return;
    }
    session = startRecording(stream);
    status.textContent = "녹음 중…";
    status.className = "recording";
    next.disabled = false;
  });

  next.addEventListener("click", async () => {
    next.disabled = true;
    // `session.stop()` already releases the microphone tracks once the final
    // chunk is in — recorder.js owns that now, so there is nothing left to
    // stop here.
    await session.stop();
    await show(await api.send("POST", `/api/sessions/${state.id}/step`, {step: "test"}));
  });

  app.append(heading, note, start, status, next);
}
