#!/usr/bin/env python3
"""poop.py — Weighted-shuffle music player with HTTP API. Zero pip dependencies."""

import argparse
import atexit
import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac", ".wma"}
FFPLAY = "ffplay"
FFPROBE = "ffprobe"


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
    def __init__(self, playlist):
        self.playlist = playlist
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
            if self.state == "paused" and self.proc:
                os.kill(self.proc.pid, signal.SIGCONT)
                self.state = "playing"
                self.track_start_time = time.time() - self.pause_elapsed
                return
            if self.state == "playing":
                return
            self._play_next()

    def pause(self):
        with self.lock:
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
        if self.proc:
            self._skip_advance = True
            try:
                # Resume first in case it's paused, otherwise terminate hangs
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
            time.sleep(0.2)
            with self.lock:
                if self.state == "playing" and self.proc and self.proc.poll() is not None:
                    # Only auto-advance if ffplay exited on its own (track ended).
                    # If _kill_proc was called, state is already updated by the caller.
                    if not self._skip_advance:
                        self._play_next()
                    self._skip_advance = False

    def shutdown(self):
        self._stop_event.set()
        with self.lock:
            self._kill_proc()


class APIHandler(BaseHTTPRequestHandler):
    player = None  # set before server starts

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
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._json(404, {"error": "not found", "routes": list(routes.keys())})

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

    def _json(self, code, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # silence request logs


def main():
    parser = argparse.ArgumentParser(description="poop.py — weighted-shuffle music player")
    parser.add_argument("directory", help="Directory containing audio files")
    parser.add_argument("-p", "--port", type=int, default=8888, help="HTTP port (default: 8888)")
    args = parser.parse_args()

    playlist = WeightedPlaylist(args.directory)
    print(f"Found {len(playlist.tracks)} tracks in {args.directory}")

    player = Player(playlist)
    atexit.register(player.shutdown)

    player.play()

    APIHandler.player = player
    server = HTTPServer(("0.0.0.0", args.port), APIHandler)
    print(f"API listening on http://localhost:{args.port}")
    print("Endpoints: /play /pause /next /prev /stop /status /queue")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
