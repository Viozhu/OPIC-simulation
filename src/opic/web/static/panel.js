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

  // The clock counts recorded seconds, not seconds on screen: 재생 pauses the
  // recorder, and a clock that kept running through it would tell the
  // candidate their answer is longer than the one being graded.
  let started = Date.now();
  let banked = 0;
  let ticking = null;

  const paint = () => {
    const running = ticking === null ? 0 : Date.now() - started;
    const seconds = Math.floor((banked + running) / 1000);
    clock.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  };
  ticking = setInterval(paint, 1000);

  return {
    element,
    pause() {
      if (ticking === null) return;
      banked += Date.now() - started;
      clearInterval(ticking);
      ticking = null;
      // The level bar keeps moving — it is drawn from the live microphone,
      // which a paused recorder does not close. Dimming the panel is what
      // stops that from reading as "still recording".
      element.classList.add("paused");
      paint();
    },
    resume() {
      if (ticking !== null) return;
      started = Date.now();
      ticking = setInterval(paint, 1000);
      element.classList.remove("paused");
    },
    stop() {
      if (ticking !== null) clearInterval(ticking);
      ticking = null;
      meter.stop();
    },
  };
}
