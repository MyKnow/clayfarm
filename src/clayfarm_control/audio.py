"""Audio contracts and deterministic post-processing for local text-to-audio jobs.

The module deliberately uses only the Python standard library.  Model adapters
produce a WAV file, then this module creates the Unity master plus review
artifacts.  It never decides that an audio asset is artist-approved.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from .common import CFError, atomic_json

BGM_PROFILES = {"sa3-small-music-cpu", "sa3-small-music-cuda", "sa3-small-music-mlx"}
SFX_PROFILES = {"sa3-small-cpu", "sa3-small-cuda", "sa3-small-mlx"}
AUDIO_PROFILES = BGM_PROFILES | SFX_PROFILES
TRACK_IDS = {"lobby", "preparation", "combat", "result"}
_BGM_FIELDS = {"track_id", "prompt", "duration_seconds", "bpm", "loop_required", "seed", "negative_prompt"}
_SFX_FIELDS = {"event_id", "prompt", "duration_seconds", "variation_count", "seed", "negative_prompt"}


def _number(value, low, high, name, *, integer=False):
    if integer:
        valid = isinstance(value, int) and not isinstance(value, bool)
    else:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if not valid or not low <= value <= high:
        raise CFError("invalid_spec", f"{name} is outside limits")
    return value


def _prompt(value, name="prompt"):
    if not isinstance(value, str) or not 1 <= len(value) <= 2000:
        raise CFError("invalid_spec", f"Provide {name} with 1..2000 characters")


def validate_audio_spec(profile: str, spec: dict) -> dict:
    """Validate the public BGM/SFX request without accepting model settings."""
    if not isinstance(spec, dict):
        raise CFError("invalid_spec", "An object is required")
    if profile in BGM_PROFILES:
        if set(spec) - _BGM_FIELDS:
            raise CFError("invalid_spec", "Unknown BGM field")
        track = spec.get("track_id")
        if track not in TRACK_IDS:
            raise CFError("invalid_spec", "track_id must be lobby, preparation, combat, or result")
        _prompt(spec.get("prompt"))
        duration_low = 0.25 if track == "result" else 1
        _number(spec.get("duration_seconds", 30), duration_low, 120, "duration_seconds")
        if "bpm" in spec:
            _number(spec["bpm"], 30, 240, "bpm")
        if not isinstance(spec.get("loop_required", False), bool):
            raise CFError("invalid_spec", "loop_required must be boolean")
        _number(spec.get("seed", 0), 0, 2**32 - 1, "seed", integer=True)
        if "negative_prompt" in spec:
            _prompt(spec["negative_prompt"], "negative_prompt")
        return spec
    if profile in SFX_PROFILES:
        if set(spec) - _SFX_FIELDS:
            raise CFError("invalid_spec", "Unknown SFX field")
        event = spec.get("event_id")
        if not isinstance(event, str) or not 1 <= len(event) <= 120:
            raise CFError("invalid_spec", "event_id must be 1..120 characters")
        _prompt(spec.get("prompt"))
        _number(spec.get("duration_seconds", 1), 0.05, 12, "duration_seconds")
        _number(spec.get("variation_count", 1), 1, 8, "variation_count", integer=True)
        _number(spec.get("seed", 0), 0, 2**32 - 1, "seed", integer=True)
        if "negative_prompt" in spec:
            _prompt(spec["negative_prompt"], "negative_prompt")
        return spec
    raise CFError("adapter_not_implemented", "No executable audio profile")


def _chunks(raw: bytes):
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise CFError("audio_format", "WAV RIFF header missing")
    pos = 12
    while pos + 8 <= len(raw):
        tag = raw[pos : pos + 4]
        size = struct.unpack_from("<I", raw, pos + 4)[0]
        start, end = pos + 8, pos + 8 + size
        if end > len(raw):
            raise CFError("audio_format", "WAV chunk exceeds file")
        yield tag, raw[start:end]
        pos = end + (size & 1)


def _decode_wav(path: Path):
    raw = path.read_bytes()
    fmt = data = None
    for tag, value in _chunks(raw):
        if tag == b"fmt ":
            fmt = value
        elif tag == b"data":
            data = value
    if not fmt or data is None or len(fmt) < 16:
        raise CFError("audio_format", "WAV fmt/data chunks are required")
    audio_format, channels, rate, _, block_align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if audio_format == 0xFFFE and len(fmt) >= 40:
        # WAVE_FORMAT_EXTENSIBLE: the first DWORD of the subtype GUID is the
        # original PCM (1) or IEEE float (3) format.
        audio_format = struct.unpack_from("<I", fmt, 24)[0]
    if channels not in (1, 2) or not 8000 <= rate <= 192000:
        raise CFError("audio_format", "Audio must be mono/stereo at 8..192kHz")
    if audio_format not in (1, 3) or bits not in (16, 24, 32) or (audio_format == 3 and bits != 32):
        raise CFError("audio_format", "Only PCM 16/24/32-bit or IEEE float32 WAV is supported")
    width = bits // 8
    if block_align != channels * width or len(data) % block_align:
        raise CFError("audio_format", "Invalid WAV frame alignment")
    frames = []
    for offset in range(0, len(data), block_align):
        frame = []
        for c in range(channels):
            chunk = data[offset + c * width : offset + (c + 1) * width]
            if audio_format == 3:
                value = struct.unpack("<f", chunk)[0]
                if not math.isfinite(value):
                    raise CFError("audio_format", "WAV contains a non-finite sample")
            elif bits == 16:
                value = struct.unpack("<h", chunk)[0] / 32768.0
            elif bits == 24:
                integer = int.from_bytes(chunk, "little", signed=True)
                value = integer / 8388608.0
            else:
                value = struct.unpack("<i", chunk)[0] / 2147483648.0
            frame.append(value)
        frames.append(frame)
    return rate, channels, frames


def _db(value):
    return -120.0 if value <= 1e-12 else 20.0 * math.log10(value)


def _write_pcm(path: Path, rate: int, channels: int, frames: list[list[float]]):
    payload = bytearray()
    for frame in frames:
        for value in frame:
            payload += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(payload)


def _waveform(path: Path, values: list[float]):
    count = min(512, max(32, int(math.sqrt(max(1, len(values))))))
    step = max(1, len(values) // count)
    points = []
    for start in range(0, len(values), step):
        segment = values[start : start + step]
        points.append(round(max(segment, key=abs), 6) if segment else 0.0)
    atomic_json(path, {"schema_version": 1, "points": points[:count], "encoding": "peak-per-window"})


def _spectrogram(path: Path, values: list[float]):
    # A small review preview, intentionally not a mastering or perceptual QA
    # score.  Downsample each window and calculate 16 deterministic bands.
    columns, bands = 64, 16
    window = max(32, len(values) // columns)
    matrix = []
    for col in range(columns):
        segment = values[col * window : (col + 1) * window]
        if not segment:
            segment = [0.0]
        row = []
        for band in range(bands):
            total = 0.0
            for i, sample in enumerate(segment):
                angle = math.pi * (band + 1) * (i + 0.5) / len(segment)
                total += sample * math.sin(angle)
            row.append(min(1.0, abs(total) / max(1.0, len(segment) * 0.15)))
        matrix.append(row)
    cells = []
    for x, row in enumerate(matrix):
        for y, value in enumerate(row):
            shade = int(255 * (1 - value))
            cells.append(f'<rect x="{x}" y="{bands - y - 1}" width="1" height="1" fill="rgb({shade},{shade},{255})"/>')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="16" viewBox="0 0 64 16">' + "".join(cells) + "</svg>"
    path.write_text(svg, encoding="utf-8")


def normalize_wav(source: Path, out: Path, *, loop_required: bool = False) -> dict:
    """Trim, peak-normalize and report a model WAV into Unity's PCM master."""
    rate, channels, original = _decode_wav(Path(source))
    if not original:
        raise CFError("audio_empty", "WAV contains no frames")
    mono = [sum(frame) / channels for frame in original]
    input_clipping = sum(1 for frame in original for value in frame if abs(value) >= 1.0)
    threshold = 10 ** (-60 / 20)
    first = next((i for i, value in enumerate(mono) if abs(value) >= threshold), 0)
    last = len(mono) - 1 - next((i for i, value in enumerate(reversed(mono)) if abs(value) >= threshold), 0)
    frames = original[first : last + 1] or [[0.0] * channels]
    peak = max(abs(value) for frame in frames for value in frame)
    scale = (10 ** (-1 / 20)) / peak if peak else 1.0
    normalized = [[max(-1.0, min(1.0, value * scale)) for value in frame] for frame in frames]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    artifact = out / "asset.wav"
    _write_pcm(artifact, rate, channels, normalized)
    flat = [sum(frame) / channels for frame in normalized]
    final_peak = max(abs(value) for value in flat) if flat else 0.0
    rms = math.sqrt(sum(value * value for value in flat) / max(1, len(flat)))
    clipping = sum(1 for frame in normalized for value in frame if abs(value) >= 0.999)
    seam = math.sqrt(sum((normalized[0][c] - normalized[-1][c]) ** 2 for c in range(channels)) / channels)
    report = {
        "schema_version": 1,
        "sample_rate": rate,
        "channels": channels,
        "duration_seconds": round(len(normalized) / rate, 6),
        "trimmed_leading_frames": first,
        "trimmed_trailing_frames": len(original) - last - 1,
        "peak_dbfs": round(_db(final_peak), 3),
        "rms_dbfs": round(_db(rms), 3),
        "input_clipping_samples": input_clipping,
        "clipping_samples": clipping,
        "loop_required": loop_required,
        "loop_seam_rms": round(seam, 6),
        "loop_seam_review_required": bool(loop_required and seam > 0.08),
        "master_format": "PCM_S16LE_WAV",
    }
    _waveform(out / "waveform.json", flat)
    _spectrogram(out / "spectrogram.svg", flat)
    atomic_json(out / "audio-report.json", report)
    return artifact, report
