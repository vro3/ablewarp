# Local runtime

Use Python 3.12, FFmpeg, ffprobe, and Ableton Live on macOS. The pilot used Live 12.4.16 and an Apple silicon Mac. With FFmpeg installed and on your PATH, run:

```sh
cache="$HOME/Library/Caches/ablewarp"
mkdir -p "$cache"
python3.12 -m venv "$cache/venv"
"$cache/venv/bin/python" -m pip install beat-this==1.1.0 torch==2.8.0 torchaudio==2.8.0
curl --fail --location \
  https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt \
  --output "$cache/final0.ckpt.part" &&
  mv "$cache/final0.ckpt.part" "$cache/final0.ckpt"
```

The model comes from [Beat This!](https://github.com/CPJKU/beat_this). Only the model download needs network access for analysis. Songs stay on your computer.
