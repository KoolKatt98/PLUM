"""OBS health helpers for the ex.tortion Clipper (fixes for bugs A and C/D).

Drop this file next to clipper_app.py and import it:

    import obs_health

Everything here is standard library only and safe to call from a worker thread.
"""
import socket
import subprocess
import sys
import time

OBS_EXE = "obs64.exe"
WS_HOST = "127.0.0.1"
WS_PORT = 4455

# Hide the console window that tasklist/taskkill would otherwise flash.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

MSG_TWO_COPIES = "Two copies of OBS are open, click Restart OBS"
MSG_WS_OFF = "OBS remote control is off, click Restart OBS"
MSG_LOST_OBS = ("Lost OBS. Stop the recording in OBS directly (tray icon), "
                "clips will still be made via 'Clip the last recording'.")


def _run(args, timeout=10):
    try:
        out = subprocess.run(args, capture_output=True, text=True,
                             timeout=timeout, creationflags=_NO_WINDOW)
        return out.stdout or ""
    except Exception:
        return ""


def count_obs_processes():
    """Number of running obs64.exe processes (0 if tasklist fails)."""
    out = _run(["tasklist", "/FI", f"IMAGENAME eq {OBS_EXE}", "/FO", "CSV", "/NH"])
    return sum(1 for line in out.splitlines()
               if line.strip().lower().startswith(f'"{OBS_EXE}"'))


def port_open(host=WS_HOST, port=WS_PORT, timeout=1.0):
    """True if something is listening on the obs-websocket port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def diagnose():
    """Explain a repeated connect failure, or return None if nothing obvious.

    Call this from _connect_loop after N consecutive failed connects.
    """
    n = count_obs_processes()
    if n > 1:
        return MSG_TWO_COPIES
    if n == 1 and not port_open():
        return MSG_WS_OFF
    return None


def stop_obs(is_recording, grace=20.0, poll=1.0, log=print):
    """Close every OBS instance: polite first, forced only if safe.

    is_recording: zero-arg callable returning True if OBS might be recording
                  (e.g. lambda: core.recording). If it returns True, or raises,
                  we NEVER force-kill.
    Returns True when no obs64.exe is left.
    """
    if count_obs_processes() == 0:
        return True
    _run(["taskkill", "/IM", OBS_EXE])          # polite: lets OBS save + finalize
    deadline = time.time() + grace
    while time.time() < deadline:
        if count_obs_processes() == 0:
            return True
        time.sleep(poll)

    try:
        recording = bool(is_recording())
    except Exception:
        recording = True                         # unknown -> treat as recording
    if recording:
        log("OBS did not close and may be recording; not forcing it.")
        return False

    log("OBS did not close politely; forcing.")
    _run(["taskkill", "/F", "/IM", OBS_EXE])
    for _ in range(10):
        if count_obs_processes() == 0:
            return True
        time.sleep(poll)
    return count_obs_processes() == 0
