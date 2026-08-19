from __future__ import annotations

# Text to speech. macOS `say`, because piper-tts ships an espeak-ng binary with
# the build machine's data path compiled into it and fails at import.
SAY_VOICE = "Samantha"
TTS_SAMPLE_RATE = 16000

# Speech to text.
WHISPER_MODEL = "medium"
WHISPER_COMPUTE_TYPE = "int8"

# The voice-activity contract. faster-whisper's defaults are 2000 and 400, under
# which no silence below about 1.2s can exist, the 0.5s merge threshold in
# core/metrics.py never fires, and pause_ratio collapses to 0.02 with
# mean_utterance_length at 75 — the exact numbers that made those metrics
# useless. Measured on evidence/sample-answer.wav; with the values below the
# same recording yields pause_ratio 0.23 and mean_utterance_length 6.8.
VAD_MIN_SILENCE_MS = 250
VAD_SPEECH_PAD_MS = 0

# The rater. Qwen3 8B runs at 5.3 tok/s on an M2 against 2.8 for the 14B, but
# measured against evidence/sample-transcript.json (see
# docs/superpowers/notes/2026-08-19-rater-model.md) the 8B failed 4 of 5 rating
# calls with a timeout at OLLAMA_TIMEOUT_S, and its one completed call
# duplicated one rubric dimension while omitting another. The 14B passed 5/5
# with all five dimensions distinct and zero evidence discarded.
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:14b"
OLLAMA_TIMEOUT_S = 600
