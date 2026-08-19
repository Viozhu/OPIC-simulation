from __future__ import annotations

from pathlib import Path

from opic.adapters import config
from opic.core.transcript import Span, Transcript, Word

SAMPLING_RATE = 16000


def spans_from_timestamps(
    timestamps: list[dict],
    sampling_rate: int = SAMPLING_RATE,
) -> tuple[Span, ...]:
    """Convert voice-activity timestamps from samples into seconds."""
    return tuple(
        Span(t["start"] / sampling_rate, t["end"] / sampling_rate) for t in timestamps
    )


class WhisperSpeechToText:
    """faster-whisper, tuned so it does not repair the speaker's grammar.

    `condition_on_previous_text=False` and `temperature=0.0` are what keep the
    errors in: with the defaults the model inserts elided subjects and rewrites
    tense, deleting roughly five real mistakes per ninety seconds.

    The VAD options come from config and are load-bearing — see the note there.
    """

    def __init__(
        self,
        model_size: str = config.WHISPER_MODEL,
        compute_type: str = config.WHISPER_COMPUTE_TYPE,
    ) -> None:
        self._model_size = model_size
        self._compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type=self._compute_type
            )
        return self._model

    def transcribe(self, audio: Path) -> Transcript:
        from faster_whisper import vad
        from faster_whisper.audio import decode_audio

        model = self._load()
        options = vad.VadOptions(
            min_silence_duration_ms=config.VAD_MIN_SILENCE_MS,
            speech_pad_ms=config.VAD_SPEECH_PAD_MS,
        )
        segments, info = model.transcribe(
            str(audio),
            language="en",
            word_timestamps=True,
            condition_on_previous_text=False,
            temperature=0.0,
            vad_filter=True,
            vad_parameters=options,
        )

        text_parts: list[str] = []
        words: list[Word] = []
        for segment in segments:
            text_parts.append(segment.text)
            for w in segment.words or ():
                words.append(Word(w.word, w.start, w.end, w.probability))

        pcm = decode_audio(str(audio), sampling_rate=SAMPLING_RATE)
        spans = spans_from_timestamps(
            vad.get_speech_timestamps(pcm, options, sampling_rate=SAMPLING_RATE),
            sampling_rate=SAMPLING_RATE,
        )

        return Transcript(
            text="".join(text_parts).strip(),
            words=tuple(words),
            speech_spans=spans,
            duration_s=info.duration,
        )
