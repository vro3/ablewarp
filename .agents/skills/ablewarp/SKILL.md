---
name: ablewarp
description: Warp full songs from a local folder for Ableton Live, save reusable native ASD sidecars, and verify grid timing. Use when someone invokes ablewarp or asks to warp a folder or batch of songs for Live.
---

# Warp a folder of songs

If the folder came with the invocation, start there. If omitted, ask for its local path or have the user drag the folder into the chat. Resolve an unambiguous name in Downloads when possible. Process supported audio files directly in that folder. Keep the source audio and any existing sidecars intact. Use a new sibling output folder named `<folder> - Warped` unless the user gives a different destination. When an output already exists, use a new numbered folder, or resume its verified matching manifest if the user asks to continue.

## Prepare and check

1. Run `scripts/warp.py prepare INPUT OUTPUT` with `~/Library/Caches/ablewarp/venv/bin/python`. The script uses local audio, FFmpeg, and the locally cached Beat This! checkpoint. If the runtime is missing, follow [the runtime setup](references/runtime.md). djay BPM can corroborate an ambiguous result when available. It is optional.
2. Use the full-source review Sets produced by the script. They use the recording's estimated sustained BPM, sparse anchors for steady tracks, and an empty first bar. A pickup can delay the audio edge beyond bar 2 so its phase survives. Each review Set is cued at 1.1.1 and framed for roughly eight bars. Prefer keeping the source's musical timing when a steady and a more aggressive map both appear plausible. Flag unresolved bar phase, timing drift, and substantial stretch. If a clip has an aligned click stem that the user identifies, use that as the timing reference where useful. Keep click stems out of the mix batch.
3. To save native sidecars, use Computer Use and the generated `Warped Tracks - Batch ASD.als`. Open this one Set in Live when it is safe to switch. Preserve any existing Live work. Focus the Arrangement, select all clips with Cmd+A, and confirm Clip View shows the expected number of clips. Click **Save Default Clip** in the Clip View header. This saves the selected clips' defaults to the copied audio files' ASD sidecars. The batch Set is for writing sidecars. Use each song's own Set to audition at its measured BPM.
4. Opening fresh files can take several seconds per waveform. If Live says the sample analysis is incomplete, dismiss the message, let analysis progress, and retry **Save Default Clip** when the last waveform is ready. A sidecar's existence alone may indicate waveform analysis only. Run `scripts/warp.py verify OUTPUT` to compare every native marker with its intended coordinates and generate the timing CSV. Where practical, spot-check a fresh import with Warp enabled and the markers restored. Distinguish this from file verification.
5. Link the output folder and timing CSV. Report how many sidecars verified, which tracks need timing attention, and any failure. Leave the review Sets available without opening them individually unless requested. For an audition, open the song's own Set with transport stopped and cued. The empty bar produces clicks when Live's metronome is on.

## While Live is playing

Folder analysis and Set preparation can run separately while the user works. If they want same-session help, keep their playback and working Set in place. Obtain the intended staging location before editing their Set. An unlaunched Session clip can be analyzed, warped and saved while Arrangement playback continues. This was demonstrated in a test Set using **Set 1.1.1 Here**, **Warp From Here**, and **Save Default Clip** after sample analysis. Use the native workflow when requested. Audible pickups must be included in the finished review Set. If Live's UI is occupied, finish offline prep and report whether native ASD export is still pending.
