# /// script
# requires-python = ">=3.12"
# ///
"""Stage the reel's inputs under public/showreel/ from the captures, the brand files and the audio.

Run from video/ after `npm run capture` has written tmp/captures/:

    uv run showreel/prepare.py --audio ../../tmp/showreel/audio

Captures are copied unchanged. The score is ElevenLabs take 4, cut to start 3.762 s in (two bars of
its intro) and kept as WAV; three effects are the Mluva showreel's takes, reused.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CAPTURES = ROOT / "tmp/captures"
OUT = ROOT / "public/showreel"
TAKES = ["welcome", "atlas", "kastovsky", "hlavacek", "versus", "results", "phone"]
BRAND = ["lockup.svg"]
IMG = ["bg-topo.svg", "bg-grid.svg"]
SCORE = ("score-4.mp3", 3.762)
SFX = {
    "impact": "massive-cinematic-sub-bass_k2oyp.mp3",
    "impact-long": "massive-cinematic-sub-bass_VRBuW.mp3",
    "whoosh-soft": "fast-airy-whoosh_hk3nd.mp3",
}


def main() -> None:
    """Copy captures, brand files and audio into public/showreel and record their hashes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True, help="Folder with score-4.mp3 and sfx/")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for take in TAKES:
        shutil.rmtree(OUT / take, ignore_errors=True)
        shutil.copytree(CAPTURES / take, OUT / take)
    (OUT / "brand").mkdir(exist_ok=True)
    for name in BRAND:
        shutil.copy2(REPO / "app/web/brand" / name, OUT / "brand" / name)
    (OUT / "img").mkdir(exist_ok=True)
    for name in IMG:
        shutil.copy2(REPO / "app/web/img" / name, OUT / "img" / name)
    audio = OUT / "audio"
    audio.mkdir(exist_ok=True)
    name, start = SCORE
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(args.audio / name), "-t", "46",
         "-ar", "48000", "-c:a", "pcm_s24le", str(audio / "score.wav")],
        check=True,
    )  # fmt: skip
    for key, file in SFX.items():
        shutil.copy2(args.audio / "sfx" / file, audio / f"{key}.mp3")
    manifest = {
        str(path.relative_to(OUT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "media.json"
    }
    (OUT / "media.json").write_text(json.dumps(manifest, indent=2))
    print(f"Staged {len(manifest)} files in {OUT}")


if __name__ == "__main__":
    main()
