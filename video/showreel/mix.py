# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
# ///
"""Mix the score and sound effects from src/showreel/cues.json, master to -14 LUFS, and mux the picture.

    uv run showreel/mix.py out/starwatch-showreel.mp4

Each cue's frame marks where the effect's peak lands; `sfx_peaks_s` holds that offset per effect.
Loudness uses FFmpeg's two-pass EBU R128 loudnorm with a -1.5 dBTP ceiling, then a small trim if the
linear pass lands more than 0.2 LU from the target.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "public/showreel/audio"
RATE = 48000
TARGET = {"I": -14.0, "TP": -1.5, "LRA": 11.0}
LOUDNORM = f"loudnorm=I={TARGET['I']}:TP={TARGET['TP']}:LRA={TARGET['LRA']}"


def decode(path: Path) -> np.ndarray:
    """Decode an audio file to 48 kHz stereo float samples."""
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(RATE), "-"]
    raw = subprocess.run(command, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def measure(path: Path) -> dict:
    """Return FFmpeg loudnorm's measurement of a file."""
    command = ["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"{LOUDNORM}:print_format=json", "-f", "null", "-"]
    stderr = subprocess.run(command, check=True, capture_output=True, text=True).stderr
    start = stderr.rindex("{")
    return json.loads(stderr[start : stderr.index("}", start) + 1])


def ffmpeg(*arguments: str) -> None:
    """Run FFmpeg quietly, overwriting outputs."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)


def main() -> None:
    """Build the mix, master it and attach it to the silent render."""
    video = Path(sys.argv[1]).resolve()
    plan = json.loads((ROOT / "src/showreel/cues.json").read_text())
    fps, frames = plan["fps"], plan["duration_frames"]
    length = round(frames / fps * RATE)
    mix = np.zeros((length, 2), dtype=np.float64)

    score = decode(AUDIO / plan["score"]["file"])[:length] * 10 ** (plan["score"]["gain_db"] / 20)
    fade_from = round(plan["score"]["fade_out_from_frame"] / fps * RATE)
    fade = np.ones(len(score))
    fade[fade_from:] = np.cos(np.linspace(0, np.pi / 2, len(score) - fade_from)) ** 2
    mix[: len(score)] += score * fade[:, None]

    cache: dict[str, np.ndarray] = {}
    for cue in plan["cues"]:
        name = cue["sfx"]
        clip = cache.setdefault(name, decode(AUDIO / f"{name}.mp3"))
        start = round((cue["frame"] / fps - plan["sfx_peaks_s"][name]) * RATE)
        gain = 10 ** (cue["gain_db"] / 20)
        a, b = max(0, start), min(length, start + len(clip))
        if b > a:
            mix[a:b] += clip[a - start : b - start] * gain

    stem = video.with_suffix("")
    raw_wav = stem.parent / f"{stem.name}-mix-raw.wav"
    master_wav = stem.parent / f"{stem.name}-mix.wav"
    peak = np.abs(mix).max()
    if peak > 0.98:
        mix *= 0.98 / peak
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(RATE), "-ac", "2", "-i", "-", str(raw_wav)],
        input=pcm.tobytes(),
        check=True,
    )

    measured = measure(raw_wav)
    second = (
        f"{LOUDNORM}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true"
    )
    ffmpeg("-i", str(raw_wav), "-af", second, "-ar", str(RATE), "-c:a", "pcm_s24le", str(master_wav))
    trim = TARGET["I"] - float(measure(master_wav)["input_i"])
    if abs(trim) > 0.2:
        trimmed = stem.parent / f"{stem.name}-mix-trim.wav"
        ceiling = 10 ** (TARGET["TP"] / 20)
        ffmpeg("-i", str(master_wav), "-af", f"volume={trim:.2f}dB,alimiter=limit={ceiling:.4f}:level=false",
               "-ar", str(RATE), "-c:a", "pcm_s24le", str(trimmed))  # fmt: skip
        trimmed.replace(master_wav)

    final = stem.parent / f"{stem.name}-master.mp4"
    ffmpeg(
        "-i", str(video), "-i", str(master_wav),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
        "-t", f"{frames / fps:.3f}", "-movflags", "+faststart", str(final),
    )  # fmt: skip
    result = measure(final)
    print(f"{final.name}: {result['input_i']} LUFS, {result['input_tp']} dBTP, LRA {result['input_lra']}")


if __name__ == "__main__":
    main()
