# poop

> **Disclaimer:** This project is a joke. It is 100% AI-generated slop. It was vibe-coded into existence by mass-prompting Claude while complaining about VLC in a Discord server. It probably works. No promises.

**P**lays **O**nly **O**pen **P**layback.

A 250-line music player that does what VLC has failed to do for decades: play your music without hanging, crashing, or forgetting how HTTP works.

## Why not VLC?

- VLC **hangs at the end of MP3 files**. Just sits there. Silence. You have to babysit it.
- VLC's HTTP remote interface **breaks after a few commands**. Every time. It's been like this for years.
- VLC's shuffle is "random" the way a toddler is "random" — it plays the same three songs and ignores the rest.
- VLC is **3.5 million lines of C**. poop is 250 lines of Python. Guess which one has fewer bugs.

poop doesn't hang. poop doesn't break. poop doesn't forget what "shuffle" means.

## What poop does

- Scans a directory for audio files
- Plays them in **weighted random** order — recently played tracks are suppressed, so you actually hear your whole library
- Exposes a dead-simple **HTTP API** for remote control
- Uses `ffplay` under the hood — each track is a clean subprocess that exits when it's done. No hanging. Ever.

## Install

```
brew install ffmpeg   # or however you get ffplay on your system
```

That's it. No pip install. No virtualenv. No requirements.txt. Just Python 3 and ffmpeg.

## Usage

```bash
python3 poop.py ~/Music
```

Starts playing immediately. API runs on port 8888 by default.

```bash
python3 poop.py ~/Music -p 9999   # custom port
```

## API

All endpoints are `GET` and return JSON. Control your music from `curl`, a browser, a webhook, a Shortcut, whatever.

| Endpoint  | What it does |
|-----------|-------------|
| `/play`   | Start or resume playback |
| `/pause`  | Toggle pause/resume |
| `/next`   | Skip to next track (weighted random) |
| `/prev`   | Go back to previous track |
| `/stop`   | Stop playback |
| `/status` | Current track, position, duration, state |
| `/queue`  | All tracks with their current shuffle weights |

### Examples

```bash
# What's playing?
curl localhost:8888/status

# Skip this one
curl localhost:8888/next

# See the weighted queue
curl localhost:8888/queue
```

## Weighted shuffle

poop maintains a play history. A track's shuffle weight is based on how long ago it was last played:

- **Never played** → weight 1.0 (high chance)
- **Just played** → weight ~0.0 (nearly impossible to repeat)
- **Played a while ago** → weight gradually recovers

The result: you hear your entire library instead of the same 10 songs on repeat. This is what VLC's shuffle should have been since 2001.

## Supported formats

mp3, flac, ogg, opus, wav, m4a, aac, wma — anything ffplay can handle.

## License

MIT
