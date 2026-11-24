import copy
import gzip
import hashlib
import math
from pathlib import Path
import shutil
from xml.etree import ElementTree as ET

from batch_warp import TEMPLATE, set_value, write_staging_set

def read(path):
    with gzip.open(path, "rb") as handle:
        return ET.parse(handle)

def write(path, tree):
    with gzip.open(path, "wb") as handle:
        tree.write(handle, encoding="utf-8", xml_declaration=True)

def place(clip, position, length):
    clip.set("Time", str(position))
    set_value(clip, "CurrentStart", position)
    set_value(clip, "CurrentEnd", position + length)

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def build(output, plans):
    output.mkdir()
    (output / "Ableton Project Info").mkdir()
    assembly = read(TEMPLATE)
    assembly_song = assembly.getroot().find("LiveSet")
    assembly_track = assembly_song.find("Tracks/AudioTrack")
    event_list = next(parent for parent in assembly_track.iter() if parent.find("AudioClip") is not None)
    event_list.remove(event_list.find("AudioClip"))
    set_value(assembly_track, "Name/EffectiveName", "Warped copies")
    set_value(assembly_track, "Name/UserName", "Warped copies")
    set_value(assembly_song, "Transport/CurrentTime", 0)
    set_value(assembly_song, "SequencerNavigator/BeatTimeHelper/CurrentZoom", .4)
    cursor = 4.
    for number, plan in enumerate(plans):
        source = Path(plan["audio"])
        project = output / source.stem
        (project / "Ableton Project Info").mkdir(parents=True)
        audio = project / source.name
        shutil.copyfile(source, audio)
        if sha(source) != sha(audio):
            raise ValueError(f"Copied audio differs from the source: {audio}")
        stage = write_staging_set(audio, plan["duration"], 0, plan["bpm"])
        tree = read(stage)
        song = tree.getroot().find("LiveSet")
        clip = next(song.iter("AudioClip"))
        markers = clip.find("WarpMarkers")
        markers.clear()
        start_b = plan["start_beat"]
        end_b = plan["anchors"][-1][1]
        length = end_b - start_b
        for index, (seconds, beat) in enumerate(plan["anchors"]):
            ET.SubElement(markers, "WarpMarker", Id=str(index + 1),
                          SecTime=str(seconds), BeatTime=str(beat))
        for key, value in {
            "LoopStart": start_b, "LoopEnd": end_b, "StartRelative": 0, "OutMarker": end_b,
            "HiddenLoopStart": start_b, "HiddenLoopEnd": end_b,
        }.items():
            set_value(clip, "Loop/" + key, value)
        set_value(clip, "ScrollerTimePreserver/RightTime", min(end_b, start_b + 32))
        set_value(clip, "ScrollerTimePreserver/LeftTime", 0)
        place(clip, 4 + start_b, length)
        set_value(song, "Transport/CurrentTime", 0)
        set_value(song, "SequencerNavigator/BeatTimeHelper/CurrentZoom", .02634)
        for ts in song.iter("TimeSelection"):
            set_value(ts, "AnchorTime", 0)
            set_value(ts, "OtherTime", 0)
        write(stage, tree)
        batch_clip = copy.deepcopy(clip)
        batch_clip.set("Id", str(number))
        set_value(batch_clip, "SampleRef/FileRef/RelativePath", str(audio.relative_to(output)))
        place(batch_clip, cursor + start_b, length)
        event_list.append(batch_clip)
        cursor = math.ceil((cursor + end_b) / 4) * 4 + 4
    write(output / "Warped Tracks - Batch ASD.als", assembly)
