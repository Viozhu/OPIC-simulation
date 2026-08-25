// What is on screen while an answer is being recorded: the level bar, and how
// long you have been talking. Neither judges anything — the exam never warns
// about a quiet answer, because a warning a candidate cannot act on is noise
// in the middle of a timed test.
import {levelMeter} from "./meter.js";

export function recordingPanel(stream) {
  const element = document.createElement("div");
  element.className = "panel";

  const meter = levelMeter(stream);
  if (meter.element) element.append(meter.element);

  const clock = document.createElement("span");
  clock.className = "clock";
  clock.textContent = "0:00";
  element.append(clock);

  const started = Date.now();
  const paint = () => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    clock.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  };
  const ticking = setInterval(paint, 1000);

  return {
    element,
    stop() {
      clearInterval(ticking);
      meter.stop();
    },
  };
}
