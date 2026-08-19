// The mechanics of one question: play it, record the answer, hand back the
// blob. Both the sample question and the real test run this, so the sample is
// a genuine rehearsal and not a different code path.
import {askForMicrophone, startRecording} from "./recorder.js";

const POLL_MS = 3000;
// A generous ceiling on how long "문제를 준비하고 있습니다" is allowed to sit
// silently polling. Past this, the caller is handed control back instead of
// spinning forever on a generation that stalled.
const READY_TIMEOUT_MS = 5 * 60 * 1000;

export async function waitUntilReady(api, sessionId, timeoutMs = READY_TIMEOUT_MS) {
  let state = await api.get(`/api/sessions/${sessionId}`);
  const deadline = Date.now() + timeoutMs;
  while (!state.questions_ready) {
    if (Date.now() >= deadline) {
      throw Object.assign(new Error("question preparation timed out"), {timedOut: true});
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    state = await api.get(`/api/sessions/${sessionId}`);
  }
  return state;
}

export function askAndRecord({audioUrl, onState}) {
  // Returns {play, replay, skip, stop}: the caller owns the buttons, this
  // owns the state machine. `replay` is allowed exactly once, as in the real
  // exam.
  let stream = null;
  let session = null;
  let replays = 0;
  const audio = new Audio(audioUrl);

  async function beginRecording() {
    stream = await askForMicrophone();
    session = startRecording(stream);
    onState("recording");
  }

  async function play() {
    onState("playing");
    await audio.play();
    await new Promise((resolve) => audio.addEventListener("ended", resolve, {once: true}));
    await beginRecording();
  }

  async function replay() {
    if (replays >= 1) return false;
    replays += 1;
    audio.currentTime = 0;
    await audio.play();
    return true;
  }

  async function skip() {
    // The question audio could not be played after retrying. The candidate
    // still has to answer something, so recording starts anyway rather than
    // trapping them on a screen that will never move — there is nothing left
    // to replay, so replaysLeft() reports zero from here on.
    replays = 1;
    if (session) return;
    await beginRecording();
  }

  async function stop() {
    // `session.stop()` releases the microphone tracks itself once the final
    // chunk of data is in; stopping them again here would be a double-stop
    // racing the recorder's own cleanup.
    const recorded = await session.stop();
    // A replay left running past 다음 would otherwise keep talking over the
    // next question's screen.
    audio.pause();
    onState("uploading");
    return recorded;
  }

  return {play, replay, skip, stop, replaysLeft: () => 1 - replays};
}

export async function uploadWithRetries(api, path, blob, filename, attempts = 3) {
  let last = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await api.upload(path, blob, filename);
    } catch (error) {
      // A 409 is the server deliberately refusing a second upload for this
      // index, not a dropped connection — retrying it changes nothing but the
      // wait, so it is rethrown immediately instead of being retried like a
      // transport failure.
      if (error.status === 409) throw error;
      last = error;
      await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
    }
  }
  throw last;
}
