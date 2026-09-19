# MeowPlayer 🐱🎵

A lightweight, aggressively cat-themed terminal music player written in Python, with `mpv` handling audio playback and `curses` providing the terminal UI.

MeowPlayer recursively scans a music directory, displays your tracks in the terminal, and lets you control playback entirely from the keyboard.

```text
 /\_/\   ♫ MEOWPLAYER — terminal purr engine
( o.o )
 > ^ <

Now Purring: Space Song.flac
00:42 ━━━━━━━∿──────────── 03:28

Meow Level: 70%   Pounce Mode: OFF   Tail-Chase: ON
```

## Features

- Full-screen terminal interface
- Cat mascot in the header
- Cat-themed startup splash
- Random rotating cat quotes
- Cat-flavored status messages
- Animated tail progress marker
- Pawprint marker for the currently playing track
- Recursive music-folder scanning
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
- A terminal with curses support
- Linux or another Unix-like environment with Unix domain sockets

No third-party Python packages are required.

### Arch Linux

```bash
sudo pacman -S python mpv
```

### Debian / Ubuntu

```bash
sudo apt install python3 mpv
```

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

By default, MeowPlayer scans `~/Music`:

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

## Controls

| Key | MeowPlayer action |
| --- | --- |
| `↑` / `↓` | Choose a track |
| `Enter` | Play selected track |
| `Space` | Paws / resume |
| `←` / `→` | Scritch backward / forward 5 seconds |
| `N` | Next meow |
| `P` | Previous purr |
| `+` / `-` | Raise / lower Meow Level |
| `S` | Toggle Pounce Mode (shuffle) |
| `R` | Toggle Tail-Chase (repeat) |
| `Q` | Escape before the cat notices |

## Feline vocabulary

MeowPlayer has elected to rename several ordinary music-player concepts:

| Conventional term | MeowPlayer term |
| --- | --- |
| Now Playing | Now Purring |
| Volume | Meow Level |
| Shuffle | Pounce Mode |
| Repeat | Tail-Chase |
| Pause | Paws |
| Seek | Scritch seek |
| Current track marker | 🐾 |

Action feedback is equally important. Expect messages such as:

```text
The cat has chosen a song.
Pawsed. The cat is loafing.
Purr resumed. The loaf has awakened.
Skipped to the next meow.
Back to the previous purr.
Meow level increased.
The cat has quieted down.
```

## How it works

MeowPlayer has two main pieces:

```text
MeowPlayer terminal UI
        │
        │ JSON IPC over a Unix socket
        ▼
       mpv
        │
        ▼
     Audio output
```

Python handles the interface, song selection, controls, library scanning, and all cat-related responsibilities. `mpv` handles the actual audio decoding and playback.

This means MeowPlayer does not need to implement MP3, FLAC, AAC, Opus, and other audio codecs itself.

## Project structure

```text
MeowPlayer/
├── meowplayer.py
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

- Playlist support
- Search and filtering
- Album and artist metadata
- Album-art support in compatible terminals
- Queue management
- Configuration file
- Media-key support
- MPRIS integration
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
