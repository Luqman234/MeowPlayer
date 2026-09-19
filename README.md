# MeowPlayer 🐱🎵

**MeowPlayer 0.12.0** is a lightweight, keyboard-first, aggressively cat-themed terminal music player for Linux and Termux.

Python and `curses` provide the interface, `mpv` handles playback, Mutagen reads music metadata, SQLite powers the persistent **Cat Catalog**, and Linux desktops can control the player through MPRIS / D-Bus.

```text
 /\_/\   ♫ MEOWPLAYER v0.12.0 — Purring
( ^.^ )
 > ♫ <

▶  Now Purring: Space Song — Beach House
00:42 ━━━━━━━∿──────────── 05:20

Meow Level: 70%   Pounce: ON (37 left)
Tail-Chase: OFF   Catnip: 4   Mood: Zoomies

Music Nest / Songs — 842 meow(s)
★ Space Song — Beach House · Depression Cherry · Dream Pop · 05:20
```

## Highlights

- Full-screen terminal UI with keyboard-first controls
- Recursive local music-library scanning
- MP3, FLAC, OGG, Opus, WAV, M4A, AAC, and WMA discovery
- Metadata for title, artist, album, album artist, track number, year, **genre**, and **duration**
- Persistent SQLite **Cat Catalog**
- Incremental metadata caching for fast warm startups
- Automatic invalidation for modified files and pruning for deleted files
- Songs, Artists, Albums, Folders/Nests, Pawmarks, Purr History, and **Smart Mixes** views
- Dynamic Smart Mixes for favorites, recent plays, most-played tracks, fresh additions, unplayed tracks, and every detected genre
- Artist → album → track drill-down navigation
- Album → track drill-down navigation
- Unicode **Scent Search**, including Japanese input and NFKC normalization
- Persistent **Pawmarks** favorites
- Persistent play counts and listening history
- Real queueing through **The Catnip Stash**
- Save/load Catnip Stash playlists as `.m3u` / `.m3u8`
- Persistent no-repeat **Pounce Bag** shuffle
- Persistent Previous-history with shuffle-aware back/forward behavior
- Tail-Chase repeat
- Automatic next-track playback
- **Gapless playback** with one-track-ahead mpv playlist priming
- Native **ReplayGain** loudness normalization through mpv
- Synchronized **LRC lyrics** plus embedded/plain lyrics support
- Dedicated live-follow **Songbook** lyrics view
- Optional **CAVA spectrum visualizer** with raw FFT bar integration
- Persistent session state and paused resume
- Linux MPRIS / D-Bus integration
- `playerctl`, desktop media keys, and MPRIS-aware widget support
- Native Termux defaults and a narrower phone-friendly layout
- **Album art in supported Kitty terminals**, using embedded artwork or common folder-cover files
- Album-art cache plus MPRIS `mpris:artUrl` exposure for desktop integrations
- Reactive cat moods, rotating cat quotes, paw markers, and Maximum Meow mode
- Proper Python packaging with `pyproject.toml`
- Package smoke tests and unit tests through GitHub Actions

## Quick start

### Arch Linux

Install the system runtime dependency and `pipx`:

```bash
sudo pacman -S mpv python-pipx
pipx ensurepath

# Optional: live spectrum visualizer
sudo pacman -S cava
```

Clone and install MeowPlayer:

```bash
git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
pipx install .
```

Then launch it from anywhere:

```bash
meowplayer
```

Useful examples:

```bash
meowplayer ~/Music
meowplayer --maximum-meow
meowplayer --serious-mode
meowplayer --no-mpris
meowplayer --no-restore
meowplayer --rebuild-catalog
meowplayer --no-album-art
meowplayer --gapless-mode weak
meowplayer --replaygain track
meowplayer --replaygain album --replaygain-preamp -1.0
meowplayer --no-lyrics
meowplayer --no-visualizer
meowplayer --version
```

To update an existing local `pipx` installation:

```bash
cd MeowPlayer
git pull
pipx reinstall meowplayer-terminal
```

### Debian / Ubuntu

Install the system runtime dependency:

```bash
sudo apt install python3 mpv
```

Then install from the repository:

```bash
git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
python3 -m pip install .
```

### Termux / Android

Install the runtime packages:

```bash
pkg update
pkg install python python-pip mpv git
```

Grant access to Android shared storage:

```bash
termux-setup-storage
```

Then:

```bash
cd ~
git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
python -m pip install .
meowplayer
```

MeowPlayer detects Termux automatically. With no explicit music directory it prefers:

```text
~/storage/music
/storage/emulated/0/Music
~/Music
```

Keep the MeowPlayer repository itself in Termux's private home directory. Shared storage is appropriate for music files, but not ideal for executable project files.

MPRIS is intentionally disabled on Termux because a normal Linux desktop D-Bus session is usually unavailable there.

## Requirements

- Python **3.10+**
- `mpv`
- Mutagen
- `dbus-next` for Linux MPRIS integration
- Pillow for album-art normalization and caching
- CAVA *(optional)* for the live audio spectrum visualizer
- A terminal with curses support
- Unix-domain socket support

Python dependencies are declared in `pyproject.toml` and installed automatically when using `pip` or `pipx`.

If Mutagen cannot be imported, MeowPlayer can still fall back to filenames/folders for newly scanned music, but rich tags such as artist, album, year, genre, and cached duration will be unavailable for those files.

## Music library views

Press the corresponding key from the Music Nest:

| Key | View |
| --- | --- |
| `1` | Songs |
| `2` | Artists |
| `3` | Albums |
| `4` | Folders / Nests |
| `5` | Pawmarks |
| `6` | Purr History |
| `7` | Smart Mixes |
| `Tab` | Cycle views |

### Songs

A flat metadata-aware track list.

```text
★ Space Song — Beach House · Depression Cherry · Dream Pop · 05:20
  Nude — Radiohead · In Rainbows · Art Rock · 04:15
```

### Artists

Artists are navigable rather than decorative group headers.

```text
Music Nest / Artists

>^.^< Radiohead · 42 track(s) ›
      YOASOBI · 18 track(s) ›
      宇多田ヒカル · 27 track(s) ›
```

Press `Enter`:

```text
Music Nest / Artists / Radiohead

>^.^< In Rainbows (2007) · 10 track(s) ›
      Kid A (2000) · 10 track(s) ›
      OK Computer (1997) · 12 track(s) ›
```

Press `Enter` again:

```text
Music Nest / Artists / Radiohead / In Rainbows

>^.^< 01. 15 Step — Radiohead · 03:57
      02. Bodysnatchers — Radiohead · 04:02
      03. Nude — Radiohead · 04:15
```

Use `B` or `Backspace` to move up one level.

### Albums

Album view opens directly into the selected album's track list.

```text
Music Nest / Albums

>^.^< In Rainbows — Radiohead (2007) · 10 track(s) ›
      Kid A — Radiohead (2000) · 10 track(s) ›
```

### Folders / Nests

Groups tracks by their physical directory under the selected music root.

### Pawmarks

Press `F` on an individual track to toggle its persistent favorite state.

```text
★ Nude — Radiohead · In Rainbows · Art Rock · 04:15
```

View `5` shows only Pawmarked tracks.

### Purr History

Every deliberate track start records:

```text
play_count += 1
last_played = now
history event = now
```

Session restoration and simply resuming the current track do not create fake listens.

View `6` is ordered by most recently played:

```text
Nude — Radiohead · played 14× · 04:15
夜に駆ける — YOASOBI · played 9× · 04:21
Space Song — Beach House · played 6× · 05:20
```

## Smart Mixes

Press `7` to open **Smart Mixes**.

Unlike ordinary saved playlists, Smart Mixes are generated from the current Cat Catalog every time they are opened.

Built-in mixes include:

```text
Pawmarked Mix
Recently Purrred
Most Purrred
Fresh Finds
Never Purrred
Genre Mix · Dream Pop
Genre Mix · Rock
Genre Mix · ...
```

Genre mixes are dynamic: if your library contains a genre tag, MeowPlayer creates a mix for it automatically.

```text
Music Nest / Smart Mixes

>^.^< Pawmarked Mix · 31 track(s) ›
      Recently Purrred · 126 track(s) ›
      Most Purrred · 91 track(s) ›
      Fresh Finds · 100 track(s) ›
      Never Purrred · 403 track(s) ›
      Genre Mix · Dream Pop · 47 track(s) ›
```

Press `Enter` to open a mix, then `Enter` on a track to play it.

Smart Mixes are real playback sequences:

```text
Next
  ↓
next track in the active Smart Mix

Pounce Mode
  ↓
Pounce Bag contains only tracks in that Smart Mix
```

The active playback sequence is persisted in runtime state, so restarting MeowPlayer does not silently turn a Smart Mix back into the full library.

Use `B` or `Backspace` to return to the Smart Mix list.

## Scent Search

Press `/` in the Music Nest.

Search checks:

- title
- artist
- album
- album artist
- year
- genre
- filename
- folder/path

For example:

```text
SCENT SEARCH > dream pop_       (18 meows)
SCENT SEARCH > 宇多田ヒカル_     (8 meows)
SCENT SEARCH > 夜に駆ける_       (1 meow)
```

Search accepts full Unicode input through `curses.get_wch()` and normalizes text with Unicode NFKC + case folding.

Controls while searching:

| Key | Action |
| --- | --- |
| Type | Refine the scent |
| `Backspace` | Delete a character |
| `Enter` | Keep the current filter |
| `Esc` | Clear the filter |

## The Cat Catalog

The **Cat Catalog** is MeowPlayer's persistent SQLite library database.

Default location:

```text
~/.local/share/meowplayer/library.sqlite3
```

If `XDG_DATA_HOME` is set, MeowPlayer uses that instead.

It stores both cacheable metadata and MeowPlayer-specific library data:

```text
path
library root
size
mtime
title
artist
album
album artist
track number
year
genre
duration
folder
filename
tagged/fallback status

Pawmark
play count
last played
added-at time
individual listening-history events
```

### Incremental metadata caching

First scan:

```text
music file
   ↓
Mutagen reads tags + duration
   ↓
Cat Catalog stores metadata
```

Warm scan:

```text
path + size + mtime
        ↓
   unchanged?
   /       \
 yes       no
  ↓         ↓
SQLite    Mutagen
 cache    re-sniff
```

A normal warm launch may report:

```text
Cat Catalog checked: 842 remembered, 3 re-sniffed, 1 vanished; 821/844 tagged meow(s).
```

### Rebuild metadata

If tags were changed externally or you suspect stale metadata:

```bash
meowplayer --rebuild-catalog
```

This forces metadata refresh for the current music root while preserving:

- Pawmarks
- play counts
- last-played values
- listening history

It does **not** modify the music files.

Do not treat `library.sqlite3` as disposable cache. Deleting it leaves your audio files untouched, but erases MeowPlayer-specific Pawmarks and history.

### Upgrading from older Cat Catalog versions

MeowPlayer 0.8.0 moved the catalog from:

```text
~/.cache/meowplayer/library.sqlite3
```

to:

```text
~/.local/share/meowplayer/library.sqlite3
```

The old database is migrated automatically.

MeowPlayer 0.9.0 added genre and duration to the catalog schema. Existing Pawmarks and listening history were preserved, but cached tracks were deliberately re-sniffed once so those fields could be populated. Later launches return to normal incremental caching.

## Lyrics / Songbook

MeowPlayer 0.12.0 adds a dedicated lyrics system.

Press `L` at any time to open the **Songbook**.

Lyrics are resolved in this order:

```text
same-name .lrc sidecar
        ↓
embedded synchronized lyrics
        ↓
same-name .txt sidecar
        ↓
embedded plain lyrics
```

For example:

```text
Music/
└── Album/
    ├── 01 Song.flac
    └── 01 Song.lrc
```

A synchronized `.lrc` file can look like:

```text
[00:12.40]First line
[00:17.85]Second line
[00:22.10]Third line
```

Multiple timestamps on one line and standard `[offset:+/-milliseconds]` tags are supported.

When synchronized lyrics are available, MeowPlayer also shows the current lyric directly in the normal player:

```text
♫ And this is the line being sung right now
```

Inside the Songbook:

| Key | Action |
| --- | --- |
| `L` | Open / close lyrics |
| `↑` / `↓` | Temporarily scroll manually |
| `Enter` | Resume live timestamp following |
| `N` / `P` | Next / previous track |
| `Space` | Pause / resume |

The currently active synchronized line is highlighted and automatically centered while follow mode is active.

Plain lyrics from `.txt` files or unsynchronized embedded tags are displayed as a normal scrollable text view.

Disable lyric loading for one launch with:

```bash
meowplayer --no-lyrics
```

The persistent config supports:

```json
"lyrics_enabled": true
```

## Audio visualizer

MeowPlayer 0.12.0 can embed a real frequency spectrum in the TUI using **CAVA**.

CAVA is optional. If it is missing, MeowPlayer continues normally with no visualizer.

On Arch Linux:

```bash
sudo pacman -S cava
```

When available, MeowPlayer starts CAVA in raw ASCII mode and consumes its FFT bar values instead of letting CAVA draw its own terminal interface.

The spectrum appears directly beneath the playback progress bar:

```text
▁▂▄▆█▇▅▃▂▁▂▅▇█▆▄▂▁
```

Press `V` to toggle it at runtime.

The generated CAVA configuration uses the default audio monitor source when available, so the visualizer observes the system output path rather than decoding the music file again inside Python.

Disable it for one launch with:

```bash
meowplayer --no-visualizer
```

Persistent config:

```json
"visualizer_enabled": true
```

Because the default sink monitor can contain audio from other applications, the displayed spectrum may react to other system audio playing at the same time.

## Album art

MeowPlayer 0.11.0 can display real album artwork directly inside **Kitty terminals** using Kitty's terminal graphics protocol.

Album art is enabled automatically when:

- MeowPlayer is running directly in Kitty / `xterm-kitty`
- the terminal is large enough to preserve the TUI layout
- Pillow is available
- a cover can be resolved
- MeowPlayer is not inside tmux
- `--no-album-art` was not supplied

The cover is rendered in the upper-right portion of the player while the normal curses UI remains usable.

MeowPlayer looks for art in this order:

1. embedded artwork in the audio file
2. common cover files beside the track

Embedded artwork support covers common MP3/FLAC/MP4/Vorbis-style metadata. Folder artwork matching is case-insensitive and recognizes names such as:

```text
cover.jpg
cover.png
cover.webp
folder.jpg
folder.png
front.jpg
front.png
album.jpg
album.png
```

Artwork is converted to PNG and cached at:

```text
~/.cache/meowplayer/album-art/
```

or the equivalent `XDG_CACHE_HOME` path. Audio files are never modified.

Disable terminal artwork for one launch with:

```bash
meowplayer --no-album-art
```

The persistent config also supports:

```json
"album_art_enabled": true
```

If the terminal is unsupported, the window is too small, or no cover exists, MeowPlayer simply falls back to the normal text UI.

Resolved covers are also exported over MPRIS as `mpris:artUrl`, allowing compatible desktop widgets and media controls to reuse the same cached image.

## Gapless playback and ReplayGain

MeowPlayer 0.11.0 upgrades the audio engine in two places.

### Gapless playback

MeowPlayer no longer waits for a song to reach EOF before deciding what comes next.

While a track is playing, it resolves the next track using the same playback priority as the rest of the app:

```text
Catnip Stash
      ↓
Pounce Bag
      ↓
active Smart Mix
      ↓
normal sequential library
```

That next track is inserted into mpv's internal playlist **before the current track ends**:

```text
current decoder
      │
      ├──────────────┐
      ▼              ▼
 Track A          Track B already primed
      │              │
      └──── boundary ┘
             ↓
       mpv advances
             ↓
MeowPlayer commits queue/history state
             ↓
       Track C is primed
```

This lets mpv keep its audio output alive across compatible files instead of MeowPlayer tearing down one file and loading the next only after EOF.

The default is:

```json
"gapless_mode": "weak"
```

Available modes:

| Mode | Behavior |
| --- | --- |
| `weak` | Default. Keeps the audio device open when mpv can safely reuse the output format; may reopen it when formats differ. |
| `yes` | Strongest gapless behavior. Keeps the first output format for later tracks, which may require resampling. |
| `no` | Disables MeowPlayer's gapless preload and mpv gapless output mode. |

Override it for one launch:

```bash
meowplayer --gapless-mode weak
meowplayer --gapless-mode yes
meowplayer --gapless-mode no
```

Queue edits, Pounce Mode changes, Tail-Chase changes, and Smart Mix playback all re-prime the upcoming file so the internal mpv playlist remains consistent with MeowPlayer's own Next logic.

### ReplayGain

ReplayGain uses gain values already stored in the audio file's metadata. MeowPlayer delegates the actual gain calculation and clipping protection to mpv.

The default mode is:

```json
"replaygain_mode": "track"
```

Modes:

| Mode | Behavior |
| --- | --- |
| `track` | Normalize each track independently. Good for shuffled libraries and mixed playlists. |
| `album` | Prefer album gain for preserving intended loudness relationships within an album; falls back to track gain when album gain is unavailable. |
| `no` | Disable ReplayGain adjustment. |

MeowPlayer also defaults to:

```json
"replaygain_preamp": 0.0
```

and starts mpv with clipping protection enabled:

```text
--replaygain-clip=no
```

Examples:

```bash
meowplayer --replaygain track
meowplayer --replaygain album
meowplayer --replaygain no
meowplayer --replaygain track --replaygain-preamp -1.5
```

ReplayGain only changes loudness when the file contains usable ReplayGain metadata. Files without those tags remain effectively unadjusted with the default preamp.

## Pounce Bag shuffle

Pounce Mode is not independent `random.choice()` selection anymore.

It uses a real no-repeat **Pounce Bag**:

```text
all tracks except current
          ↓
      shuffle once
          ↓
     Pounce Bag
          ↓
  consume one by one
          ↓
        empty?
          ↓
refill excluding current
```

Every eligible track gets one turn before a new shuffle cycle starts.

The UI shows the remaining bag:

```text
Pounce: ON (37 left)
```

The exact next song stays a mystery:

```text
Next Treat: mystery meow (37 left in Pounce Bag)
```

The bag is persisted in the state file, so restarting MeowPlayer does not reset the shuffle cycle.

Playback Previous-history is also persistent. In Pounce Mode:

```text
A → B → C → D

Previous
   ↓
   C

Previous
   ↓
   B

Next
 ↓
 C
```

When going backward, the track you leave is placed at the top of the Pounce Bag so forward navigation remains natural.

The Catnip Stash always has priority over the Pounce Bag.

## The Catnip Stash

The queue is officially called **The Catnip Stash**.

From a leaf-level track, press `A` to stash it.

Press `Q` to switch between the Music Nest and Catnip Stash.

Queue playback has priority:

```text
Catnip Stash
     ↓
Pounce Bag / sequential library
```

Inside the stash:

| Key | Action |
| --- | --- |
| `↑` / `↓` | Select queued track |
| `Enter` | Play and consume selected item |
| `D` | Remove |
| `K` | Move up |
| `J` | Move down |
| `C` | Clear stash |
| `W` | Save as `.m3u` |
| `O` | Load `.m3u` / `.m3u8` |
| `Q` | Return to Music Nest |

The default playlist path is:

```text
<current music root>/catnip-stash.m3u
```

Loaded playlist entries must resolve to tracks already indexed in the current library.

## Main controls

| Key | Action |
| --- | --- |
| `↑` / `↓` | Choose |
| `Enter` | Open artist/album group or play track |
| `1`–`7` | Select library view |
| `Tab` | Cycle library view |
| `B` / `Backspace` | Go up one drill-down level |
| `/` | Scent Search |
| `F` | Toggle Pawmark |
| `A` | Add track to Catnip Stash |
| `Q` | Toggle Music Nest / Catnip Stash |
| `L` | Toggle Songbook / lyrics view |
| `V` | Toggle live spectrum visualizer |
| `Space` | Paws / resume |
| `←` / `→` | Scritch backward / forward 5 seconds |
| `N` | Next meow |
| `P` | Previous purr |
| `+` / `-` | Adjust Meow Level |
| `S` | Toggle Pounce Mode |
| `R` | Toggle Tail-Chase |
| `X` | Quit |

## Persistent config and state

MeowPlayer follows the XDG base-directory layout.

### Config

```text
~/.config/meowplayer/config.json
```

Example:

```json
{
  "album_art_enabled": true,
  "gapless_mode": "weak",
  "lyrics_enabled": true,
  "mpris_enabled": true,
  "music_dir": "/home/you/Music",
  "replaygain_mode": "track",
  "replaygain_preamp": 0.0,
  "restore_session": true,
  "visualizer_enabled": true
}
```

### Runtime state

```text
~/.local/state/meowplayer/state.json
```

It remembers:

- volume
- Pounce Mode
- Tail-Chase
- current library view
- last track
- playback position
- Catnip Stash
- remaining Pounce Bag
- Previous-history
- active Smart Mix playback sequence

State is written periodically and again during shutdown.

Session restore loads the last track at the saved position **paused**. Opening MeowPlayer never intentionally blasts yesterday's track immediately.

## MPRIS and media keys

On Linux desktops, MeowPlayer exposes:

```text
org.mpris.MediaPlayer2.meowplayer
```

Supported controls include:

- Play / Pause / PlayPause
- Next / Previous
- Stop
- relative and absolute seek
- volume
- Shuffle / Pounce Mode
- LoopStatus / Tail-Chase
- remote Quit

MPRIS metadata includes:

- title
- artist
- album
- album artist
- genre
- file URI
- duration
- album-art URL when available

Test with `playerctl`:

```bash
sudo pacman -S playerctl

playerctl -l
playerctl --player=meowplayer status
playerctl --player=meowplayer metadata
playerctl --player=meowplayer play-pause
playerctl --player=meowplayer next
playerctl --player=meowplayer previous
```

If `playerctl` says no players were found:

```bash
python -c 'import dbus_next; print("dbus-next: OK")'
busctl --user list >/dev/null && echo "user D-Bus: OK"
busctl --user list | grep org.mpris.MediaPlayer2.meowplayer
```

MeowPlayer stays usable if MPRIS registration fails and displays the startup error in its status line.

## Cat modes

### Normal mode

```bash
meowplayer
```

### Serious Mode

```bash
meowplayer --serious-mode
```

Uses conventional labels and removes most feline presentation.

### Maximum Meow

```bash
meowplayer --maximum-meow
```

For situations where the existing quantity of cat is scientifically insufficient.

The two modes are mutually exclusive.

## Cat moods

The mascot reacts to player state:

| State | Mood |
| --- | --- |
| Nothing playing | Waiting |
| Normal playback | Purring |
| Paused | Loafing |
| Pounce Mode | Zoomies |
| Tail-Chase | Tail-Chasing |
| Catnip queued | Guarding Catnip |

```text
 /\_/\   ♫ MEOWPLAYER v0.12.0 — Loafing
( -.- )
 > ^ <  ...
```

## Feline vocabulary

| Conventional | MeowPlayer |
| --- | --- |
| Library | Music Nest |
| Folders | Nests |
| Search | Scent Search |
| Queue | The Catnip Stash |
| Favorites | Pawmarks |
| Listening history | Purr History |
| Smart playlists | Smart Mixes |
| Lyrics | Songbook |
| Audio visualizer | Spectrum |
| Now Playing | Now Purring |
| Volume | Meow Level |
| Shuffle | Pounce Mode |
| Shuffle pool | Pounce Bag |
| Repeat | Tail-Chase |
| Pause | Paws |
| Seek | Scritch |
| Save playlist | Bury stash |
| Load playlist | Dig up stash |

## Architecture

```text
                     Music files
                         │
                    recursive scan
                         │
                         ▼
                ┌─────────────────┐
                │   Cat Catalog   │
                │     SQLite      │
                ├─────────────────┤
                │ cached metadata │
                │ genre/duration  │
                │ Pawmarks        │
                │ Purr History    │
                │ Smart Mix data  │
                └────────┬────────┘
                         │
            ┌────────────┼─────────────┐
            ▼            ▼             ▼
         Artists       Albums       Smart Mixes
            │            │             │
            └────────────┼─────────────┘
                         ▼
                    Scent Search
                         │
                         ▼
                    Music Nest
                   │
            ┌──────┴────────┐
            ▼               ▼
      Catnip Stash      Pounce Bag
            └──────┬────────┘
                   ▼
             MeowPlayer TUI
              │         │
              │         ├── Lyrics / Songbook
              │         └── CAVA raw spectrum
              │
             mpv JSON IPC
                   │
             next-track priming
                   │
                   ▼
                  mpv
          gapless + ReplayGain
                   │
                   ▼
              audio output

                   ↕
              MPRIS / D-Bus
                   ↕
         playerctl / media keys
```

Python owns the interface, library model, Smart Mix generation, lyrics synchronization, spectrum rendering, search, persistence, queueing, shuffle logic, one-track-ahead gapless scheduling, album-art resolution, and cat-related responsibilities. Mutagen reads metadata, embedded artwork, and stream duration. SQLite stores the persistent library model. Pillow normalizes artwork into cached PNG files. `mpv` handles decoding, ReplayGain, audio output, and the actual gapless handoff between primed playlist entries.

## Build packages

Install the build frontend:

```bash
python -m pip install build
```

Build wheel + source distribution:

```bash
python -m build
```

Output:

```text
dist/
├── meowplayer_terminal-0.12.0-py3-none-any.whl
└── meowplayer_terminal-0.12.0.tar.gz
```

The installed CLI is still:

```text
meowplayer
```

## Project structure

```text
MeowPlayer/
├── meowplayer.py
├── album_art.py
├── lyrics_support.py
├── meow_catalog.py
├── meow_smart.py
├── meow_persistence.py
├── mpris_support.py
├── visualizer.py
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE
├── tests/
│   ├── test_album_art.py
│   ├── test_audio.py
│   ├── test_catalog.py
│   ├── test_lyrics.py
│   ├── test_shuffle.py
│   ├── test_smart.py
│   └── test_visualizer.py
└── .github/
    └── workflows/
        └── package-smoke.yml
```

## Development and tests

Compile the modules:

```bash
python -m py_compile meowplayer.py album_art.py lyrics_support.py meow_catalog.py meow_smart.py meow_persistence.py mpris_support.py visualizer.py
```

Run tests:

```bash
python -m unittest discover -s tests -v
```

Build-test the package:

```bash
python -m build
```

The GitHub Actions package-smoke workflow automatically checks relevant pushes and pull requests by:

```text
compile Python modules
        ↓
run unit tests
        ↓
build wheel + source distribution
        ↓
install wheel in a clean venv
        ↓
meowplayer --version
meowplayer --help
```

## Roadmap

Potential next upgrades:

- additional terminal graphics protocols beyond Kitty
- user-defined Smart Mix rules
- per-track lyric timing offsets and lyric editing
- additional visualizer backends / dedicated per-player capture
- ReplayGain tag inspection / loudness diagnostics
- broader gapless stress testing across mixed sample rates and codecs
- release automation and tagged GitHub releases
- Arch `PKGBUILD` / AUR packaging
- additional scientifically unnecessary cat behavior

## License

MeowPlayer is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE).

## Why "MeowPlayer"?

Because every respectable terminal deserves at least one cat-themed application.

```text
 /\_/\
( o.o )
 > ^ <
```

And because apparently naming it MeowPlayer was not enough. We had to commit to the bit.
