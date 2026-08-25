// Step 4 — Sample Question. Not scored, not uploaded, and never sent to a
// model: the question is spoken by the browser's own voice so the sample costs
// nothing. What it rehearses is the mechanic — question plays, recording starts
// by itself, 다음 ends it.
import {askForMicrophone, startRecording} from "../recorder.js";
import {recordingPanel} from "../panel.js";

const SAMPLE_TEXT = "Let's start the interview. Tell me a little about yourself.";
// speak() can hang forever on a machine with speechSynthesis but zero
// installed voices: speak() then fires neither onend nor onerror. Ten seconds
// is generous for one sentence, and it is what stops that from being a dead
// screen.
const SPEECH_TIMEOUT_MS = 10000;

// Resolves true if the sentence was actually spoken, false if there is no
// voice to speak it with or speaking it took too long — never rejects, and
// never hangs.
async function speak(text) {
  if (!("speechSynthesis" in window) || speechSynthesis.getVoices().length === 0) {
    return false;
  }
  const speech = new SpeechSynthesisUtterance(text);
  speech.lang = "en-US";
  const spoke = await Promise.race([
    new Promise((resolve) => {
      speech.onend = () => resolve(true);
      speech.onerror = () => resolve(false);
      speechSynthesis.speak(speech);
    }),
    new Promise((resolve) => setTimeout(() => resolve(false), SPEECH_TIMEOUT_MS)),
  ]);
  if (!spoke) speechSynthesis.cancel(); // in case the timeout won and it is still talking
  return spoke;
}

export async function render(state, {api, show}) {
  const app = document.getElementById("app");
  const heading = document.createElement("h2");
  heading.textContent = "예시 문항 (점수에 반영되지 않습니다)";
  const note = document.createElement("p");
  note.textContent =
    "질문이 재생된 뒤 자동으로 녹음이 시작됩니다. 답변을 마치면 다음을 누르세요.";
  const questionText = document.createElement("p");
  questionText.textContent = `"${SAMPLE_TEXT}"`;
  questionText.hidden = true;
  const status = document.createElement("p");
  status.setAttribute("aria-live", "polite");
  const start = document.createElement("button");
  start.textContent = "시작";
  const next = document.createElement("button");
  next.textContent = "시험 시작";
  next.className = "secondary";
  next.disabled = true;

  let session = null;
  let panel = null;

  start.addEventListener("click", async () => {
    start.disabled = true;
    status.textContent = "질문 재생 중…";

    const spoken = await speak(SAMPLE_TEXT);
    if (!spoken) {
      // No voice installed, or the browser hung trying: the sample is a
      // rehearsal of the mechanic, not scored, so losing the spoken prompt
      // is survivable — being trapped here is not. Show the text and move
      // straight on to recording.
      questionText.hidden = false;
      status.textContent = "이 기기에서는 음성을 재생할 수 없습니다. 위 문장을 보고 답변해 주세요.";
    }

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
    panel = recordingPanel(session.stream);
    status.after(panel.element);
    status.textContent = "녹음 중…";
    status.className = "recording";
    next.disabled = false;
  });

  next.addEventListener("click", async () => {
    next.disabled = true;
    try {
      // `session.stop()` already releases the microphone tracks once the
      // final chunk is in — recorder.js owns that now, so there is nothing
      // left to stop here on success.
      await session.stop();
    } catch (error) {
      // A synchronous throw out of MediaRecorder never reaches `onstop`, so
      // the tracks are still held — release() is what frees the microphone
      // when stop() itself failed. The sample is not scored, so the cheapest
      // way to recover is to let the candidate start it over rather than
      // strand them with 다음 disabled and no working session.
      console.error(error);
      session.release();
      panel.stop();
      panel.element.remove();
      status.textContent = "녹음을 마치지 못했습니다. 처음부터 다시 시도해 주세요.";
      status.className = "issues";
      start.disabled = false;
      return;
    }
    panel.stop();
    panel.element.remove();
    try {
      await show(await api.send("POST", `/api/sessions/${state.id}/step`, {step: "test"}));
    } catch (error) {
      status.textContent = "서버와 연결할 수 없습니다. 다시 시도해 주세요.";
      status.className = "issues";
      next.disabled = false;
    }
  });

  app.append(heading, note, questionText, start, status, next);
}
