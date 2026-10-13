# /// script
# requires-python = ">=3.12"
# ///
"""Stage the reel's inputs under public/showreel/ from the captures, the brand files and the audio.

Run from video/ after `npm run capture` has written tmp/captures/:

    uv run showreel/prepare.py --audio ../../tmp/showreel/audio

Captures are copied unchanged. The score is ElevenLabs take 4, cut to start 3.762 s in (two bars of
its intro) and kept as WAV; the effects are the Mluva showreel's takes, reused.
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
TAKES = ["atlas", "spotlight", "pulse", "radar", "results", "welcome", "phone"]
BRAND = ["lockup-white.svg", "mark.svg"]
SCORE = ("score-4.mp3", 3.762)
SFX = {
    "impact": "massive-cinematic-sub-bass_k2oyp.mp3",
    "impact-long": "massive-cinematic-sub-bass_VRBuW.mp3",
    "whoosh": "fast-airy-whoosh_8m4uS.mp3",
    "whoosh-soft": "fast-airy-whoosh_hk3nd.mp3",
    "glitch": "short-digital-glitch_KuJyn.mp3",
    "tick": "tiny-soft-ui_A0IpI.mp3",
    "riser": "tense-white-noise-riser_PRkdb.mp3",
    "key": "single-deep-mechanical_qDf6b.mp3",
    "flap": "split-flap-departure-board_qaW6O.mp3",
    "flash": "bright-flash-pop_2eU6P.mp3",
    "jelly": "soft-glossy-jelly_jdBPe.mp3",
    "blips": "rapid-subtle-computer_Ztd92.mp3",
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
