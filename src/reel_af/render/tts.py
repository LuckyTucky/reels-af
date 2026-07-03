"""Sample-accurate sentence-by-sentence TTS via OpenRouter (Gemini Flash).

The TTS engine already knows when it speaks each word, but doesn't expose
those timings. Recovering them via ASR drifts 200-500 ms and occasionally
hallucinates. Instead, chop the script into sentences, synthesize each one
as its own WAV, measure it with ffprobe, then concatenate. Sentence
boundaries on the final audio are sample-accurate; words inside are
distributed by syllable count over the measured sentence span.

Inline Gemini TTS audio tags ([curious], [emphasis], …) must stay attached
to whichever sentence they precede. We split on spoken-text punctuation
but pass the with-tags sentence to the TTS engine so the model gets its
stage directions.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import subprocess
import wave
from pathlib import Path
from typing import Optional

from agentfield.media_providers import OpenRouterProvider

# The runtime patch that adds OpenRouterProvider.generate_speech() must
# be imported before we call generate_speech.
import reel_af.sdk_patches  # noqa: F401
from reel_af.models import WordTiming
from reel_af.render import cost as cost_track

# ───── Constants ─────────────────────────────────────────────────────

# Gemini 3.1 Flash TTS via OpenRouter /audio/speech. Picked because it
# supports 200+ inline audio tags ([curious], [emphasis], [confident])
# that steer delivery without polluting the spoken text.
DEFAULT_TTS_MODEL = "google/gemini-3.1-flash-tts-preview"

# Gemini Flash TTS streams PCM @ 24kHz mono 16-bit.
TTS_SAMPLE_RATE = 24000

# Audio speed multiplier applied to every per-sentence WAV via ffmpeg
# atempo. Gemini Flash TTS reads at ~100-130 WPM regardless of prompt;
# atempo preserves pitch while compressing the timeline to a tight
# 18-25s reel. 1.5+ starts sounding rushed; below 1.3 still drags.
_AUDIO_SPEED_FACTOR = 1.35

# Gemini voice map by tone. Picks below are the most reliable for
# English narration in each register.
_VOICE_BY_TONE: dict[str, str] = {
    "urgent":  "Charon",      # deep, serious — gravitas
    "wonder":  "Kore",        # warm, curious — default scientific narrator
    "deadpan": "Schedar",     # neutral, measured
    "earnest": "Aoede",       # friendly, warm
    "playful": "Puck",        # bright, conversational
}

_TAG_RE = re.compile(r"\[[^\]]*\]")
_SENTENCE_END = re.compile(r"[.!?]+(?:[\"'’”])?\s*$")


# ───── Public helpers ────────────────────────────────────────────────


def voice_for_tone(tone: str) -> str:
    """Pick a Gemini voice that matches the script's tone."""
    return _VOICE_BY_TONE.get(tone, "Kore")


def strip_tts_tags(text: str) -> str:
    """Remove ``[...]`` Gemini TTS stage-direction tags and collapse
    whitespace. The spoken audio never contains the tag text, so the
    word list we tile against the audio must exclude them.
    """
    stripped = _TAG_RE.sub(" ", text)
    return " ".join(stripped.split())


# ───── Internal helpers ──────────────────────────────────────────────


def _wrap_pcm16_bytes_as_wav(
    pcm: bytes, sample_rate: int = TTS_SAMPLE_RATE, channels: int = 1,
) -> bytes:
    """Wrap raw little-endian 16-bit PCM samples in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def _sdk_generate_wav(
    tagged_script: str, voice: str, model: str, timeout: float = 300.0,
) -> bytes:
    """Generate a complete WAV via AgentField's SDK + Gemini TTS.

    Returns ready-to-write WAV bytes (header + PCM). Gemini outputs raw
    PCM at 24 kHz mono 16-bit; we add the WAV header locally.
    """
    provider = OpenRouterProvider()
    pcm = await provider.generate_speech(  # type: ignore[attr-defined]
        text=tagged_script,
        model=model,
        voice=voice,
        response_format="pcm",
        timeout=timeout,
    )
    if not pcm:
        raise RuntimeError(
            f"reel_af.render.tts: generate_speech returned no audio for "
            f"model {model}"
        )
    # OpenRouter /audio/speech renvoie des octets bruts, sans info de coût —
    # on logue au moins la taille du texte envoyé pour garder une trace.
    cost_track.add("tts", None, model=model, chars=len(tagged_script))
    return _wrap_pcm16_bytes_as_wav(pcm)


def _probe_duration(audio_path: Path) -> float:
    """Return the audio file's duration in seconds via ffprobe."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _split_sentences_with_tags(narration: str) -> list[str]:
    """Split ``narration`` into sentence strings that PRESERVE any
    inline TTS tags. We split by spoken-text punctuation so tags
    travel with the sentence they precede.

    Em-dashes and commas do NOT split. Only ``.``, ``!``, ``?``.
    """
    sentences: list[str] = []
    current: list[str] = []
    for tok in narration.split():
        current.append(tok)
        if _SENTENCE_END.search(tok):
            sentences.append(" ".join(current))
            current = []
    if current:
        sentences.append(" ".join(current))
    return sentences


def _syllables(word: str) -> int:
    """Cheap syllable estimate: count vowel groups; acronyms count letters."""
    if word.isupper() and len(re.sub(r"[^A-Z]", "", word)) >= 2:
        return max(1, len(re.sub(r"[^A-Z]", "", word)))
    norm = re.sub(r"[^a-z]", "", word.lower())
    if not norm:
        return 1
    groups = re.findall(r"[aeiouy]+", norm)
    return max(1, len(groups))


async def _atempo_speed_up(
    in_wav: Path, out_wav: Path, factor: float,
) -> None:
    """Speed up ``in_wav`` by ``factor`` using ffmpeg ``atempo``.

    Preserves pitch (atempo only changes tempo). The output WAV has
    identical PCM params (rate, channels, sample width) to the input
    — required for the subsequent native-wave concat to work.
    """
    if abs(factor - 1.0) < 0.001:
        out_wav.write_bytes(in_wav.read_bytes())
        return
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(in_wav),
        "-filter:a", f"atempo={factor:.3f}",
        "-c:a", "pcm_s16le",
        "-ar", str(TTS_SAMPLE_RATE),
        str(out_wav),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"_atempo_speed_up: ffmpeg failed ({proc.returncode}): "
            f"{stderr.decode(errors='replace')[-400:]}"
        )


def _concat_wavs_native(wav_paths: list[Path], out_path: Path) -> None:
    """Concatenate WAV files by re-reading raw PCM and rewriting one
    container. Works for identical PCM params — which our TTS always
    produces. Avoids spawning ffmpeg and works on macOS/Linux/Windows.
    """
    if not wav_paths:
        raise ValueError("_concat_wavs_native: no inputs")

    first = wave.open(str(wav_paths[0]), "rb")
    params = first.getparams()
    first.close()

    with wave.open(str(out_path), "wb") as out_wav:
        out_wav.setparams(params)
        for wav_path in wav_paths:
            with wave.open(str(wav_path), "rb") as in_wav:
                if in_wav.getparams()[:3] != params[:3]:
                    raise RuntimeError(
                        f"_concat_wavs_native: PCM param mismatch on "
                        f"{wav_path.name} — cannot concat"
                    )
                out_wav.writeframes(
                    in_wav.readframes(in_wav.getnframes())
                )


# ───── Single-shot TTS (used for one sentence at a time) ─────────────


async def synthesize_audio_single(
    narration: str,
    voice: str,
    out_dir: Path,
    model: Optional[str] = None,
) -> tuple[Path, float]:
    """Single TTS call → ``(audio_path, duration_s)``.

    ``narration`` must include any inline Gemini tags ([curious],
    [emphasis], …) — they're stage directions Gemini interprets but
    never speaks. They appear in the script verbatim and do NOT
    appear in the synthesized audio.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tts_model = model or os.environ.get("REEL_AF_TTS_MODEL", DEFAULT_TTS_MODEL)

    wav_bytes = await _sdk_generate_wav(
        tagged_script=narration,
        voice=voice,
        model=tts_model,
    )
    full_audio_path = out_dir / "full.wav"
    full_audio_path.write_bytes(wav_bytes)
    duration_s = _probe_duration(full_audio_path)
    return full_audio_path, duration_s


# ───── Public entrypoint — sentence-by-sentence aligned synthesis ────


async def synthesize_audio(
    narration: str,
    voice: str,
    out_dir: Path,
    *,
    model: Optional[str] = None,
) -> tuple[Path, list[WordTiming]]:
    """Synthesize sentence-by-sentence, concatenate, return per-word
    timings whose sentence boundaries are sample-accurate.

    Returns ``(full_audio_path, word_timings)``. Inside each sentence,
    words are distributed proportional to syllable count over the
    measured sentence span — ±50ms typical accuracy which is invisible
    at karaoke pace.

    Sentences synthesize in parallel for latency.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    sentences_with_tags = _split_sentences_with_tags(narration)
    if not sentences_with_tags:
        path, _ = await synthesize_audio_single(narration, voice, out_dir, model=model)
        return path, []

    sent_dir = out_dir / "sentences"
    sent_dir.mkdir(parents=True, exist_ok=True)

    async def _synth_one(idx: int, sent_with_tags: str) -> tuple[Path, float]:
        sub_dir = sent_dir / f"s{idx:02d}"
        sub_dir.mkdir(parents=True, exist_ok=True)
        tmp_path, _ = await synthesize_audio_single(
            narration=sent_with_tags,
            voice=voice,
            out_dir=sub_dir,
            model=model,
        )
        raw_path = sent_dir / f"sentence-{idx:02d}-raw.wav"
        tmp_path.rename(raw_path)
        final_path = sent_dir / f"sentence-{idx:02d}.wav"
        await _atempo_speed_up(raw_path, final_path, _AUDIO_SPEED_FACTOR)
        dur = _probe_duration(final_path)
        return final_path, dur

    results = await asyncio.gather(
        *(_synth_one(i, sent) for i, sent in enumerate(sentences_with_tags))
    )
    sent_paths = [r[0] for r in results]
    sent_durations = [r[1] for r in results]

    full_path = out_dir / "full.wav"
    _concat_wavs_native(sent_paths, full_path)

    word_timings: list[WordTiming] = []
    cursor = 0.0
    for sent_with_tags, sent_dur in zip(
        sentences_with_tags, sent_durations, strict=True
    ):
        sent_start = cursor
        sent_end = cursor + sent_dur

        spoken_words = strip_tts_tags(sent_with_tags).split()
        if not spoken_words:
            cursor = sent_end
            continue

        weights = [_syllables(w) for w in spoken_words]
        total_w = sum(weights)
        w_cursor = sent_start
        for w, wt in zip(spoken_words, weights, strict=True):
            dur = sent_dur * wt / total_w
            word_timings.append(
                WordTiming(word=w, start_s=w_cursor, end_s=w_cursor + dur)
            )
            w_cursor += dur
        cursor = sent_end

    return full_path, word_timings


__all__ = [
    "DEFAULT_TTS_MODEL",
    "strip_tts_tags",
    "synthesize_audio",
    "synthesize_audio_single",
    "voice_for_tone",
]
