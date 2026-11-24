# AbleWarp

AbleWarp prepares a folder of full songs for Ableton Live. It estimates the tempo and beat grid locally, preserves the original audio and intro, and makes a review Set per song. Live writes reusable `.asd` sidecars in one batch operation. AbleWarp checks the saved warp markers against the intended grid and flags tracks that need an ear check.

This is an experimental tool built by Vince Romanelli for live performance prep. The pilot used macOS on Apple silicon and Ableton Live 12.4.16.

## Try it

1. Clone this repo and follow the [local runtime setup](.agents/skills/ablewarp/references/runtime.md).
2. In a Codex chat with this repo open, type `$ablewarp ~/Downloads/New Songs`. Use `$ablewarp` by itself to supply the folder on the next turn.
3. Open an individual review Set to audition at the recording's measured tempo. The Arrangement starts with an empty bar. Turn on the metronome to hear the four clicks.

### Run the batch yourself

From this repo's root, choose an input folder and a **new** output folder:

```sh
warp_python="$HOME/Library/Caches/ablewarp/venv/bin/python"
warp_script=".agents/skills/ablewarp/scripts/warp.py"
"$warp_python" "$warp_script" prepare "/path/to/songs" "/path/to/songs - Warped"
```

In Ableton, open `Warped Tracks - Batch ASD.als` inside the output folder. Focus the Arrangement, select all clips, wait for their waveforms to finish analyzing, and click **Save Default Clip** in Clip View. Use the individual Sets for playback at the measured tempo. Then verify:

```sh
"$warp_python" "$warp_script" verify "/path/to/songs - Warped"
```

Keep each copied audio file next to its `.asd`. The resulting `Warp timing review.csv` indicates grid and sidecar checks.

## Pilot results

- Ableton wrote 27 sidecars and all 27 matched the prepared warp maps. Eleven tracks were flagged for timing review, mostly for uncertainty about the first beat of the bar.
- In a separate creator-mode test, we imported and warped a fresh song in an unlaunched Session slot while an Arrangement track played. Live's transport kept advancing, and a fresh import restored all 89 saved warp markers. That test used Live's controls.
- Beat detection uses [Beat This!](https://github.com/CPJKU/beat_this). The repo includes a blank Live Set template. Supply your own music.
