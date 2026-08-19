// The mechanics of one question: play it, record the answer, hand back the
// blob. Both the sample question and the real test run this, so the sample is
// a genuine rehearsal and not a different code path.
import {askForMicrophone, startRecording} from "./recorder.js";

const POLL_MS = 3000;

export async function waitUntilReady(api, sessionId) {
  let state = await api.get(`/api/sessions/${sessionId}`);
  while (!state.questions_ready) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    state = await api.get(`/api/sessions/${sessionId}`);
  }
  return state;
}

export function askAndRecord({audioUrl, onState}) {
  // Returns {play, replay, stop}: the caller owns the buttons, this owns the
  // state machine. `replay` is allowed exactly once, as in the real exam.
  let stream = null;
  let session = null;
  let replays = 0;
  const audio = new Audio(audioUrl);

  async function play() {
    onState("playing");
    await audio.play();
    await new Promise((resolve) => audio.addEventListener("ended", resolve, {once: true}));
    stream = await askForMicrophone();
    session = startRecording(stream);
    onState("recording");
  }

  async function replay() {
    if (replays >= 1) return false;
    replays += 1;
    audio.currentTime = 0;
    await audio.play();
    return true;
  }

  async function stop() {
    // `session.stop()` releases the microphone tracks itself once the final
    // chunk of data is in; stopping them again here would be a double-stop
    // racing the recorder's own cleanup.
    const recorded = await session.stop();
    onState("uploading");
    return recorded;
  }

  return {play, replay, stop, replaysLeft: () => 1 - replays};
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
