"""Background music for the ex.tortion Clipper: find free-to-use tracks, strip
the vocals, and mix the result under a clip.

Drop this file next to clipper_app.py and import it:

    import clipper_music

The module itself is standard library only. It shells out to three tools:

    ffmpeg / ffprobe   mixing (the Clipper already ships these)
    yt-dlp             finding and downloading tracks      (pip install yt-dlp)
    audio-separator    vocal removal ("stems")             (pip install "audio-separator[cpu]" audioread)

Nothing heavy is imported into the Clipper process, so a missing or broken
install only disables that one feature. Every function is safe to call from a
worker thread and takes log=..., e.g. log=lambda m: core.put("status", m).

Only music that is cleared for reuse is downloaded: tracks from the channels in
SOURCES, or videos YouTube itself marks Creative Commons. Removing vocals from
a commercial song does NOT make it safe: the instrumental is still copyrighted
and Content ID still matches it. Local files you already have the rights to
can be added with add_local().
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
MUSIC_DIR = os.path.join(HERE, "music")
LIBRARY = os.path.join(MUSIC_DIR, "library.json")

# Hide the console window each helper process would otherwise flash.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Channels whose uploads are published for creators to reuse. "terms" is what
# the label asks for; credit() turns it into the line for the description.
# Labels change their terms, so re-check the link before monetizing.
SOURCES = {
    "ncs": {
        "name": "NoCopyrightSounds",
        "channel": "https://www.youtube.com/@NoCopyrightSounds",
        "channel_id": "UC_aEa8K-EOJ3D6gOs7HcyNg",
        "license": "NCS usage policy (credit required)",
        "terms": "https://ncs.io/usage-policy",
        "credit": "Music: {title} | provided by NoCopyrightSounds | {url}",
    },
    "audiolibrary": {
        "name": "Audio Library",
        "channel": "https://www.youtube.com/@AudioLibrary",
        "channel_id": "UCht8qITGkBvXKsR1Byln-wA",
        "license": "per-track, see the video description (credit required)",
        "terms": "https://www.youtube.com/@AudioLibrary/about",
        "credit": "Music: {title} | promoted by Audio Library | {url}",
    },
}
CC_SEARCH = "cc"            # pseudo-source: any video YouTube marks Creative Commons
CC_LICENSE_MARK = "creative commons"
DEFAULT_MODEL = "UVR-MDX-NET-Inst_HQ_3.onnx"   # instrumental-focused, runs fine on CPU


class MusicError(Exception):
    """Something the user should see as a status message."""


class NotCleared(MusicError):
    """The track is not from a cleared source, so it was not downloaded."""


# ---------------------------------------------------------------- helpers

def _run(args, timeout=None):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace",
                              creationflags=_NO_WINDOW)
    except FileNotFoundError:
        raise MusicError(f"{args[0]} is not installed")
    except subprocess.TimeoutExpired:
        raise MusicError(f"{os.path.basename(str(args[0]))} timed out")


def _tool(name, module=None):
    """Command prefix for a helper: the exe if it is on PATH, else python -m."""
    exe = shutil.which(name)
    if exe:
        return [exe]
    if module:
        return [sys.executable, "-m", module]
    raise MusicError(f"{name} is not installed")


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "track"


def _load():
    try:
        with open(LIBRARY, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(lib):
    os.makedirs(MUSIC_DIR, exist_ok=True)
    tmp = LIBRARY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lib, f, indent=2)
    os.replace(tmp, LIBRARY)


def _path(track, key="file"):
    return os.path.join(MUSIC_DIR, track[key]) if track.get(key) else None


# ---------------------------------------------------------------- library

def tracks():
    """Every saved track, newest first. Each is a dict (see _register)."""
    return sorted(_load().values(), key=lambda t: t.get("added", 0), reverse=True)


def get(track_id):
    try:
        return _load()[track_id]
    except KeyError:
        raise MusicError(f"No track called {track_id!r}")


def audio_path(track, prefer_instrumental=True):
    """File to mix: the instrumental if one was made, else the original."""
    if prefer_instrumental and track.get("instrumental"):
        p = _path(track, "instrumental")
        if os.path.exists(p):
            return p
    return _path(track)


def credit(track):
    """Line to paste into the caption/description, or '' if none is needed."""
    return track.get("credit", "")


def _register(file, title, artist, url, license, credit_line, source):
    lib = _load()
    base = _slug(f"{artist} {title}" if artist else title)
    track_id, n = base, 2
    while track_id in lib and lib[track_id].get("url") != url:
        track_id, n = f"{base}-{n}", n + 1
    lib[track_id] = {
        "id": track_id, "title": title, "artist": artist, "url": url,
        "license": license, "credit": credit_line, "source": source,
        "file": os.path.basename(file), "instrumental": None, "added": time.time(),
    }
    _save(lib)
    return lib[track_id]


def add_local(path, title, artist="", url="", license="", credit_line=""):
    """Add a file you already have the rights to (YouTube Audio Library
    download, Pixabay, your own beat). The file is copied into the library."""
    if not os.path.isfile(path):
        raise MusicError(f"File not found: {path}")
    os.makedirs(MUSIC_DIR, exist_ok=True)
    ext = os.path.splitext(path)[1] or ".mp3"
    dest = os.path.join(MUSIC_DIR, _slug(f"{artist} {title}") + ext)
    if os.path.abspath(path) != os.path.abspath(dest):
        shutil.copyfile(path, dest)
    return _register(dest, title, artist, url, license or "user supplied",
                     credit_line, "local")


# ---------------------------------------------------------------- find + download

def _ytdlp_json(args, timeout=120):
    out = _run(_tool("yt-dlp", "yt_dlp") + ["--no-warnings", "--ignore-errors",
                                             "--dump-json"] + args, timeout=timeout)
    rows = []
    for line in out.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    if not rows and out.returncode:
        raise MusicError((out.stderr.strip().splitlines() or ["yt-dlp failed"])[-1])
    return rows


def find(query, source="ncs", limit=8):
    """Search one cleared source. Returns [{title, url, duration, source}].

    source: a key of SOURCES, or "cc" for any Creative Commons video.
    """
    q = urllib.parse.quote_plus(query)
    if source == CC_SEARCH:
        # sp=EgIwAQ== is YouTube's own "Creative Commons" search filter.
        url = f"https://www.youtube.com/results?search_query={q}&sp=EgIwAQ%253D%253D"
    elif source in SOURCES:
        url = f"{SOURCES[source]['channel']}/search?query={q}"
    else:
        raise MusicError(f"Unknown source {source!r}")
    rows = _ytdlp_json(["--flat-playlist", "--playlist-end", str(limit), url])
    hits = []
    for r in rows:
        vid = r.get("id")
        if not vid or r.get("ie_key") not in (None, "Youtube"):
            continue
        hits.append({"title": r.get("title") or vid,
                     "url": f"https://www.youtube.com/watch?v={vid}",
                     "duration": r.get("duration"), "source": source})
    return hits[:limit]


def clearance(info):
    """(source_key, license_text) for yt-dlp metadata, or raise NotCleared."""
    for key, src in SOURCES.items():
        if info.get("channel_id") == src["channel_id"]:
            return key, src["license"]
    lic = info.get("license") or ""
    if CC_LICENSE_MARK in lic.lower():
        return CC_SEARCH, lic
    raise NotCleared(
        f"'{info.get('title', 'That video')}' is not from a free-to-use source, "
        "so it would get a copyright claim. Pick a track from find() instead.")


def _split_title(raw):
    """'Artist - Song [NCS Release]' -> ('Song', 'Artist')."""
    name = re.sub(r"\s*[\[(|][^\])]*(ncs|release|copyright|audio library|music)[^\])]*[\])]?\s*$",
                  "", raw, flags=re.I).strip() or raw
    if " - " in name:
        artist, title = name.split(" - ", 1)
        return title.strip(), artist.strip()
    return name, ""


def fetch(url, log=print):
    """Download one track from a cleared source into the library.

    Raises NotCleared (and downloads nothing) for anything else.
    """
    info = _ytdlp_json(["--no-playlist", url])
    if not info:
        raise MusicError("Could not read that video")
    info = info[0]
    source, license = clearance(info)
    page = info.get("webpage_url") or url

    for t in _load().values():
        if t.get("url") == page and os.path.exists(_path(t)):
            return t

    title, artist = _split_title(info.get("title") or info["id"])
    os.makedirs(MUSIC_DIR, exist_ok=True)
    stem = f"{_slug(f'{artist} {title}')}-{_slug(info['id'])}"   # id keeps re-uploads apart
    log(f"Downloading {title}...")
    out = _run(_tool("yt-dlp", "yt_dlp") + [
        "--no-warnings", "--no-playlist", "-f", "bestaudio/best", "-x",
        "--audio-format", "mp3", "--audio-quality", "0",
        "-o", os.path.join(MUSIC_DIR, stem + ".%(ext)s"), page], timeout=600)
    dest = os.path.join(MUSIC_DIR, stem + ".mp3")
    if out.returncode or not os.path.exists(dest):
        raise MusicError((out.stderr.strip().splitlines() or ["Download failed"])[-1])

    shown = f"{artist} - {title}" if artist else title
    if source in SOURCES:
        line = SOURCES[source]["credit"].format(title=shown, url=page)
    else:
        line = f"Music: {shown} by {info.get('uploader', 'unknown')} (CC BY) | {page}"
    track = _register(dest, title, artist, page, license, line, source)
    log(f"Saved {shown}")
    return track


# ---------------------------------------------------------------- stems

def make_instrumental(track_or_path, model=DEFAULT_MODEL, log=print):
    """Remove the vocals. Slow: about 1-3 min per song on CPU, and the first
    run downloads the model (~70 MB).

    Pass a library track (dict or id) to store the result on it, or any audio
    file path to get an instrumental next to that file. Returns the new path.
    """
    track = None
    if isinstance(track_or_path, dict):
        track = track_or_path
    elif not os.path.isfile(track_or_path):
        track = get(track_or_path)
    src = _path(track) if track else os.path.abspath(track_or_path)
    if not os.path.isfile(src):
        raise MusicError(f"File not found: {src}")

    out_dir = os.path.dirname(src)
    base = os.path.splitext(os.path.basename(src))[0]
    before = set(os.listdir(out_dir))
    log("Removing vocals, this takes a minute or two...")
    res = _run(_tool("audio-separator", "audio_separator.utils.cli") + [
        src, "--model_filename", model, "--single_stem", "Instrumental",
        "--output_format", "MP3", "--output_dir", out_dir,
        "--model_file_dir", os.path.join(MUSIC_DIR, "_models")], timeout=3600)
    made = [f for f in set(os.listdir(out_dir)) - before
            if "instrumental" in f.lower() and f.startswith(base)]
    if res.returncode or not made:
        raise MusicError((res.stderr.strip().splitlines() or ["Vocal removal failed"])[-1])

    final = os.path.join(out_dir, base + ".instrumental.mp3")
    os.replace(os.path.join(out_dir, made[0]), final)
    if track:
        lib = _load()
        lib[track["id"]]["instrumental"] = os.path.basename(final)
        _save(lib)
        track["instrumental"] = os.path.basename(final)
    log("Instrumental ready")
    return final


# ---------------------------------------------------------------- mix

def _probe(path):
    """(duration_seconds, has_audio) for a media file."""
    res = _run(["ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_type", "-of", "json", path], timeout=60)
    try:
        data = json.loads(res.stdout)
        dur = float(data["format"]["duration"])
    except (ValueError, KeyError):
        raise MusicError(f"Could not read {os.path.basename(path)}")
    return dur, any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def mix(video, music, out, music_db=-16.0, duck=True, start=0.0, fade=1.5, log=print):
    """Lay music under a clip. The video stream is copied, not re-encoded.

    music:    library track (dict or id) or an audio file path
    music_db: music level. -16 sits under commentary; raise toward -8 for a
              montage with no talking
    duck:     dip the music whenever the clip's own audio (voice, game) is loud
    start:    seconds into the song to begin at (skip a slow intro)
    The song loops if the clip is longer, and fades out at the end.
    """
    if isinstance(music, dict):
        music = audio_path(music)
    elif not os.path.isfile(music):
        music = audio_path(get(music))
    if not os.path.isfile(video):
        raise MusicError(f"File not found: {video}")
    if os.path.abspath(out) == os.path.abspath(video):
        raise MusicError("Output must be a different file from the input clip")

    dur, has_audio = _probe(video)
    fade = min(fade, dur / 2)
    bed = (f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={music_db}dB,"
           f"atrim=0:{dur:.3f},afade=t=out:st={dur - fade:.3f}:d={fade:.3f}")
    if not has_audio:
        graph = bed + "[a]"
    elif duck:
        graph = (bed + "[bed];"
                 "[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[clip][key];"
                 "[bed][key]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[low];"
                 "[clip][low]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        graph = (bed + "[bed];"
                 "[0:a]aresample=48000,aformat=channel_layouts=stereo[clip];"
                 "[clip][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")

    log("Adding music...")
    res = _run(["ffmpeg", "-y", "-v", "error", "-i", video,
                "-stream_loop", "-1", "-ss", f"{start:.3f}", "-i", music,
                "-filter_complex", graph, "-map", "0:v:0", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-t", f"{dur:.3f}", "-movflags", "+faststart", out], timeout=1800)
    if res.returncode or not os.path.exists(out):
        raise MusicError((res.stderr.strip().splitlines() or ["ffmpeg failed"])[-1])
    log("Music added")
    return out


# ---------------------------------------------------------------- CLI

def _main(argv):
    import argparse
    p = argparse.ArgumentParser(prog="clipper_music", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("find", help="search a free-to-use source")
    s.add_argument("query")
    s.add_argument("--source", default="ncs", choices=list(SOURCES) + [CC_SEARCH])
    s.add_argument("--limit", type=int, default=8)
    s = sub.add_parser("get", help="download a track (cleared sources only)")
    s.add_argument("url")
    s.add_argument("--instrumental", action="store_true", help="also remove the vocals")
    s = sub.add_parser("add", help="add a local file you have the rights to")
    s.add_argument("path")
    s.add_argument("--title", required=True)
    s.add_argument("--artist", default="")
    s.add_argument("--credit", default="")
    s = sub.add_parser("stem", help="remove vocals from a track id or any audio file")
    s.add_argument("track")
    sub.add_parser("list", help="show saved tracks")
    s = sub.add_parser("mix", help="put a track under a clip")
    s.add_argument("video")
    s.add_argument("track")
    s.add_argument("out")
    s.add_argument("--db", type=float, default=-16.0)
    s.add_argument("--no-duck", action="store_true")
    s.add_argument("--start", type=float, default=0.0)
    a = p.parse_args(argv)

    try:
        if a.cmd == "find":
            for h in find(a.query, a.source, a.limit):
                d = h["duration"]
                length = f"{int(d) // 60}:{int(d) % 60:02d}" if d else "  ?"
                print(f"{length:>5}  {h['title']}\n       {h['url']}")
        elif a.cmd == "get":
            t = fetch(a.url)
            if a.instrumental:
                make_instrumental(t)
            print(f"id: {t['id']}\ncredit: {credit(t)}")
        elif a.cmd == "add":
            t = add_local(a.path, a.title, a.artist, credit_line=a.credit)
            print(f"id: {t['id']}")
        elif a.cmd == "stem":
            print(make_instrumental(a.track))
        elif a.cmd == "list":
            for t in tracks():
                mark = "inst" if t.get("instrumental") else "    "
                print(f"{mark}  {t['id']:<40} {t['license']}")
        elif a.cmd == "mix":
            mix(a.video, a.track, a.out, music_db=a.db, duck=not a.no_duck, start=a.start)
            if not os.path.isfile(a.track):
                c = credit(get(a.track))
                if c:
                    print(f"Add to the caption:\n{c}")
    except MusicError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
