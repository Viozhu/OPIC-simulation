// Microphone access and recording, in one place: the Setup step and the Test
// step must behave identically, and the browser's supported MIME type is
// decided once, here.
const CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

export function supportedType() {
  return CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? "";
}

// The question is played over the speakers while the microphone is live, so
// without echo cancellation a candidate answering without headphones records
// the question along with their answer — and Whisper transcribes it. Those
// words then reach the rater as if the candidate had said them, which is the
// one way this leak can move a grade.
//
// Browsers turn this on by default, but a default is not a decision: it is
// stated here so it cannot quietly change underneath the exam. `true` and not
// `{exact: true}` — an exact constraint a device cannot meet fails
// getUserMedia outright, and losing the microphone costs the candidate far
// more than the leak does. `noiseSuppression` and `autoGainControl` are left
// alone deliberately: both reshape the speech itself, and pauses and word
// confidence are measured from it.
const AUDIO_CONSTRAINTS = {echoCancellation: true};

export async function askForMicrophone() {
  try {
    return await navigator.mediaDevices.getUserMedia({audio: AUDIO_CONSTRAINTS});
  } catch (error) {
    // The Korean message is for the candidate; the console keeps the real
    // cause (denied permission, no device, hardware error) for whoever has
    // to debug this later.
    console.error(error);
    throw new Error("마이크 권한이 필요합니다. 브라우저 설정에서 허용해 주세요.", {cause: error});
  }
}

export function startRecording(stream) {
  const type = supportedType();
  const recorder = new MediaRecorder(stream, type ? {mimeType: type} : undefined);
  const chunks = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  recorder.start();

  return {
    // The live stream, so a caller can attach a meter to the same microphone
    // rather than asking for it a second time — a second getUserMedia is a
    // second prompt on some browsers and a second thing that can fail.
    stream,
    stop() {
      return new Promise((resolve) => {
        recorder.onstop = () => {
          // MediaRecorder.stop() leaves the tracks live. Releasing them here is
          // what turns the recording indicator off.
          stream.getTracks().forEach((track) => track.stop());
          const blob = new Blob(chunks, {type: recorder.mimeType});
          const extension = recorder.mimeType.includes("mp4") ? "mp4" : "webm";
          resolve({blob, filename: `answer.${extension}`});
        };
        recorder.stop();
      });
    },
    // For a caller that abandons a recording without ever calling stop() —
    // releases the microphone without waiting for a final data chunk.
    release() {
      stream.getTracks().forEach((track) => track.stop());
    },
  };
}
