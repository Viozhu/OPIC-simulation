// The level bar: proof, while recording, that something is being heard.
//
// Decoration on a critical path. Every branch here is wrapped and every
// failure returns a meter that draws nothing, because a browser that will not
// hand over an AudioContext must cost the candidate a bar and not an exam.

// The RMS peak below which a recording is treated as silence. Chosen, not
// measured: well under speech, well over the noise floor of a laptop
// microphone in a quiet room. Only the setup step acts on it, and only by
// warning — see steps/setup.js.
export const SILENCE_PEAK = 0.02;

// A full bar at this RMS. Speech rarely goes past it, and a bar that only ever
// moves in its bottom tenth reads as broken.
const FULL_SCALE = 0.2;

const DEAF = {element: null, peak: () => null, stop: () => {}};

export function levelMeter(stream) {
  let context = null;
  try {
    const Context = window.AudioContext ?? window.webkitAudioContext;
    if (!Context) return DEAF;
    context = new Context();
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(stream).connect(analyser);

    const element = document.createElement("div");
    element.className = "meter";
    // The status line and the clock next to it already say what is happening;
    // a bar that announces a number many times a second would only get in the
    // way of a screen reader.
    element.setAttribute("aria-hidden", "true");
    const fill = document.createElement("span");
    fill.className = "meter__fill";
    element.append(fill);

    // The byte view, not the float one: it is the older API and the one every
    // target browser has had for years.
    const samples = new Uint8Array(analyser.fftSize);
    let peak = 0;
    let running = true;

    const tick = () => {
      if (!running) return;
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) {
        const centred = (sample - 128) / 128;
        sum += centred * centred;
      }
      const rms = Math.sqrt(sum / samples.length);
      if (rms > peak) peak = rms;
      fill.style.width = `${Math.min(100, (rms / FULL_SCALE) * 100)}%`;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);

    return {
      element,
      peak: () => peak,
      stop() {
        running = false;
        try {
          context.close();
        } catch (error) {
          // A context that will not close is not worth a broken screen.
        }
      },
    };
  } catch (error) {
    // The console keeps the real cause for whoever debugs this; the candidate
    // gets a screen that behaves exactly as it did before there was a meter.
    console.error(error);
    try {
      context?.close();
    } catch (ignored) {}
    return DEAF;
  }
}
