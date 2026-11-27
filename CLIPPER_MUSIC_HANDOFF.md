# Clipper handoff: background music, vocal removal, and the gameplay crop

For the session that has `clipper_app.py` on the Clipper PC. A cloud session
built the pieces below but could not see or edit the Clipper itself.

## What I want

1. Pick a free-to-use song inside the Clipper and have it play quietly under
   my GTA clips, with the vocals removed if I tick a box.
2. The credit line for the song added to the clip's caption automatically.
3. The gameplay screen in the vertical layout made slightly smaller. Right
   now its left and right edges are cut off.

## Get the files

Repo `KoolKatt98/PLUM` (public), branch `claude/epic-einstein-2i7q6w`:

```
git clone --branch claude/epic-einstein-2i7q6w --depth 1 https://github.com/KoolKatt98/PLUM.git plum_music
```

Or download the two files directly:

- https://raw.githubusercontent.com/KoolKatt98/PLUM/claude/epic-einstein-2i7q6w/clipper_music/clipper_music.py
- https://raw.githubusercontent.com/KoolKatt98/PLUM/claude/epic-einstein-2i7q6w/clipper_music/INTEGRATION.md

| File | What it is |
|---|---|
| `clipper_music/clipper_music.py` | The module. Standard library only; shells out to `yt-dlp`, `audio-separator`, `ffmpeg`, `ffprobe`. |
| `clipper_music/INTEGRATION.md` | Step-by-step wiring, code snippets, verify checklist, and the crop fix. **Follow this.** |

## Do this, in order

1. Back up: `copy clipper_app.py clipper_app.py.pre_music_bak`.
2. Install into the portable Python:
   `portable\python\python.exe -m pip install yt-dlp "audio-separator[cpu]" audioread`
   (use `"audio-separator[gpu]"` if the PC has an NVIDIA card).
3. Copy `clipper_music.py` next to `clipper_app.py`.
4. Run the smoke test from INTEGRATION.md **before** editing the app:
   `find`, then `get <url> --instrumental`, then `mix`.
5. If `get` refuses every track, the `channel_id` values in `SOURCES` are
   wrong. Fix them as described under "Not tested" in INTEGRATION.md.
6. Wire the Music box, the mix step after the clip is rendered, and the
   credit line in the caption (sections "UI", "Clip step", "Caption").
7. Apply the gameplay crop fix (last section of INTEGRATION.md).
8. Run the Verify checklist, then `Desktop\_restart_clipper.bat`.

## What is and is not proven

Worked in the cloud container (Linux): mixing with ducking, looping and
fade-out; vocal removal end to end on a test tone; the check that refuses
anything not from a cleared source.

Never run: search and download against real YouTube (blocked there), and
everything on Windows. Treat step 4 as the real first test.

## Rules to keep

- A music failure must never lose a clip. Mix to a temp file, swap it in
  only on success, and fall back to the clip without music.
- Run find, download, vocal removal and mix on worker threads and report
  through `put("status", ...)`. Vocal removal takes a minute or two on CPU.
- Do not add a way to download songs from outside the cleared sources.
  Removing the vocals from a commercial song does not stop a copyright
  claim, and avoiding claims is the whole point.
- NCS and Audio Library tracks need the credit line in the caption. Keep it
  out of the 5-hashtag cap.

## Gameplay crop, in one line

The gameplay panel is about 1.62:1 but the game is 16:9, so roughly 9% of
the width is cropped. Scale the gameplay to the full 1080 width
(`scale=1080:-2`, giving 1080x608) and take the extra height from the
facecam panel, instead of scale-to-fill plus crop.

## Still open

- NCS's current terms on monetized videos: read https://ncs.io/usage-policy.
  Secondary sources disagree on whether NCS claims ad revenue.
- The earlier OBS fixes on branch `claude/focused-knuth-ohjpz6`
  (`clipper_fixes/`) are separate from this and may still be waiting.
