// Step 3 — Setup. The only job here is to fail early: if the microphone is
// denied or silent, the candidate finds out now and not in the middle of the
// exam. The permission prompt happens here, once.
import {askForMicrophone, startRecording} from "../recorder.js";
import {SILENCE_PEAK, levelMeter} from "../meter.js";

export async function render(state, {api, show}) {
  const app = document.getElementById("app");
  const explanation = document.createElement("p");
  explanation.textContent =
    "마이크를 점검합니다. 녹음 버튼을 누르고 몇 초간 말한 뒤, 재생하여 소리가 들리는지 확인해 주세요.";

  const record = document.createElement("button");
  record.textContent = "녹음 시작";
  const player = document.createElement("audio");
  player.controls = true;
  player.hidden = true;
  const status = document.createElement("p");
  const next = document.createElement("button");
  next.textContent = "다음";
  next.disabled = true;
  next.className = "secondary";

  let session = null;
  let meter = null;
  record.addEventListener("click", async () => {
    if (session) {
      // Stopping is not instant — session.stop() waits on a final data chunk.
      // Without this, a second click in that window re-enters this branch and
      // calls meter.stop() a second time, which closes an already-closed
      // AudioContext. The finally is what makes that safe even when stop()
      // itself throws — without it, a rejected stop() would leave the button
      // disabled forever and the app still believing a recording is running.
      record.disabled = true;
      try {
        const {blob} = await session.stop();
        session = null;
        const peak = meter.peak();
        meter.stop();
        meter.element?.remove();
        meter = null;
        player.src = URL.createObjectURL(blob);
        player.hidden = false;
        record.textContent = "다시 녹음";
        record.classList.remove("recording");
        if (peak !== null && peak < SILENCE_PEAK) {
          // A warning and not a block: a meter bug or an unusual device must
          // not be able to strand somebody before the exam has started.
          // `null` is a meter that could not measure, which is not evidence
          // of silence.
          status.textContent =
            "목소리가 거의 감지되지 않았습니다. 입력 장치와 음량을 확인한 뒤 다시 녹음해 보세요. 그대로 진행할 수도 있습니다.";
          status.className = "issues";
        } else {
          status.textContent = "재생해서 목소리가 들리면 다음으로 진행하세요.";
          status.className = "";
        }
        next.disabled = false;
      } catch (error) {
        // session.stop() itself failed — the recorder, not just the meter.
        // The candidate needs to know the recording did not come back, and
        // needs a clean slate to try again rather than a button stuck
        // mid-stop. release() (not stop()) because the recorder is already
        // broken; it only needs the microphone handed back.
        console.error(error);
        session.release();
        session = null;
        meter.stop();
        meter.element?.remove();
        meter = null;
        record.textContent = "녹음 시작";
        record.classList.remove("recording");
        status.textContent = "녹음을 마치지 못했습니다. 다시 시도해 주세요.";
        status.className = "issues";
      } finally {
        record.disabled = false;
      }
      return;
    }
    // getUserMedia() neither resolves nor rejects while the browser's own
    // permission prompt is on screen — without this line the page looks
    // frozen for however long the candidate takes to answer it.
    record.disabled = true;
    status.textContent = "브라우저의 마이크 권한 요청을 확인하고 허용해 주세요.";
    status.className = "";
    try {
      const stream = await askForMicrophone();
      session = startRecording(stream);
      meter = levelMeter(session.stream);
      if (meter.element) status.after(meter.element);
      record.textContent = "녹음 중지";
      record.classList.add("recording");
      status.textContent = "녹음 중…";
    } catch (error) {
      status.textContent = error.message;
      status.className = "issues";
    } finally {
      record.disabled = false;
    }
  });

  next.addEventListener("click", async () => {
    next.disabled = true;
    try {
      await show(await api.send("POST", `/api/sessions/${state.id}/step`, {step: "sample"}));
    } catch (error) {
      status.textContent = "서버와 연결할 수 없습니다. 다시 시도해 주세요.";
      status.className = "issues";
      next.disabled = false;
    }
  });

  app.append(explanation, record, player, status, next);
}
