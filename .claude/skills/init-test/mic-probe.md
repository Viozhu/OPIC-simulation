# Splitting "I cannot hear my voice" into two different bugs

Step 3 shows an `<audio controls>` after recording and asks the candidate to
press play. When they report hearing nothing, two causes look identical on
screen and are fixed in opposite ways:

- **The microphone captured nothing.** Ask about the hardware mute switch
  first — headsets have one, it costs nothing to check, and it is what this
  turned out to be on 2026-08-21 after the browser and the OS had both been
  cleared. Then the OS permission (macOS: Ajustes → Privacidad y seguridad →
  Micrófono — a browser can hold web permission without it), then the selected
  input device. No code is at fault in any of the three.
- **Something was captured and will not play.** `MediaRecorder.start()` is
  called without a `timeslice`, so the WebM carries no duration in its header;
  `player.duration` comes back `Infinity`. That one is ours, in `recorder.js`.

Do not guess between them. Measure the blob: bytes, decoded duration, and peak
amplitude. Peak is the datum that decides it — bytes alone cannot tell silence
from speech, because a recording of silence is not an empty file.

## Apply

Keep a copy of the original first, so restoring is a `cp` and not an edit:

```bash
cp src/opic/web/static/steps/setup.js /tmp/setup.js.orig
```

In `setup.js`, append `probe(blob, diagnostics)` where the recording stops, add
a `<pre>` to the DOM, and paste the function below. Then have the candidate
reload with **Cmd+Shift+R** — a soft reload serves the cached module and the
probe never runs, which reads exactly like the probe failing.

```js
// TEMPORARY DIAGNOSTIC — not part of the product.
async function probe(blob, into) {
  into.hidden = false;
  into.textContent = `blob: ${blob.size} bytes, type ${blob.type || "(none)"}`;
  try {
    const context = new AudioContext();
    const audio = await context.decodeAudioData(await blob.arrayBuffer());
    const data = audio.getChannelData(0);
    let peak = 0;
    for (let i = 0; i < data.length; i++) peak = Math.max(peak, Math.abs(data[i]));
    await context.close();
    const player = document.querySelector("#app audio");
    into.textContent =
      `blob: ${blob.size} bytes, type ${blob.type}\n` +
      `decoded: ${audio.duration.toFixed(2)}s @ ${audio.sampleRate} Hz\n` +
      `peak: ${peak.toFixed(4)}   player.duration: ${player?.duration}\n` +
      (peak < 0.01 ? "→ SILENCIO: el micro no capturó nada"
                   : "→ HAY SONIDO: el fallo es la reproducción");
  } catch (error) {
    into.textContent += `\ndecodeAudioData FAILED: ${error.name}: ${error.message}`;
  }
}
```

## Revert

The probe is diagnostic scaffolding, not a feature. Restore before committing
anything, or it ships:

```bash
cp /tmp/setup.js.orig src/opic/web/static/steps/setup.js
git status --porcelain src/opic/web/static/steps/setup.js   # debe salir vacío
```
