// Step 3 — Setup. The only job here is to fail early: if the microphone is
// denied or silent, the candidate finds out now and not in the middle of the
// exam. The permission prompt happens here, once.
import {askForMicrophone, startRecording} from "../recorder.js";

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
  record.addEventListener("click", async () => {
    if (session) {
      const {blob} = await session.stop();
      session = null;
      player.src = URL.createObjectURL(blob);
      player.hidden = false;
      record.textContent = "다시 녹음";
      record.classList.remove("recording");
      status.textContent = "재생해서 목소리가 들리면 다음으로 진행하세요.";
      next.disabled = false;
      return;
    }
    try {
      const stream = await askForMicrophone();
      session = startRecording(stream);
      record.textContent = "녹음 중지";
      record.classList.add("recording");
      status.textContent = "녹음 중…";
    } catch (error) {
      status.textContent = error.message;
      status.className = "issues";
    }
  });

  next.addEventListener("click", async () => {
    next.disabled = true;
    await show(await api.send("POST", `/api/sessions/${state.id}/step`, {step: "sample"}));
  });

  app.append(explanation, record, player, status, next);
}
