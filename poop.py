#!/usr/bin/env python3
"""poop.py — Weighted-shuffle music player with HTTP API. Optional Chromecast support via pychromecast."""

import argparse
import atexit
import json
import os
import random
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac", ".wma"}
AUDIO_MIMES = {
    ".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg",
    ".opus": "audio/opus", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".wma": "audio/x-ms-wma",
}
FFPLAY = "ffplay"
FFPROBE = "ffprobe"


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


REMOTE_HTML = """\
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>poop</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:#0a0a0a;color:#e8e4df;font-family:'JetBrains Mono',monospace;
  overflow:hidden;touch-action:manipulation;user-select:none}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:1.5rem;gap:1rem}
.hero{font-size:clamp(4rem,15vw,7rem);line-height:1;text-align:center;
  filter:drop-shadow(0 0 40px rgba(200,120,40,.3))}
.hero.spinning{animation:spin 3s linear infinite}
.hero.stopped{filter:grayscale(1) drop-shadow(0 0 10px rgba(100,100,100,.2))}
@keyframes spin{to{transform:rotate(360deg)}}
.track{text-align:center;max-width:90vw;min-height:2.8em}
.track-name{font-size:clamp(.85rem,3vw,1.1rem);font-weight:700;color:#f5f0eb;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:80vw;
  display:block;margin:0 auto}
.track-state{font-size:.7rem;text-transform:uppercase;letter-spacing:.15em;
  color:#8a7e72;margin-top:.25rem}
.progress{width:min(80vw,360px);height:4px;background:#1e1c1a;border-radius:2px;overflow:hidden}
.progress-fill{height:100%;background:linear-gradient(90deg,#c87828,#e8a848);
  border-radius:2px;width:0%;transition:width .8s linear}
.time{display:flex;justify-content:space-between;width:min(80vw,360px);
  font-size:.65rem;color:#5a5550;margin-top:-.15rem}
.controls{display:flex;gap:clamp(.6rem,3vw,1.2rem);align-items:center}
.btn{background:none;border:2px solid #2a2622;color:#c8beb4;
  width:clamp(48px,12vw,56px);height:clamp(48px,12vw,56px);
  border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:clamp(1.1rem,3vw,1.3rem);cursor:pointer;transition:all .15s;
  -webkit-tap-highlight-color:transparent;position:relative;overflow:hidden}
.btn:active{transform:scale(.9);background:#1a1816}
.btn.primary{width:clamp(60px,15vw,72px);height:clamp(60px,15vw,72px);
  border-color:#c87828;color:#e8a848;font-size:clamp(1.4rem,4vw,1.7rem)}
.btn.primary:active{background:#2a1a08}
.btn.stop{font-size:clamp(.9rem,2.5vw,1rem)}
.cast-section{display:flex;gap:.5rem;align-items:center;margin-top:.5rem;
  flex-wrap:wrap;justify-content:center}
select{background:#141210;border:1px solid #2a2622;color:#c8beb4;
  font-family:inherit;font-size:.75rem;padding:.5rem .8rem;border-radius:6px;
  appearance:none;-webkit-appearance:none;min-width:160px;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 5l3 3 3-3' stroke='%235a5550' fill='none' stroke-width='1.5'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right .6rem center;padding-right:2rem}
select:focus{outline:none;border-color:#c87828}
.cast-btn{background:#141210;border:1px solid #2a2622;color:#8a7e72;
  font-family:inherit;font-size:.7rem;padding:.5rem 1rem;border-radius:6px;
  cursor:pointer;transition:all .15s;text-transform:uppercase;letter-spacing:.1em}
.cast-btn:active{background:#1a1816}
.cast-btn.active{border-color:#c87828;color:#e8a848}
.cast-status{font-size:.65rem;color:#5a5550;width:100%;text-align:center;min-height:1em}
</style>
</head><body>

<div class="hero" id="hero">&#128169;</div>

<div class="track">
  <span class="track-name" id="track">---</span>
  <div class="track-state" id="state">stopped</div>
</div>

<div class="progress"><div class="progress-fill" id="fill"></div></div>
<div class="time"><span id="pos">0:00</span><span id="dur">0:00</span></div>

<div class="controls">
  <button class="btn" onclick="cmd('prev')" aria-label="Previous">&#9198;</button>
  <button class="btn stop" onclick="cmd('stop')" aria-label="Stop">&#9632;</button>
  <button class="btn primary" id="playpause" onclick="togglePlay()" aria-label="Play/Pause">&#9654;&#65039;</button>
  <button class="btn" onclick="cmd('next')" aria-label="Next">&#9197;</button>
</div>

<div class="cast-section">
  <select id="devices"><option value="">Local playback</option></select>
  <button class="cast-btn" id="castbtn" onclick="castTo()">Cast</button>
  <div class="cast-status" id="caststatus"></div>
</div>

<script>
var currentState = 'stopped';

function fmt(s) {
  if (!s || s < 0) return '0:00';
  var m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return m + ':' + (sec < 10 ? '0' : '') + sec;
}

function cmd(c) {
  fetch('/' + c).catch(function(){});
}

function togglePlay() {
  cmd(currentState === 'playing' ? 'pause' : 'play');
}

function poll() {
  fetch('/status').then(function(r){return r.json()}).then(function(s) {
    currentState = s.state;
    document.getElementById('track').textContent = s.track || '---';
    document.getElementById('state').textContent = s.state;
    document.getElementById('pos').textContent = fmt(s.position);
    document.getElementById('dur').textContent = fmt(s.duration);
    var pct = s.duration > 0 ? (s.position / s.duration * 100) : 0;
    document.getElementById('fill').style.width = Math.min(pct, 100) + '%';
    var hero = document.getElementById('hero');
    var pp = document.getElementById('playpause');
    if (s.state === 'playing') {
      hero.className = 'hero spinning';
      pp.innerHTML = '&#10074;&#10074;';
    } else if (s.state === 'paused') {
      hero.className = 'hero';
      pp.innerHTML = '&#9654;&#65039;';
    } else {
      hero.className = 'hero stopped';
      pp.innerHTML = '&#9654;&#65039;';
    }
  }).catch(function(){});
}

function loadDevices() {
  fetch('/cast-list').then(function(r){return r.json()}).then(function(d) {
    var sel = document.getElementById('devices');
    var current = sel.value;
    while (sel.options.length > 1) sel.remove(1);
    (d.devices || []).forEach(function(name) {
      var opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      sel.appendChild(opt);
    });
    if (current) sel.value = current;
    if (d.connected) {
      sel.value = d.connected;
      document.getElementById('castbtn').classList.add('active');
      document.getElementById('castbtn').textContent = 'Disconnect';
      document.getElementById('caststatus').textContent = 'casting to ' + d.connected;
    }
  }).catch(function(){});
}

function castTo() {
  var sel = document.getElementById('devices');
  var btn = document.getElementById('castbtn');
  var st = document.getElementById('caststatus');
  if (btn.classList.contains('active')) {
    st.textContent = 'disconnecting...';
    fetch('/cast-stop').then(function(r){return r.json()}).then(function() {
      btn.classList.remove('active');
      btn.textContent = 'Cast';
      sel.value = '';
      st.textContent = 'local playback';
    }).catch(function(){ st.textContent = 'error'; });
    return;
  }
  var device = sel.value;
  if (!device) return;
  st.textContent = 'connecting...';
  fetch('/cast?device=' + encodeURIComponent(device))
    .then(function(r){return r.json()})
    .then(function(d) {
      if (d.error) { st.textContent = d.error; return; }
      btn.classList.add('active');
      btn.textContent = 'Disconnect';
      st.textContent = 'casting to ' + d.connected;
    }).catch(function(){ st.textContent = 'error'; });
}

poll();
setInterval(poll, 1000);
loadDevices();
</script>
</body></html>
"""


class WeightedPlaylist:
    def __init__(self, directory):
        self.tracks = sorted(
            p for p in Path(directory).rglob("*")
            if p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith(".")
        )
        if not self.tracks:
            print(f"No audio files found in {directory}", file=sys.stderr)
            sys.exit(1)
        self.play_history = []  # list of track indices, most recent last
        self.max_history = len(self.tracks) * 2

    def pick_next(self):
        n = len(self.tracks)
        weights = [1.0] * n
        for age, idx in enumerate(reversed(self.play_history)):
            # age 0 = most recently played → lowest weight
            w = (age + 1) / (len(self.play_history) + 1)
            weights[idx] = min(weights[idx], w)
        chosen = random.choices(range(n), weights=weights, k=1)[0]
        self._record(chosen)
        return chosen

    def pick_prev(self):
        if len(self.play_history) >= 2:
            self.play_history.pop()  # remove current
            return self.play_history[-1]
        return self.play_history[-1] if self.play_history else 0

    def _record(self, idx):
        self.play_history.append(idx)
        if len(self.play_history) > self.max_history:
            self.play_history = self.play_history[-self.max_history:]

    def get_weights(self):
        n = len(self.tracks)
        weights = [1.0] * n
        for age, idx in enumerate(reversed(self.play_history)):
            w = (age + 1) / (len(self.play_history) + 1)
            weights[idx] = min(weights[idx], w)
        return weights


def get_duration(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=5,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


class Player:
    def __init__(self, playlist, cast_mode=False, base_url=None, chromecast=None):
        self.playlist = playlist
        self.cast_mode = cast_mode
        self.base_url = base_url  # e.g. "http://192.168.1.5:8888"
        self.chromecast = chromecast  # pychromecast CastDevice
        self.lock = threading.Lock()
        self.proc = None
        self.current_idx = None
        self.state = "stopped"  # playing, paused, stopped
        self.track_start_time = 0.0
        self.pause_elapsed = 0.0
        self._stop_event = threading.Event()
        self._skip_advance = False

        t = threading.Thread(target=self._advance_loop, daemon=True)
        t.start()

    def play(self):
        with self.lock:
            if self.state == "paused":
                if self.cast_mode and self.chromecast:
                    self.chromecast.media_controller.play()
                    self.state = "playing"
                    self.track_start_time = time.time() - self.pause_elapsed
                    return
                if self.proc:
                    os.kill(self.proc.pid, signal.SIGCONT)
                    self.state = "playing"
                    self.track_start_time = time.time() - self.pause_elapsed
                    return
            if self.state == "playing":
                return
            self._play_next()

    def pause(self):
        with self.lock:
            if self.cast_mode and self.chromecast:
                if self.state == "playing":
                    self.pause_elapsed = time.time() - self.track_start_time
                    self.chromecast.media_controller.pause()
                    self.state = "paused"
                elif self.state == "paused":
                    self.chromecast.media_controller.play()
                    self.state = "playing"
                    self.track_start_time = time.time() - self.pause_elapsed
                return
            if self.state == "playing" and self.proc:
                self.pause_elapsed = time.time() - self.track_start_time
                os.kill(self.proc.pid, signal.SIGSTOP)
                self.state = "paused"
            elif self.state == "paused" and self.proc:
                os.kill(self.proc.pid, signal.SIGCONT)
                self.state = "playing"
                self.track_start_time = time.time() - self.pause_elapsed

    def next(self):
        with self.lock:
            self._kill_proc()
            self._play_next()

    def prev(self):
        with self.lock:
            self._kill_proc()
            idx = self.playlist.pick_prev()
            self._start(idx)

    def stop(self):
        with self.lock:
            self._kill_proc()
            self.state = "stopped"

    def status(self):
        with self.lock:
            if self.current_idx is None:
                return {"state": self.state, "track": None, "position": 0, "duration": 0}
            track = self.playlist.tracks[self.current_idx]
            dur = get_duration(track)
            if self.state == "playing":
                pos = time.time() - self.track_start_time
            elif self.state == "paused":
                pos = self.pause_elapsed
            else:
                pos = 0
            return {
                "state": self.state,
                "track": track.name,
                "path": str(track),
                "position": round(pos, 1),
                "duration": round(dur, 1),
                "index": self.current_idx,
            }

    def _play_next(self):
        idx = self.playlist.pick_next()
        self._start(idx)

    def _start(self, idx):
        self._kill_proc()
        track = self.playlist.tracks[idx]
        if self.cast_mode and self.chromecast:
            mime = AUDIO_MIMES.get(track.suffix.lower(), "audio/mpeg")
            url = f"{self.base_url}/audio/{idx}"
            self.chromecast.media_controller.play_media(
                url, mime, title=track.name, stream_type="BUFFERED",
            )
        else:
            self.proc = subprocess.Popen(
                [FFPLAY, "-nodisp", "-autoexit", "-loglevel", "quiet", str(track)],
                stdin=subprocess.DEVNULL,
            )
        self.current_idx = idx
        self.state = "playing"
        self.track_start_time = time.time()
        self.pause_elapsed = 0.0
        print(f"▶ {track.name}")

    def _kill_proc(self):
        if self.cast_mode:
            return
        if self.proc:
            self._skip_advance = True
            try:
                if self.state == "paused":
                    os.kill(self.proc.pid, signal.SIGCONT)
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    def _advance_loop(self):
        while not self._stop_event.is_set():
            time.sleep(0.5)
            with self.lock:
                if self.cast_mode and self.chromecast:
                    mc = self.chromecast.media_controller
                    if (self.state == "playing" and mc.status
                            and mc.status.player_is_idle
                            and mc.status.idle_reason == "FINISHED"):
                        self._play_next()
                elif self.state == "playing" and self.proc and self.proc.poll() is not None:
                    if not self._skip_advance:
                        self._play_next()
                    self._skip_advance = False

    def cast_connect(self, chromecast, base_url):
        """Switch to casting on the given chromecast device."""
        with self.lock:
            self._kill_proc()
            self.chromecast = chromecast
            self.base_url = base_url
            self.cast_mode = True
            if self.current_idx is not None:
                self._start(self.current_idx)

    def cast_disconnect(self):
        """Switch back to local ffplay playback."""
        with self.lock:
            if self.chromecast:
                try:
                    self.chromecast.media_controller.stop()
                    self.chromecast.quit_app()
                except Exception:
                    pass
            self.chromecast = None
            self.cast_mode = False
            if self.current_idx is not None:
                self._start(self.current_idx)

    def shutdown(self):
        self._stop_event.set()
        with self.lock:
            if self.cast_mode and self.chromecast:
                try:
                    self.chromecast.media_controller.stop()
                    self.chromecast.quit_app()
                except Exception:
                    pass
            else:
                self._kill_proc()


class APIHandler(BaseHTTPRequestHandler):
    player = None  # set before server starts
    port = 8888

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        routes = {
            "/play": self._play,
            "/pause": self._pause,
            "/next": self._next,
            "/prev": self._prev,
            "/stop": self._stop,
            "/status": self._status,
            "/queue": self._queue,
        }
        handler = routes.get(path or "/")
        if path in ("", "/"):
            self._home()
        elif handler:
            handler()
        elif path == "/cast-list":
            self._cast_list()
        elif path == "/cast":
            self._cast()
        elif path == "/cast-stop":
            self._cast_stop()
        elif path.startswith("/audio/"):
            self._audio(path)
        else:
            self._json(404, {"error": "not found"})

    def _play(self):
        self.player.play()
        self._json(200, self.player.status())

    def _pause(self):
        self.player.pause()
        self._json(200, self.player.status())

    def _next(self):
        self.player.next()
        self._json(200, self.player.status())

    def _prev(self):
        self.player.prev()
        self._json(200, self.player.status())

    def _stop(self):
        self.player.stop()
        self._json(200, {"state": "stopped"})

    def _status(self):
        self._json(200, self.player.status())

    def _queue(self):
        pl = self.player.playlist
        weights = pl.get_weights()
        tracks = [
            {"index": i, "name": t.name, "weight": round(w, 3)}
            for i, (t, w) in enumerate(zip(pl.tracks, weights))
        ]
        self._json(200, {"count": len(tracks), "tracks": tracks})

    def _home(self):
        body = REMOTE_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cast_list(self):
        connected = None
        if self.player.chromecast:
            connected = self.player.chromecast.cast_info.friendly_name
        try:
            import pychromecast
            chromecasts, browser = pychromecast.get_chromecasts()
            names = sorted(cc.cast_info.friendly_name for cc in chromecasts)
            browser.stop_discovery()
        except Exception:
            names = []
        self._json(200, {"devices": names, "connected": connected})

    def _cast(self):
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(self.path).query)
        device_name = query.get("device", [None])[0]
        if not device_name:
            self._json(400, {"error": "missing device parameter"})
            return
        try:
            cast = setup_chromecast(device_name)
            local_ip = get_local_ip()
            base_url = f"http://{local_ip}:{self.port}"
            self.player.cast_connect(cast, base_url)
            self._json(200, {"connected": cast.cast_info.friendly_name})
        except ValueError as e:
            self._json(404, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _cast_stop(self):
        self.player.cast_disconnect()
        self._json(200, {"state": "local"})

    def _audio(self, path):
        try:
            idx = int(path.split("/")[-1])
            track = self.player.playlist.tracks[idx]
        except (ValueError, IndexError):
            self._json(404, {"error": "invalid track index"})
            return
        mime = AUDIO_MIMES.get(track.suffix.lower(), "application/octet-stream")
        size = track.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(track, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _json(self, code, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # silence request logs


def scan_chromecasts():
    """Discover Chromecasts on the network. Returns (chromecasts, browser)."""
    import pychromecast
    print("Scanning for Chromecasts...")
    chromecasts, browser = pychromecast.get_chromecasts()
    if not chromecasts:
        print("No Chromecasts found on the network", file=sys.stderr)
        sys.exit(1)
    return chromecasts, browser



def setup_chromecast(device_name):
    """Discover and connect to a Chromecast by name. Returns the CastDevice.
    Raises ValueError if device not found or ambiguous."""
    chromecasts, browser = scan_chromecasts()
    needle = device_name.lower()
    matches = [cc for cc in chromecasts
               if needle in cc.cast_info.friendly_name.lower()]
    if not matches:
        names = [cc.cast_info.friendly_name for cc in chromecasts]
        browser.stop_discovery()
        raise ValueError(f"No device matching '{device_name}'. Available: {names}")
    if len(matches) > 1:
        names = [cc.cast_info.friendly_name for cc in matches]
        browser.stop_discovery()
        raise ValueError(f"Multiple devices match '{device_name}': {names}. Be more specific.")
    cast = matches[0]
    cast.wait()
    print(f"Connected to {cast.cast_info.friendly_name}")
    browser.stop_discovery()
    return cast


def main():
    parser = argparse.ArgumentParser(description="poop.py — weighted-shuffle music player")
    parser.add_argument("directory", help="Directory containing audio files")
    parser.add_argument("-p", "--port", type=int, default=8888, help="HTTP port (default: 8888)")
    args = parser.parse_args()

    playlist = WeightedPlaylist(args.directory)
    print(f"Found {len(playlist.tracks)} tracks in {args.directory}")

    player = Player(playlist)
    atexit.register(player.shutdown)

    APIHandler.player = player
    APIHandler.port = args.port
    server = ThreadingHTTPServer(("0.0.0.0", args.port), APIHandler)
    print(f"Remote: http://localhost:{args.port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
