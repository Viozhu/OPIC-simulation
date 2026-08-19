// Microphone access and recording, in one place: the Setup step and the Test
// step must behave identically, and the browser's supported MIME type is
// decided once, here.
const CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

export function supportedType() {
  return CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? "";
}

export async function askForMicrophone() {
  try {
    return await navigator.mediaDevices.getUserMedia({audio: true});
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
