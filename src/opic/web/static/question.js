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
  const deadline = Date.now() + timeoutMs;
  while (true) {
    if (Date.now() >= deadline) {
      throw Object.assign(new Error("question preparation timed out"), {timedOut: true});
    }
    try {
      const state = await api.get(`/api/sessions/${sessionId}`);
      if (state.questions_ready) return state;
    } catch (error) {
      // A dropped fetch here looks identical to a server that is still
      // preparing questions; keep polling instead of throwing out of
      // render() and leaving a blank page — the deadline above still applies.
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}

export function askAndRecord({audioUrl, onState}) {
  // Returns {play, replay, skip, stop}: the caller owns the buttons, this
  // owns the state machine. `replay` is allowed exactly once, as in the real
  // exam.
  let stream = null;
  let session = null;
  let replays = 0;
  const audio = new Audio(audioUrl);

  // The recording is paused while the question plays over the speakers, and
  // resumed the moment it stops. Two things fall out of that: the question
  // cannot leak into the answer at all (echo cancellation only ever attenuated
  // it), and the seconds spent listening are not in the recording, so nothing
  // downstream has to subtract them — the answer is as long as the answer.
  //
  // This only ever applies to the replay. On the first playthrough the
  // microphone is not open yet, and `session` is null, so both calls are
  // no-ops.
  //
  // `ended` fires on a replay that ran out; `pause` on one cut short by 다음.
  // Both lift the same pause, and `paused` is what makes the second one a
  // no-op — including the `pause` event 다음 queues, which lands after the
  // recorder has already stopped and would otherwise put "녹음 중" back on a
  // screen that is already uploading.
  let paused = false;

  function liftPause(announce) {
    if (!paused) return;
    paused = false;
    session.resume();
    if (announce) onState("recording", {stream});
  }

  const resumeRecording = () => liftPause(true);
  audio.addEventListener("ended", resumeRecording);
  audio.addEventListener("pause", resumeRecording);
  // A replay that dies after it started — a decode failure, a range request
  // the tunnel dropped — is not required to fire `pause` as well. Without this
  // listener that leaves the recorder paused with nothing left to lift it, and
  // the candidate keeps talking into a recording that is not happening.
  audio.addEventListener("error", resumeRecording);

  async function beginRecording() {
    stream = await askForMicrophone();
    session = startRecording(stream);
    // The caller owns what is on screen, so it is the caller that gets the
    // stream — the panel it mounts must attach to this microphone and not ask
    // for another one.
    onState("recording", {stream});
  }

  async function play() {
    onState("playing", {});
    await audio.play();
    await new Promise((resolve) => audio.addEventListener("ended", resolve, {once: true}));
    await beginRecording();
  }

  async function replay() {
    if (replays >= 1) return false;
    replays += 1;
    audio.currentTime = 0;
    // Paused before the audio starts, not after: a pause that lands late
    // leaves the first word of the question inside the answer, which is the
    // whole thing this avoids.
    if (session !== null) {
      session.pause();
      paused = true;
      onState("replaying", {});
    }
    try {
      await audio.play();
    } catch (error) {
      // play() rejected, so neither `ended` nor `pause` is coming and nothing
      // else would ever lift the pause — the candidate would be left talking
      // into a recorder that is not recording. Undo it here and let the
      // caller see the failure.
      //
      // The replay is handed back too. The ordinary way this rejects is 다음
      // pressed while play() is still pending: `stop()` pauses the audio and
      // the promise aborts. That case is over anyway — but a genuine playback
      // failure must not cost the candidate the one replay they get without
      // ever having heard it.
      replays -= 1;
      resumeRecording();
      throw error;
    }
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
    // A replay left running past 다음 would otherwise keep talking over the
    // next question's screen, whether the stop below succeeds or not.
    audio.pause();
    // The `pause` event that lands here is a queued task, so it arrives after
    // `session.stop()` has already run. Lifting the pause inline is what makes
    // sure the recorder is not still paused when it is asked to stop — and
    // silently, since the screen is on its way to "uploading" and has no use
    // for one last "recording".
    liftPause(false);
    let recorded;
    try {
      // `session.stop()` releases the microphone tracks itself once the
      // final chunk of data is in; stopping them again here would be a
      // double-stop racing the recorder's own cleanup.
      recorded = await session.stop();
    } catch (error) {
      // A synchronous throw out of MediaRecorder never reaches `onstop`, so
      // the tracks are still held — release() is what frees the microphone
      // when stop() itself failed. `stop()` owns no screen to report onto,
      // so it only tears down what "recording" put up — the same
      // "uploading" transition a successful stop fires — and rethrows so the
      // caller can actually tell the candidate something went wrong.
      session.release();
      onState("uploading", {});
      throw error;
    }
    onState("uploading", {});
    // Empty, always: the replay is not in this recording any more. The field
    // stays because the upload still carries it and the server still parses
    // it — sessions recorded before this change have real spans on disk, and
    // the metrics that subtract them are still the ones reading those.
    return {...recorded, replaySpans: []};
  }

  return {play, replay, skip, stop, replaysLeft: () => 1 - replays};
}

export async function uploadWithRetries(api, path, blob, filename, fields = {}, attempts = 3) {
  let last = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await api.upload(path, blob, filename, fields);
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
