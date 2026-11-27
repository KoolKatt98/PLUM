# Wiring bugs A–D into clipper_app.py

These were written without seeing `clipper_app.py`. The names below come from
CLIPPER_HANDOFF.md (`Core._connect_loop`, `put`, `self.obs`, `self.recording`,
`restart_obs`, `_stop`). Adjust them to match the real code.

**First:** `copy clipper_app.py clipper_app.py.pre_bugfix_bak`, then copy
`obs_health.py` next to it and add `import obs_health` at the top.

## Bugs B + C + A(1): `_connect_loop`

The shape the loop should end up with:

```python
def _connect_loop(self):
    fails = 0
    last_ping = 0.0
    while not self._quit:
        if self.obs.connected:
            fails = 0
            # Bug C: heartbeat every ~5s catches a half-dead socket
            if time.time() - last_ping >= 5:
                last_ping = time.time()
                try:
                    st = self.obs.request("GetRecordStatus", timeout=5)
                    rec = bool(st.get("outputActive"))
                    if rec != self.recording:
                        self.recording = rec
                        self.put("rec", rec)      # also stops a stale REC timer
                except Exception:
                    self.obs.close()              # reader thread fires on_close -> UI resets
            time.sleep(1)
            continue

        try:
            self.obs.connect(...)                 # keep the existing args
        except Exception:
            fails += 1
            self.put("obs", False)
            if fails >= 3:                        # Bug A: explain why
                msg = obs_health.diagnose()
                if msg:
                    self.put("status", msg)
            time.sleep(2)
            continue

        # Bug B: connected means connected, even if the next call fails
        fails = 0
        self.put("obs", True)
        try:
            st = self.obs.request("GetRecordStatus", timeout=5)
            self.recording = bool(st.get("outputActive"))
            self.put("rec", self.recording)
        except Exception:
            pass   # OBS still loading or switching collections; the heartbeat retries in <=5s
```

If an exception can happen *after* `connect()` elsewhere in that block (filter
setup and so on), catch it and call `self.obs.close()` instead of
`put("obs", False)`, so the state flag and the socket always agree.

Check what `obsws_min.request` actually returns. The `outputActive` key comes
straight from obs-websocket v5's `GetRecordStatus`, but the client might wrap it.

## Bug A(2): `restart_obs`

Replace the `taskkill` call with:

```python
if not obs_health.stop_obs(lambda: self.recording, log=lambda m: self.put("status", m)):
    return   # still alive (maybe recording): don't launch a second copy
# ...existing launch code (it already checks obs_running() first)
```

## Bug D: `_stop`

Before sending `StopRecord`:

```python
if not self.obs.connected:
    self.put("status", obs_health.MSG_LOST_OBS)
    return
```

Also wrap the `StopRecord` request: on a timeout or exception, call
`self.obs.close()` and show `MSG_LOST_OBS`.

## Verify

```
portable\python\python.exe -m py_compile clipper_app.py obsws_min.py obs_health.py
Desktop\_restart_clipper.bat
```

Manual checks:
1. With OBS closed, start the Clipper. Open OBS normally: the pill should
   change to connected within ~2s.
2. Start OBS a second time with "Launch Anyway". After ~6s the Clipper should
   say "Two copies of OBS are open".
3. Click Restart OBS while not recording: both copies close and one comes back.
4. Record, then kill OBS in Task Manager: within ~5s the REC timer stops
   and the pill shows disconnected.
