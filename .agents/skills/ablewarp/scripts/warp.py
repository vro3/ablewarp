"""Prepare full-track warp maps and check sidecars written by Ableton Live."""
import argparse
import csv
from itertools import groupby
import json
from pathlib import Path
import struct
import subprocess

import numpy as np

from batch_warp import AUDIO_TYPES, WARP_RECORD
from projects import build, read, sha
from timing import plan

CACHE = Path.home() / "Library/Caches/ablewarp"
MANIFEST = "Warp manifest.json"

def prepare(source, output, checkpoint):
    import torch
    from beat_this.inference import Audio2Beats

    if not source.is_dir():
        raise ValueError(f"Input folder does not exist: {source}")
    if output.exists():
        raise ValueError(f"Choose a new output folder: {output}")
    tracks = sorted(path for path in source.iterdir()
                    if path.is_file() and path.suffix.lower() in AUDIO_TYPES)
    if not tracks:
        raise ValueError(f"No supported audio files in {source}")
    if len({path.stem.casefold() for path in tracks}) != len(tracks):
        raise ValueError("Two input files have the same track name. Use unique filename stems.")
    torch.set_num_threads(6)
    model = Audio2Beats(str(checkpoint))
    plans, failures = [], []
    for track in tracks:
        try:
            pcm = subprocess.check_output([
                "ffmpeg", "-nostdin", "-v", "error", "-i", str(track),
                "-map", "0:a:0", "-ac", "1", "-ar", "22050", "-f", "f32le", "-",
            ])
            beats, downbeats = model(np.frombuffer(pcm, dtype="<f4"), 22050)
            result = plan({"source": str(track), "beats": beats, "downbeats": downbeats})
        except (ValueError, RuntimeError, subprocess.CalledProcessError) as err:
            failures.append({"track": track.name, "error": str(err)})
            print(f"Review required: {track.name} — {err}", flush=True)
            continue
        plans.append(result)
        print(f"{track.stem}: {result['bpm']:.2f} BPM, {len(result['anchors'])} markers", flush=True)
    if not plans:
        raise ValueError("No usable warp maps were produced.")
    build(output, plans)
    (output / MANIFEST).write_text(json.dumps({"plans": plans, "failures": failures}, indent=2))
    print(f"{len(plans)} ready for Live; {len(failures)} could not be staged. {output}", flush=True)

def sidecar_matches(data, expected):
    if not data.startswith(b"\x06I"):
        return False
    matches = WARP_RECORD.finditer(data)
    groups = groupby(enumerate(matches), key=lambda item: item[1].start() - 32 * item[0])
    for _, group in groups:
        actual = [struct.unpack("<dd", match[1]) for _, match in group]
        if len(actual) == len(expected) and np.allclose(actual, expected, atol=1e-7, rtol=0):
            return True
    return False

def verify(output):
    manifest = json.loads((output / MANIFEST).read_text())
    rows = []
    verified = 0
    for entry in manifest["plans"]:
        source = Path(entry["audio"])
        audio = output / source.stem / source.name
        project = audio.with_suffix(".als")
        sidecar = audio.with_name(audio.name + ".asd")
        clip = next(read(project).iter("AudioClip"))
        markers = [(float(m.get("SecTime")), float(m.get("BeatTime")))
                   for m in clip.findall("WarpMarkers/WarpMarker")]
        tempo = float(read(project).find("LiveSet/MainTrack/DeviceChain/Mixer/Tempo/Manual").get("Value"))
        if sha(audio) != sha(source) or tempo != entry["bpm"] or float(clip.get("Time")) < 4:
            raise ValueError(f"Unexpected Set or copied audio data: {audio}")
        if len(markers) != len(entry["anchors"]) or not np.allclose(markers, entry["anchors"]):
            raise ValueError(f"Set timing differs from the manifest: {project}")
        status = "Analysis pending"
        if sidecar.exists():
            status = "Verified" if sidecar_matches(sidecar.read_bytes(), markers) else "Warp markers missing or different"
        verified += status == "Verified"
        rows.append([source.stem, tempo, status, "; ".join(entry["flags"]),
                     entry["beat_p90_ms"], entry["attack_median_ms"], entry["stretch_pct"],
                     str(project.relative_to(output))])
    for failure in manifest["failures"]:
        rows.append([failure["track"], "", "Unable to stage", failure["error"], "", "", "", ""])
    rows.sort(key=lambda row: (row[2] == "Verified" and not row[3], row[0].casefold()))
    with (output / "Warp timing review.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Track", "Set BPM", "ASD check", "Timing review", "Model beat error p90 (ms)",
                         "Nearby attack offset median (ms)", "Largest local timing change (%)", "Review Set"])
        writer.writerows(rows)
    print(f"{verified}/{len(manifest['plans'])} sidecars verified. {sum(bool(row[3]) for row in rows)} tracks flagged.")
    return verified != len(manifest["plans"]) or bool(manifest["failures"])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    build_parser = actions.add_parser("prepare")
    build_parser.add_argument("source", type=Path)
    build_parser.add_argument("output", type=Path)
    build_parser.add_argument("--checkpoint", type=Path, default=CACHE / "final0.ckpt")
    actions.add_parser("verify").add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if args.action == "prepare":
        prepare(args.source.expanduser().resolve(), output, args.checkpoint.expanduser())
        return 0
    return verify(output)

if __name__ == "__main__":
    raise SystemExit(main())
