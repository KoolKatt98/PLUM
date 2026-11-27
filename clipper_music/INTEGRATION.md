# Wiring background music into clipper_app.py

Written without seeing `clipper_app.py` (it is not in this repo). Names such as
`Core`, `put` and the caption builder come from CLIPPER_HANDOFF.md and the
earlier `clipper_fixes/INTEGRATION.md`. Adjust them to match the real code.

**First:** `copy clipper_app.py clipper_app.py.pre_music_bak`, then copy
`clipper_music.py` next to it and add `import clipper_music` at the top.

## What was and was not tested

Tested in the cloud container (Linux, Python 3.13, ffmpeg):

- `add_local`, the library file, `credit`
- `mix`: video stream copied, song looped to the clip length, fade-out,
  ducking, clip with no audio track, `--start`
- `make_instrumental`: ran end to end with `audio-separator` 0.48 on CPU
  (model download, separation, result stored on the track). The input was a
  synthetic tone, so how clean the result sounds on a real song is unjudged.
- `find` / `fetch` / the clearance gate, against a stand-in for `yt-dlp`
  that returns sample metadata. A video from a channel outside `SOURCES`
  without a Creative Commons license is refused and nothing is downloaded.

**Not tested** (YouTube is blocked in the container):

- `find` and `fetch` against real YouTube. Check the two `channel_id` values
  in `SOURCES` first: run `find "energy"`, then
  `yt-dlp --dump-json --no-playlist <first url>` and compare `channel_id`.
  If it differs, fix the constant, otherwise `fetch` refuses every track.
  The channel search URL and the Creative Commons search filter are also
  unconfirmed against the live site.
- Anything on Windows.

## Install (once, on the Clipper PC)

```
portable\python\python.exe -m pip install yt-dlp "audio-separator[cpu]" audioread
```

`audioread` is needed for MP3 input; without it vocal removal fails with
`No module named 'audioread'`.

With an NVIDIA card use `"audio-separator[gpu]"` instead: vocal removal drops
from a minute or two per song to a few seconds. `ffmpeg` and `ffprobe` must be
on PATH. If the Clipper calls ffmpeg by full path, prepend that folder to
`os.environ["PATH"]` before the first `clipper_music` call.

Smoke test before touching the app:

```
portable\python\python.exe clipper_music.py find "energy"
portable\python\python.exe clipper_music.py get <url from the list> --instrumental
portable\python\python.exe clipper_music.py list
portable\python\python.exe clipper_music.py mix some_clip.mp4 <id> out.mp4
```

## UI: a Music box

Next to the Game box, add:

- a text entry and a **Find** button
- a list of results
- a **Use** button, and a **No vocals** checkbox
- a dropdown of saved tracks, with "None" first, that the clip step reads

Every call below is slow, so run it on a worker thread like the OBS calls and
report through `put`:

```python
log = lambda m: self.put("status", m)

def _music_find(self, query):
    try:
        self.put("music_results", clipper_music.find(query, source="ncs"))
    except clipper_music.MusicError as e:
        self.put("status", str(e))

def _music_use(self, hit, no_vocals):
    try:
        track = clipper_music.fetch(hit["url"], log=log)
        if no_vocals and not track.get("instrumental"):
            clipper_music.make_instrumental(track, log=log)
        self.put("music_tracks", clipper_music.tracks())   # refresh the dropdown
    except clipper_music.MusicError as e:
        self.put("status", str(e))
```

`find` takes `source="ncs"`, `"audiolibrary"` or `"cc"`. A source dropdown is
optional; `"ncs"` is the catchy one.

## Clip step: mix after the clip is rendered

Find where the finished clip file is written (after the facecam/gameplay
stack and the burned-in captions). Add the music as the last step, to a new
file, then swap it in:

```python
if self.music_track_id:                       # None when the dropdown says "None"
    try:
        track = clipper_music.get(self.music_track_id)
        tmp = clip_path + ".music.mp4"
        clipper_music.mix(clip_path, track, tmp, log=log)
        os.replace(tmp, clip_path)
        credit = clipper_music.credit(track)
    except clipper_music.MusicError as e:
        self.put("status", f"Clip saved without music: {e}")
        credit = ""
```

A music failure must never lose the clip, hence the try/except around the
whole block.

`mix` copies the video stream, so it adds a second or two, not a re-encode.
Defaults: music at -16 dB, dipping further while the clip's own audio is loud.

## Caption: add the credit

NCS and Audio Library tracks are free to use **only with credit**. Where the
caption is built (the 5-hashtag code), put `credit` on its own line above the
hashtags when it is not empty. Do not count it against the hashtag cap.

## Verify

```
portable\python\python.exe -m py_compile clipper_app.py clipper_music.py
Desktop\_restart_clipper.bat
```

1. Find "energy", Use the first result with No vocals ticked. Status shows
   Downloading, then Removing vocals, then Instrumental ready.
2. Make a clip with that track selected: the music sits under the voice and
   fades at the end. The caption has the credit line.
3. Select "None" and make a clip: no music, no credit line.
4. Disconnect the network and click Find: a status message, no crash.

---

# Separate fix: the gameplay screen is slightly too big

In the vertical layout (facecam on top, gameplay below), the gameplay panel is
cropped on the left and right: in the posted Reel the credits text and the car
are cut off at both edges. The panel is roughly 1.62:1 but the game is 16:9
(1.78:1), so about 9% of the width is lost.

The cause will be a scale-to-fill followed by a crop in the ffmpeg filter for
the gameplay panel, something like:

```
scale=1080:H:force_original_aspect_ratio=increase,crop=1080:H
```

Fix: fit the gameplay to the full width and give the panel the height that
matches. On a 1080x1920 canvas a 16:9 source is exactly 1080x608:

```
scale=1080:-2          (gameplay: full width, nothing cropped)
```

Then take the difference out of the facecam panel (it is a crop of a webcam,
so losing a little height there costs nothing), or keep the panel sizes and
replace the crop with a pad:

```
scale=1080:H:force_original_aspect_ratio=decrease,pad=1080:H:(ow-iw)/2:(oh-ih)/2:color=0x14121f
```

Resizing the panels looks better than padding. If the game is recorded at an
aspect other than 16:9, compute the panel height as `1080 * src_h / src_w`
rounded to an even number rather than hard-coding 608. Check afterwards that
the caption bar and the lower banner still sit on the seam and not over the
gameplay.
