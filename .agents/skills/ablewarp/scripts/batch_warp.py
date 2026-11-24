"""Prepare scratch Ableton Sets and independently check native ASD timing."""
import argparse
import gzip
import json
from itertools import groupby
import math
import re
import shutil
import struct
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

AUDIO_TYPES = {".aif", ".aiff", ".flac", ".m4a", ".mp3", ".wav"}
RATE = 12000
HOP = 60
FRAME = 360
STEP = HOP / RATE
TEMPLATE = Path(__file__).with_name("template.als")
WARP_RECORD = re.compile(rb"\x0aWarpMarker.{4}(.{16})", re.DOTALL)


def audio_features(path):
    data = subprocess.check_output([
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"
    ])
    samples = np.frombuffer(data, dtype="<f4")
    if len(samples) < RATE * 8:
        raise ValueError("At least eight seconds of audio are required.")
    frames = np.lib.stride_tricks.sliding_window_view(samples, FRAME)[::HOP]
    window = np.hanning(FRAME)
    previous = None
    bands = []
    for begin in range(0, len(frames), 1024):
        spectrum = np.log1p(8 * np.abs(np.fft.rfft(frames[begin:begin + 1024] * window)))
        change = np.maximum(0, np.diff(spectrum, axis=0, prepend=spectrum[:1] if previous is None else previous))
        bands.append([change[:, a:b].mean(axis=1) for a, b in ((1, 6), (6, 32), (32, 150))])
        previous = spectrum[-1:]
    bands = np.concatenate(bands, axis=1)
    bands /= np.maximum(np.quantile(bands, 0.9, axis=1)[:, None], 1e-6)
    return len(samples) / RATE, np.minimum(bands, 6).mean(axis=0)


def estimate_tempo(attacks):
    nfft = max(1 << 20, 1 << (len(attacks) - 1).bit_length())
    spectrum = np.abs(np.fft.rfft(attacks - attacks.mean(), nfft))
    bpms = np.arange(65, 201, 0.01)
    frequencies = bpms * nfft * STEP / 60
    harmonics = [np.interp(frequencies * k, np.arange(len(spectrum)), spectrum) for k in range(1, 5)]
    first, second, third, fourth = harmonics
    score = np.sqrt((first + 0.01) * (first + second + 0.5 * (third + fourth)))
    best = score.max()
    if best <= 0.01:
        raise ValueError("No usable rhythmic pulse was detected.")
    candidates = []
    for _ in range(3):
        i = int(score.argmax())
        candidates.append({"bpm": round(float(bpms[i]), 2), "strength": round(float(score[i] / best), 2)})
        score[np.abs(bpms - bpms[i]) < 1] = 0
    return candidates


def onset_candidates(attacks, bpm):
    period = 60 / bpm
    times = np.arange(len(attacks)) * STEP + FRAME / (2 * RATE)
    count = round(period / STEP)
    bins = np.floor((times % period) / period * count).astype(int)
    density = np.bincount(bins, weights=attacks, minlength=count) / np.maximum(np.bincount(bins, minlength=count), 1)
    smoothed = sum(weight * np.roll(density, shift) for shift, weight in zip(range(-2, 3), (1, 2, 3, 2, 1)))
    phase = (int(smoothed.argmax()) + 0.5) * period / count
    peaks = []
    for beat in np.arange(phase, min(18, times[-5]), period):
        nearby = np.flatnonzero(np.abs(times[:4000] - beat) < 0.045)
        if nearby.size:
            index = nearby[int(attacks[nearby].argmax())]
            if attacks[index] >= 0.7:
                peaks.append(round(float(times[index]), 3))
    return peaks


def set_value(parent, path, value):
    parent.find(path).set("Value", str(value))


def write_staging_set(audio, duration, downbeat, bpm):
    with gzip.open(TEMPLATE, "rb") as handle:
        tree = ET.parse(handle)
    song = tree.getroot().find("LiveSet")
    track = song.find("Tracks/AudioTrack")
    clip = next(track.iter("AudioClip"))
    tempo = song.find("MainTrack/DeviceChain/Mixer/Tempo")
    set_value(tempo, "Manual", bpm)
    tempo_target = tempo.find("AutomationTarget").get("Id")
    for envelope in song.findall("MainTrack//AutomationEnvelope"):
        target = envelope.find("EnvelopeTarget/PointeeId")
        if target is not None and target.get("Value") == tempo_target:
            for event in envelope.findall("Automation/Events/FloatEvent"):
                event.set("Value", str(bpm))

    tail = (duration - downbeat) * bpm / 60
    set_value(track, "Name/EffectiveName", audio.stem)
    set_value(track, "Name/UserName", audio.stem)
    set_value(clip, "Name", audio.stem)
    set_value(clip, "CurrentEnd", tail)
    for key in ("LoopEnd", "OutMarker", "HiddenLoopEnd"):
        set_value(clip, "Loop/" + key, tail)
    set_value(clip, "Loop/HiddenLoopStart", -downbeat * bpm / 60)
    set_value(clip, "ScrollerTimePreserver/RightTime", tail)

    metadata = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
        "stream=sample_rate", "-of", "json", str(audio)
    ]))
    sample_rate = int(metadata["streams"][0]["sample_rate"])
    reference = clip.find("SampleRef")
    for key, value in {
        "FileRef/RelativePathType": 1, "FileRef/RelativePath": audio.name,
        "FileRef/Path": audio, "FileRef/OriginalFileSize": audio.stat().st_size,
        "FileRef/OriginalCrc": 0, "LastModDate": int(audio.stat().st_mtime),
        "DefaultDuration": round(duration * sample_rate), "DefaultSampleRate": sample_rate,
    }.items():
        set_value(reference, key, value)
    markers = clip.find("WarpMarkers")
    for index, beat in enumerate((0, 0.03125)):
        ET.SubElement(markers, "WarpMarker", Id=str(index),
                      SecTime=str(downbeat + beat * 60 / bpm), BeatTime=str(beat))

    destination = audio.with_suffix(".als")
    with gzip.open(destination, "xb") as handle:
        tree.write(handle, encoding="utf-8", xml_declaration=True)
    return destination


def plan_files(paths):
    for path in paths:
        _, attacks = audio_features(path)
        tempo = estimate_tempo(attacks)
        print(json.dumps({"audio": str(path), "tempo_candidates": tempo,
                          "opening_beat_candidates": onset_candidates(attacks, tempo[0]["bpm"])}))


def prepare_files(folder, output, entries):
    jobs = []
    for entry in entries:
        name, anchor, bpm = entry.rsplit("=", 2)
        path = folder / name
        if path.parent != folder or path.suffix.lower() not in AUDIO_TYPES or not path.is_file():
            raise ValueError(f"Choose an audio filename from the input folder: {name}")
        downbeat, tempo = float(anchor), float(bpm)
        duration, _ = audio_features(path)
        if not math.isfinite(downbeat) or not 0 <= downbeat < duration - 4 or not 40 <= tempo <= 240:
            raise ValueError(f"Invalid downbeat or BPM for {name}")
        jobs.append((path, duration, downbeat, tempo))
    if len({path.stem.casefold() for path, *_ in jobs}) != len(jobs):
        raise ValueError("Track stems must be unique within a batch.")
    output.mkdir(parents=True, exist_ok=False)
    for source, duration, downbeat, tempo in jobs:
        folder = output / source.stem
        (folder / "Ableton Project Info").mkdir(parents=True)
        audio = folder / source.name
        shutil.copyfile(source, audio)
        stage = write_staging_set(audio, duration, downbeat, tempo)
        print(json.dumps({"name": audio.stem, "audio": str(audio), "stage": str(stage),
                          "bar_one_seconds": downbeat, "initial_bpm": tempo}))


def map_positions(seconds, beats, values):
    values = np.asarray(values)
    segments = np.clip(np.searchsorted(beats, values, side="right") - 1, 0, len(beats) - 2)
    start, stop = segments, segments + 1
    fraction = (values - beats[start]) / (beats[stop] - beats[start])
    return seconds[start] + fraction * (seconds[stop] - seconds[start])


def verify_file(audio):
    sidecar = audio.with_name(audio.name + ".asd")
    data = sidecar.read_bytes()
    if not data.startswith(b"\x06I"):
        raise ValueError("Unrecognized Live ASD header.")
    records = list(WARP_RECORD.finditer(data))
    groups = groupby(enumerate(records), key=lambda item: item[1].start() - 32 * item[0])
    longest = max(([match for _, match in group] for _, group in groups), key=len, default=[])
    markers = np.array([struct.unpack("<dd", match[1]) for match in longest])
    if len(markers) < 4 or not np.isfinite(markers).all() or not (np.diff(markers, axis=0) > 0).all():
        raise ValueError("No usable multi-marker warp map found.")
    seconds, beats = markers.T
    duration, attacks = audio_features(audio)
    if abs(beats[0]) > 0.0001 or abs(seconds[-1] - duration) > 12:
        raise ValueError("Warp map does not start at bar one or cover the end of the audio.")
    clips = []
    for fraction in (0.15, 0.5, 0.85):
        center = int(beats[-1] * fraction)
        expected = map_positions(seconds, beats, np.arange(max(0, center - 16), center + 16))
        errors = []
        for time in expected:
            i = round((time - FRAME / (2 * RATE)) / STEP)
            window = np.arange(max(0, i - 10), min(len(attacks), i + 11))
            if window.size:
                peak = int(window[attacks[window].argmax()])
                if attacks[peak] >= 0.8:
                    errors.append(abs(peak * STEP + FRAME / (2 * RATE) - time) * 1000)
        clips.append({"section": fraction, "attacks": len(errors),
                      "median_ms": round(float(np.median(errors)), 1) if errors else None,
                      "p90_ms": round(float(np.quantile(errors, .9)), 1) if errors else None})
    flag = any(part["attacks"] < 8 or part["median_ms"] > 18 or part["p90_ms"] > 36 for part in clips)
    print(json.dumps({"audio": str(audio), "asd_records": len(markers), "bar_one_seconds": round(seconds[0], 6),
                      "last_visible_beat": float(beats[-2]), "section_checks": clips,
                      "timing_review": flag}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("audio", type=Path, nargs="+")
    prepare = commands.add_parser("prepare")
    prepare.add_argument("folder", type=Path)
    prepare.add_argument("output", type=Path)
    prepare.add_argument("--track", action="append", required=True, metavar="FILENAME=DOWNBEAT_SECONDS=BPM")
    verify = commands.add_parser("verify")
    verify.add_argument("audio", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        if args.action == "plan":
            plan_files([path.resolve() for path in args.audio])
        elif args.action == "prepare":
            prepare_files(args.folder.resolve(), args.output.resolve(), args.track)
        else:
            for path in args.audio:
                verify_file(path.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
