# MeowPlayer 🐱🎵

A lightweight terminal music player written in Python, with `mpv` handling audio playback and `curses` providing the terminal UI.

MeowPlayer recursively scans a music directory, displays your tracks in the terminal, and lets you control playback entirely from the keyboard.

## Features

- Full-screen terminal interface
- Recursive music-folder scanning
- Play and pause
- Previous and next track
- Seek forward and backward
- Volume control
- Shuffle mode
- Repeat mode
- Playback progress and duration display
- Automatic playback of the next track
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

## Controls

| Key | Action |
| --- | --- |
| `↑` / `↓` | Select a track |
| `Enter` | Play selected track |
| `Space` | Play / pause |
| `←` / `→` | Seek backward / forward 5 seconds |
| `N` | Next track |
| `P` | Previous track |
| `+` / `-` | Volume up / down |
| `S` | Toggle shuffle |
| `R` | Toggle repeat |
| `Q` | Quit |

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

Python handles the user interface, song selection, controls, and library scanning. `mpv` handles the actual audio decoding and playback.

This means MeowPlayer does not need to implement MP3, FLAC, AAC, Opus, and other audio codecs itself.

## Project structure

```text
MeowPlayer/
├── meowplayer.py
├── README.md
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

## Why "MeowPlayer"?

Because every respectable terminal deserves at least one cat-themed application.

```text
 /_/\\
( o.o )
 > ^ <
```
