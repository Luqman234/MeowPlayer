# MeowPlayer 🐱🎵

A lightweight, aggressively cat-themed terminal music player written in Python, with `mpv` handling audio playback and `curses` providing the terminal UI.

MeowPlayer recursively scans a music directory, reads audio metadata, lets you browse by songs/artists/albums/folders, search the library live, build a real playback queue called **The Catnip Stash**, and control everything from the keyboard.

```text
 /\_/\   ♫ MEOWPLAYER — terminal purr engine
( o.o )
 > ^ <

Now Purring: Space Song.flac
00:42 ━━━━━━━∿──────────── 03:28

Meow Level: 70%   Pounce: OFF   Tail-Chase: ON   Catnip: 4

Music Nest — scent: 'space' (2 meows)
```

## Features

- Full-screen terminal interface
- Recursive music-folder scanning
- Metadata parsing for title, artist, album, album artist, track number, and year
- Filename/folder fallbacks for untagged or malformed audio files
- Grouped library views for Songs, Artists, Albums, and Folders
- Live search/filtering across metadata, filenames, and folder paths
- **The Catnip Stash** queue
- Queue-first playback: stashed tracks play before normal library playback
- Reorder and remove queued tracks
- Save the stash as an `.m3u` playlist
- Load `.m3u` / `.m3u8` playlists back into the stash
- Previous-track history
- Persistent XDG config and playback state
- Restores volume, shuffle, repeat, library view, last track, and position
- MPRIS D-Bus integration for desktop media controls
- Playerctl, Waybar, and media-key friendly transport controls
- Cat mascot in the header
- Cat-themed startup splash
- Random rotating cat quotes
- Cat-flavored status messages
- Animated tail progress marker
- Pawprint marker for the currently playing track
- Play and paws
- Previous purr and next meow
- Seek forward and backward
- Meow Level volume control
- Pounce Mode shuffle
- Tail-Chase repeat
- Playback progress and duration display
- Automatic playback of the next track
- Serious mode for people who temporarily require professionalism
- Maximum Meow mode for people who absolutely do not
- Uses `mpv` as the audio backend

### Supported formats

MeowPlayer currently scans for:

- MP3
- FLAC
- OGG
- Opus
- WAV
- M4A
- AAC
- WMA

## Requirements

- Python 3
- `mpv`
- [Mutagen](https://mutagen.readthedocs.io/) for audio metadata parsing
- `dbus-next` for optional Linux MPRIS integration
- A terminal with curses support
- Linux, or Termux on Android
- Unix domain socket support

If Mutagen is unavailable, MeowPlayer still runs using filename/folder fallbacks, but tag-based artist/album/year data will not be available.

### Arch Linux

```bash
sudo pacman -S python mpv python-mutagen python-dbus-next
```

### Debian / Ubuntu

```bash
sudo apt install python3 mpv python3-mutagen python3-dbus-next
```

### Termux / Android

MeowPlayer has first-class Termux support.

Install the runtime packages:

```bash
pkg update
pkg install python python-pip mpv git
```

Grant Termux access to Android shared storage:

```bash
termux-setup-storage
```

After permission is granted, Android's normal Music directory is typically exposed to Termux as:

```text
~/storage/music
```

MeowPlayer detects Termux automatically. If no music directory is supplied, it prefers `~/storage/music`, then `/storage/emulated/0/Music`, and finally `~/Music`.

Keep the **MeowPlayer repository itself inside Termux's private home directory**, such as `~/MeowPlayer`. Shared Android storage is fine for the music library, but it does not behave like a normal Unix filesystem and is not a good location for executable project files.

Example setup:

```bash
cd ~
git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
python -m pip install -r requirements.txt
termux-setup-storage
python meowplayer.py
```

The Termux build of `mpv` is configured for Android audio output, so MeowPlayer continues to use the same mpv backend as on desktop Linux.

Persistent config/state works normally in Termux. MPRIS is intentionally disabled there because a standard Linux desktop D-Bus session is normally not present.

For smaller phone displays, MeowPlayer lowers its minimum supported width from 46 columns to 32 columns when Termux is detected. Long labels and footer hints are truncated automatically rather than preventing the player from opening.

## Installation

Clone the repository:

```bash
git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
```

Optionally make the script executable:

```bash
chmod +x meowplayer.py
```

## Usage

By default, MeowPlayer scans `~/Music` on desktop Linux. In Termux it automatically prefers Android's shared `~/storage/music` directory:

```bash
./meowplayer.py
```

or:

```bash
python3 meowplayer.py
```

To use another music directory, pass it as the first argument:

```bash
./meowplayer.py ~/Downloads/Music
```

The directory is scanned recursively, so music inside subdirectories is included automatically.

On Termux, you can still override the Android music directory explicitly:

```bash
python meowplayer.py ~/storage/downloads/Music
```

If MeowPlayer detects Termux but cannot find shared music storage, it prints a Termux-specific hint telling you to run `termux-setup-storage`.

## Metadata and library views

MeowPlayer uses **Mutagen** to read tags from supported audio files. It currently looks for:

- title
- artist
- album
- album artist
- track number
- year/date

When tags are missing or unreadable, MeowPlayer falls back safely to the filename, folder, and `Unknown Artist` / `Unknown Album` placeholders.

The current song display and The Catnip Stash use parsed metadata instead of raw filenames whenever tags are available.

### Switching views

While in the Music Nest:

| Key | Library view |
| --- | --- |
| `1` | Songs |
| `2` | Artists |
| `3` | Albums |
| `4` | Folders / Nests |
| `Tab` | Cycle to the next view |

**Songs** is a flat metadata-aware track list.

**Artists** groups tracks under artist headers.

**Albums** groups tracks by album and album artist, respects track numbers when available, and shows the album year when tagged.

**Folders / Nests** groups files by their physical directory inside the music library.

Example:

```text
Music Nest / Albums — 128 meows

▾ In Rainbows — Radiohead (2007)
   01. 15 Step — Radiohead
>^.^< 02. Bodysnatchers — Radiohead
   03. Nude — Radiohead

▾ Unknown Album
   loose-recording.mp3
```

## Search: Scent Search

Press `/` while viewing the library to start searching.

As you type, MeowPlayer filters the library immediately. Search now checks parsed **title, artist, album, album artist, year, filename, and folder path**, so a query can match either tags or where the file lives.

Scent Search accepts full Unicode input, including Japanese kana and kanji. It also applies Unicode NFKC normalization before matching, which makes compatibility variants such as half-width/full-width forms behave more consistently.

```text
SCENT SEARCH > 宇多田ヒカル_   (8 meows)
SCENT SEARCH > 夜に駆ける_     (1 meow)
SCENT SEARCH > 東京_           (4 meows)
```

Japanese input uses your terminal's normal input method/IME; MeowPlayer reads the resulting wide characters directly through `curses`.

- Type normally to refine the search.
- `Backspace` deletes characters.
- `Enter` keeps the current filter and leaves typing mode.
- `Esc` clears the search completely.
- Press `Esc` later while a filter is active to return to the full library.

## The Catnip Stash

The queue is officially called **The Catnip Stash** because dignity was never a project requirement.

From the library, highlight a song and press:

```text
A
```

to stash it.

Press:

```text
Q
```

to switch between the Music Nest and The Catnip Stash.

The stash behaves as a real **up-next queue**. When a track ends — or when you press `N` — queued tracks are consumed from the top of the stash before MeowPlayer returns to normal sequential or shuffled library playback.

Inside The Catnip Stash:

| Key | Action |
| --- | --- |
| `↑` / `↓` | Choose a queued track |
| `Enter` | Play and consume selected stash item now |
| `D` | Remove selected item |
| `K` | Move selected item up |
| `J` | Move selected item down |
| `C` | Clear the entire stash |
| `W` | Save stash as an `.m3u` playlist |
| `O` | Load an `.m3u` / `.m3u8` playlist |
| `Q` | Return to the Music Nest |

The default playlist path is:

```text
~/Music/catnip-stash.m3u
```

or the equivalent path inside whichever music directory you launched MeowPlayer with. You can type another path when prompted.

Loaded playlist entries must point to songs that are already inside the current MeowPlayer library. Entries that cannot be found are skipped and reported.

## Main controls

| Key | MeowPlayer action |
| --- | --- |
| `↑` / `↓` | Choose a track |
| `Enter` | Play selected track |
| `1` / `2` / `3` / `4` | Songs / Artists / Albums / Folders view |
| `Tab` | Cycle library view |
| `/` | Start Scent Search |
| `A` | Add selected track to The Catnip Stash |
| `Q` | Toggle Music Nest / Catnip Stash |
| `Space` | Paws / resume |
| `←` / `→` | Scritch backward / forward 5 seconds |
| `N` | Next meow; consumes stash first |
| `P` | Previous purr |
| `+` / `-` | Raise / lower Meow Level |
| `S` | Toggle Pounce Mode (shuffle) |
| `R` | Toggle Tail-Chase (repeat) |
| `X` | Escape before the cat notices |

> `Q` now opens The Catnip Stash, so quitting moved to `X`.

## Persistent config and state

MeowPlayer now follows the XDG base-directory layout.

By default:

```text
~/.config/meowplayer/config.json
~/.local/state/meowplayer/state.json
```

If `XDG_CONFIG_HOME` or `XDG_STATE_HOME` is set, MeowPlayer uses those locations instead.

The config file is user-editable and currently stores:

```json
{
  "mpris_enabled": true,
  "music_dir": "/home/you/Music",
  "restore_session": true
}
```

The state file is managed automatically and remembers:

- Meow Level / volume
- Pounce Mode / shuffle
- Tail-Chase / repeat
- current Songs / Artists / Albums / Nests view
- last track
- last playback position
- The Catnip Stash queue

State is written periodically and again on shutdown.

When session restore is enabled, MeowPlayer loads the previous track at its saved position **paused**. It never auto-blasts audio just because the program was opened.

You can bypass either feature for one launch:

```bash
python meowplayer.py --no-restore
python meowplayer.py --no-mpris
```

## MPRIS and media keys

On Linux desktops, MeowPlayer exports the standard MPRIS service:

```text
org.mpris.MediaPlayer2.meowplayer
```

MPRIS exposes:

- Play / Pause / PlayPause
- Next / Previous
- Stop
- seek and absolute position
- current title / artist / album metadata
- playback position and duration
- volume
- Pounce Mode as MPRIS Shuffle
- Tail-Chase as MPRIS LoopStatus
- remote Quit

This makes MeowPlayer visible to MPRIS-aware desktop components and tools.

### Test it with playerctl

On Arch:

```bash
sudo pacman -S playerctl
```

Then, while MeowPlayer is running:

```bash
playerctl --player=meowplayer status
playerctl --player=meowplayer metadata
playerctl --player=meowplayer play-pause
playerctl --player=meowplayer next
playerctl --player=meowplayer previous
```

### Hyprland media-key example

If your compositor does not bind hardware media keys automatically, route them through `playerctl`.

Current Hyprland Lua-style configuration:

```lua
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl --player=meowplayer play-pause"), { locked = true })
hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl --player=meowplayer next"), { locked = true })
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl --player=meowplayer previous"), { locked = true })
hl.bind("XF86AudioStop", hl.dsp.exec_cmd("playerctl --player=meowplayer stop"), { locked = true })
```

On older Hyprland releases using hyprlang syntax:

```ini
bindl = , XF86AudioPlay, exec, playerctl --player=meowplayer play-pause
bindl = , XF86AudioNext, exec, playerctl --player=meowplayer next
bindl = , XF86AudioPrev, exec, playerctl --player=meowplayer previous
bindl = , XF86AudioStop, exec, playerctl --player=meowplayer stop
```

That means your keyboard's Play/Pause, Next, Previous, and Stop keys can control MeowPlayer even when its terminal is not focused.

MPRIS requires a user D-Bus session plus the Python `dbus-next` package. If either is missing, MeowPlayer simply runs without MPRIS rather than failing to start.

## Cat modes

Normal mode is already cat-themed:

```bash
./meowplayer.py
```

If you need MeowPlayer to behave itself for a moment:

```bash
./meowplayer.py --serious-mode
```

Serious Mode removes the cat jokes, mascot splash, feline labels, quotes, paw markers, and animated tail in favor of conventional music-player wording.

If normal MeowPlayer does not contain enough cat:

```bash
./meowplayer.py --maximum-meow
```

Maximum Meow increases the mascot energy and turns the quote line into a full feline emergency.

You can combine either mode with a music directory:

```bash
./meowplayer.py --maximum-meow ~/Music
```

`--serious-mode` and `--maximum-meow` are mutually exclusive, for obvious philosophical reasons.

## Feline vocabulary

| Conventional term | MeowPlayer term |
| --- | --- |
| Library | Music Nest |
| Folders | Nests |
| Search | Scent Search |
| Queue | The Catnip Stash |
| Now Playing | Now Purring |
| Volume | Meow Level |
| Shuffle | Pounce Mode |
| Repeat | Tail-Chase |
| Pause | Paws |
| Seek | Scritch seek |
| Save playlist | Bury stash |
| Load playlist | Dig up stash |
| Current track marker | 🐾 |

Action feedback is equally important. Expect messages such as:

```text
The cat has chosen a song.
Stashed the meow: Space Song.flac
Opened THE CATNIP STASH.
The cat pulled the next treat from The Catnip Stash.
Pawsed. The cat is loafing.
Purr resumed. The loaf has awakened.
Scent locked: 3 possible meow(s).
```

## How it works

```text
Music Nest
   │
   ├── Scent Search
   │
   └── A → The Catnip Stash
              │
              │ queue-first playback
              ▼
        MeowPlayer terminal UI
              │
              │ JSON IPC over a Unix socket
              ▼
             mpv
              │
              ▼
          Audio output
```

Python handles the interface, library scanning, metadata-backed views, search, queue state, playlist files, keyboard controls, and all cat-related responsibilities. **Mutagen** reads audio tags, while `mpv` handles the actual audio decoding and playback.

This means MeowPlayer does not need to implement MP3, FLAC, AAC, Opus, and other audio codecs itself.

## Project structure

```text
MeowPlayer/
├── meowplayer.py
├── meow_persistence.py
├── mpris_support.py
├── requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

## Development

After making changes:

```bash
git status
git diff
git add .
git commit -m "Describe your change"
git push
```

## Roadmap

Some possible future improvements:

- Album-art support in compatible terminals
- Better shuffle history
- Packaging as a system command
- Additional scientifically unnecessary cat behavior

## License

MeowPlayer is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE) for the full license text.

## Why "MeowPlayer"?

Because every respectable terminal deserves at least one cat-themed application.

```text
 /\_/\
( o.o )
 > ^ <
```

And because apparently naming it MeowPlayer was not enough. We had to commit to the bit.
