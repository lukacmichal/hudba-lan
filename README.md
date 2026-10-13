# hudba-lan — a music player for the whole flat

A Windows music player that streams whatever it is playing to the local
network, an Android app that finds it by itself, plays the stream and works
as a remote control, and a Firefox add-on that puts the same controls into the
browser toolbar.

Around the playing itself it does the boring jobs for me: unpacks downloaded
albums and gives them proper names, finds covers and lyrics, keeps a list of
new metal releases and counts what I really listen to. And since the phone is
already talking to the PC, it can also be its touchpad.

It started as "I want to hear the music from the laptop in the kitchen" and
grew from there. It is the biggest thing I have built: about 10 000 lines of
Python, 5 000 lines of Kotlin and a bit of JavaScript, ~275 Python tests and
~40 on the Android side.

Python · PySide6 · ffmpeg · SQLite · Kotlin · Jetpack Compose · LibVLC ·
Firefox WebExtensions

## What it looks like

<img src="docs/screenshots/player.png" alt="The PC player: playlist with track lengths, cover art, lyrics pane and the sleep buttons" width="760">

The PC player. The row above the playlist is most of the app in one line: two
*sleep* playlists, the importer that unpacks a downloaded album and renames it,
the new-releases list, and the statistics. On the right, the cover and the
*Metal Archives* link above it are what the player found for this album on its
own — the same lookup that renames the folder. Under the cover are the lyrics,
with a button for the DeepL translation. The line at the bottom says whether
the LAN stream is up — the address next to it is my home network.

<img src="docs/screenshots/remote.png" alt="The Android remote: what is playing, transport controls, volume and the whole playlist" width="240">

The phone, showing the same playlist the PC has, with the current track marked.
*Streaming nedostupný* is honest: nothing is playing at that moment, so ffmpeg
is not running and there is no stream to join. This shot was taken in an
emulator, where a UDP broadcast from the PC never arrives, so the player was
reached through the manual address the settings offer for exactly that case —
on a phone on the same Wi-Fi the discovery finds it without typing anything.

The interface is Slovak.

## What it does

**On the PC**

- **Plays** — playlist and history kept between runs, tray icon, autostart,
  global media keys, choice of audio output.
- **Streams** — ffmpeg starts on *Play* and stops on *Pause*, low-latency
  multicast to the LAN. When nothing plays, nothing runs.
- **Unpacks downloads** — one button takes every rar/zip/7z music archive from
  *Downloads*, unpacks it into the music folder and names the album
  `Artist - Album - Year` ([below](#the-part-i-like-most-album-names)). No
  WinRAR or 7-Zip needed: the `tar.exe` that ships with Windows reads all three.
- **Covers and lyrics** — the player finds the cover and the Metal Archives
  page by itself and saves the cover next to the music (`folder.jpg`), so each
  album is looked up once. Lyrics come from lrclib.net or lyrics.ovh. One click
  sends them to DeepL, and the translation is kept on disk too, so a song costs
  the quota once.
- **New releases** — a nightly job collects new metal albums and the player
  shows them in two tabs: *this week*, and *already out* — albums that reached
  Metal Archives only after their release date, so a "this week" list would
  never show them. The genre filter is edited right there, in the same file the
  nightly job reads. An album unpacked from *Downloads* ticks itself off.
- **Statistics** — tracks, artists and albums by play count, for all time, the
  year, 30 or 7 days. A play counts after 30 seconds of real playing, so
  skipped tracks don't. One SQLite database per laptop — two writers on a
  network share would break it sooner or later.
- **Two sleep buttons** — each one appends its own short playlist and starts
  it. Pressed every evening, the playlist still does not grow: if it already
  ends with those tracks, the player only jumps there. By default the added
  tracks go away again when the player quits.
- **Bookmarks** — tracks to start from with one click; playing then goes on
  from there and nothing is added. A bookmark keeps both the file and its
  position: the file alone is not enough when a track is in the playlist twice,
  the position alone moves whenever something is added above it.
- **Playlist backup** to the NAS — written only when the playlist changed, the
  last 30 kept for each laptop.

**On the phone**

- **Finds the PC by itself** — the player broadcasts a small UDP beacon every
  2 seconds with its API port, so no IP address is ever typed in.
- **Plays the stream** through LibVLC, with the controls in the notification.
- **Remote control** — what is playing, transport, volume and the whole
  playlist, with a search that ignores diacritics and word order
  (`opeth blackwater` finds *Opeth — Blackwater Park*, `mgla` finds *Mgła*).
- **Touchpad and keyboard for the PC** — the same gestures as on a laptop: one
  finger moves, a tap clicks, a two-finger tap is a right click, two fingers
  scroll, hold until it buzzes and then drag. Below the pad is a text field
  that types into the PC and a row of keys (Esc, Enter, arrows, Alt+Tab,
  Ctrl+C/V, Alt+F4). Moves and clicks share one TCP connection, so a click
  never overtakes the move before it. There is no password: it is meant for
  the home network, and windows running as administrator can't be controlled
  at all — Windows does not let a normal program click into them.
- **Home-screen widget** — the two sleep playlists, put the PC to sleep or shut
  it down (each behind a confirmation), and a volume strip. The strip is not a
  slider: `RemoteViews` has no `SeekBar`, and a drag across a widget belongs to
  the launcher. So it is a `ProgressBar` with twenty invisible tiles over it,
  each carrying its own "set volume to 5 / 10 / … / 100 %" — and each needing
  its own PendingIntent request code, because two PendingIntents that differ
  only in an extra are the same intent to Android.

**In Firefox**

- **A toolbar popup** — what is playing, a seek bar, volume, the sleep buttons
  and the playlist with a search that ignores diacritics.
- **Four toolbar buttons** ⏮ ⏯ ⏭ 🔇 that act on one click, with the current
  track in the tooltip; they turn grey when the player is not running. Firefox
  gives an extension exactly one toolbar button, so these are four tiny
  extensions built from one script. The main add-on keeps the state fresh and
  the buttons ask it, not the network.
- **Picks the right laptop** — Firefox can't hear the UDP beacon, so the add-on
  asks a short list of addresses at once and takes the one I picked last,
  otherwise the one that is playing, otherwise the first that answers.
- Signed by Mozilla as *unlisted*: it can be installed, but it is not listed
  anywhere.

**Both apps update themselves** from my NAS. The PC reads only a few hundred
bytes of `latest.json`, asks, then downloads the package, verifies its SHA-256,
replaces itself and restarts. `config.txt` and the sleep playlists are never
overwritten. `GET /health` tells which version runs on which laptop without
walking over to it.

## How the pieces talk

```
 Windows PC                                     Android phone
 ┌──────────────────────────────┐               ┌──────────────────────────┐
 │ PySide6 player (QMediaPlayer)│  UDP beacon   │ finds the player by      │
 │                              │ ────────────► │ itself, no IP typing     │
 │ ffmpeg → multicast stream    │  audio stream │ LibVLC plays the stream  │
 │                              │ ────────────► │                          │
 │ HTTP API :8765               │ ◄──────────── │ remote, widget, touchpad │
 │  /api/now-playing, playlist, │  commands     └──────────────────────────┘
 │  control, mouse; /health     │
 │                              │ ◄──────────── Firefox add-on + 4 buttons
 └──────────────────────────────┘
```

Everything goes through the one HTTP API. The Firefox add-on needed no change
in the player at all.

## The part I like most: album names

Downloaded albums arrive named every possible way —
``Dark Plague`2026`Masquerade by necroscum``, `Blind-Guardian-Somewhere-2026-GRP`.
Before unpacking, the folder is renamed to `Artist - Album - Year` in three
steps, each more expensive than the one before:

1. **Offline rules** (`nazvy.py`) — split on backticks, dashes, underscores,
   pull out the year, drop `[FLAC]`, `(WEB)` and release-group tags. If the
   result is unambiguous, done.
2. **The new-releases list** that is already on disk.
3. **Metal Archives** (`nazvy_ma.py`) — searched **only by band name**, from the
   longest possible name to the shortest; the album is then matched offline
   against the discography.

```
Blind-Guardian-Somewhere-2026-GRP
  -> band "Blind Guardian Somewhere"?  MA: nothing
  -> band "Blind Guardian"?            MA: discography
  -> an album whose words are all in the folder name? no -> keep original
```

**If nothing matches, the name stays as it came.** A wrongly guessed artist is
worse than the original mess — the mess can at least be read and fixed by hand.
Metal Archives also knows the proper spelling, so `Behemoth-I-Scvlptor` ends up
as `Behemoth - I, Scvlptor`.

## Two laptops, one list

The new releases are written to the NAS by a job on another machine, and I tick
off what I have heard — on either of two laptops. One shared file would have
the laptops overwrite each other, so there are two: the list (written only by
the job) and an **append-only** log of ticks, one JSON line per click. Two
writes at once have nothing to fight over, the last line about an album wins,
and a tick can be undone.

## Run

```
python -m pip install PySide6 mutagen requests
python app.pyw
```

Tests: `python -m pytest -q tests` (PC) and `./gradlew testDebugUnitTest` in
`android/`.

Lyrics translation uses the DeepL API. No key is included in this repository —
create your own free key at https://www.deepl.com/pro-api and put it in
`config.txt` as `DEEPL_API_KEY=...`. Without a key the player works, only the
translation is off.

The Firefox add-on: `firefox\zabal.ps1` packs unsigned `.xpi` files that can be
loaded through `about:debugging`. Signing needs your own addons.mozilla.org API
key; the details are in [firefox/README.md](firefox/README.md).

The UI is in Slovak. The original Slovak README, much longer and with every
setting explained, is in [README.sk.md](README.sk.md). Design notes from the
beginning are in [NAVRH_HUDBA_LAN.md](NAVRH_HUDBA_LAN.md).
