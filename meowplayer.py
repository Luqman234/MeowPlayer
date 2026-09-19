#!/usr/bin/env python3

import argparse
import curses
import json
import os
import queue
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

from meow_catalog import LibraryCatalog
from meow_persistence import (
    load_config,
    load_state,
    save_config,
    save_state,
)
from mpris_support import MPRISBridge


__version__ = "0.9.0"


SUPPORTED_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".opus",
    ".wav", ".m4a", ".aac", ".wma"
}

LIBRARY_VIEWS = (
    "songs",
    "artists",
    "albums",
    "folders",
    "pawmarks",
    "history",
)
VIEW_LABELS = {
    "songs": ("Songs", "Songs"),
    "artists": ("Artists", "Artists"),
    "albums": ("Albums", "Albums"),
    "folders": ("Folders", "Nests"),
    "pawmarks": ("Favorites", "Pawmarks"),
    "history": ("Listening History", "Purr History"),
}

CAT_QUOTES = [
    "A cat chooses the soundtrack, not the other way around.",
    "Now serving fresh purrs.",
    "This terminal has been claimed by a musical cat.",
    "Every playlist deserves a little mischief.",
    "Nine lives. One excellent queue.",
    "If it fits in the terminal, the cat sits in the terminal.",
    "Paws on the keyboard. Music in the speakers.",
    "The Catnip Stash is legally considered organized chaos.",
    "Metadata is just a cat reading the tiny label on the record.",
    "The queue has been inspected. Several times. For quality control.",
    "No keyboard is safe from paws.",
    "The waveform has been judged acceptable by the cat.",
    "Local files. Local cat. Maximum ownership.",
    "A suspicious amount of engineering has gone into this meow.",
]

CAT_MASCOT = (
    " /\\_/\\",
    r"( o.o )",
    r" > ^ <",
)

CAT_MOOD_MASCOTS = {
    "Waiting": (
        " /\\_/\\",
        r"( -.- )",
        r" > ^ <  zZ",
    ),
    "Purring": (
        " /\\_/\\",
        r"( ^.^ )",
        r" > ♫ <",
    ),
    "Loafing": (
        " /\\_/\\",
        r"( -.- )",
        r" > ^ <  ...",
    ),
    "Zoomies": (
        " /\\_/\\",
        r"( >.< )",
        r" > ~ <  !!",
    ),
    "Tail-Chasing": (
        " /\\_/\\",
        r"( @.@ )",
        r" > ↻ <",
    ),
    "Guarding Catnip": (
        " /\\_/\\",
        r"( o.o )",
        r" > ~ <",
    ),
}

MAXIMUM_MEOW_MASCOT = (
    "  /\\_/\\      ♪",
    r" ( =^.^=)   ♫",
    r'  (")_(")   ♪',
)

TAIL_FRAMES = ("~", "⌁", "∿", "≈")


@dataclass(frozen=True)
class TrackMetadata:
    path: Path
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int
    track_text: str
    year: str
    genre: str
    duration: float
    folder: str
    filename: str
    tagged: bool

    @property
    def artist_title(self):
        return f"{self.title} — {self.artist}"

    @property
    def queue_label(self):
        if self.album != "Unknown Album":
            return f"{self.artist_title} · {self.album}"
        return self.artist_title


def _first_tag(tags, *names):
    if not tags:
        return ""

    for name in names:
        value = tags.get(name)
        if value is None:
            continue

        if isinstance(value, (list, tuple)):
            if not value:
                continue
            value = value[0]

        value = str(value).strip()
        if value:
            return value

    return ""


def _parse_track_number(value):
    if not value:
        return 0, ""

    text = str(value).strip()
    first = text.split("/", 1)[0].strip()

    digits = ""
    for char in first:
        if char.isdigit():
            digits += char
        elif digits:
            break

    try:
        number = int(digits) if digits else 0
    except ValueError:
        number = 0

    return number, text


def _clean_year(value):
    if not value:
        return ""

    text = str(value).strip()
    for token in text.replace("/", "-").split("-"):
        token = token.strip()
        if len(token) == 4 and token.isdigit():
            return token
    return text[:12]


def _normalize_search_text(value):
    return unicodedata.normalize("NFKC", str(value)).casefold()


def _is_termux():
    prefix = os.environ.get("PREFIX", "")
    return bool(
        os.environ.get("TERMUX_VERSION")
        or "com.termux" in prefix
        or "/termux/" in prefix
    )


def _default_music_dir():
    if not _is_termux():
        return Path("~/Music").expanduser()

    candidates = [
        Path("~/storage/music").expanduser(),
        Path("/storage/emulated/0/Music"),
        Path("~/Music").expanduser(),
    ]

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    # This is the path termux-setup-storage normally creates.
    return candidates[0]


def _platform_install_hint():
    if _is_termux():
        return (
            "Install mpv in Termux with:\n\n"
            "    pkg install mpv\n"
        )

    return (
        "Install mpv on Arch Linux with:\n\n"
        "    sudo pacman -S mpv\n"
    )


def _missing_music_dir_message(path):
    message = f"Music directory doesn't exist: {path}"

    if _is_termux():
        message += (
            "\n\nTermux detected. To access Android's shared Music folder, run:\n\n"
            "    termux-setup-storage\n\n"
            "Then allow the storage permission and try again. "
            "MeowPlayer will prefer ~/storage/music automatically.\n"
            "You can also pass any readable music directory explicitly."
        )

    return message


class MPVController:
    def __init__(self):
        self.socket_path = os.path.join(
            tempfile.gettempdir(),
            f"meowplayer-{os.getpid()}.sock"
        )

        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

        self.process = subprocess.Popen(
            [
                "mpv",
                "--no-video",
                "--idle=yes",
                "--keep-open=yes",
                "--really-quiet",
                f"--input-ipc-server={self.socket_path}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for _ in range(50):
            if os.path.exists(self.socket_path):
                break
            time.sleep(0.02)

    def command(self, *args):
        if not os.path.exists(self.socket_path):
            return None

        request = {"command": list(args)}

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                sock.connect(self.socket_path)
                sock.sendall((json.dumps(request) + "\n").encode("utf-8"))

                data = b""
                while not data.endswith(b"\n"):
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk

            if data:
                return json.loads(data.decode("utf-8"))

        except (OSError, json.JSONDecodeError, socket.timeout):
            pass

        return None

    def get_property(self, name):
        response = self.command("get_property", name)
        if response and response.get("error") == "success":
            return response.get("data")
        return None

    def set_property(self, name, value):
        self.command("set_property", name, value)

    def set_repeat(self, enabled):
        self.set_property("loop-file", "inf" if enabled else "no")

    def load(self, filename):
        self.command("loadfile", str(filename), "replace")

    def pause(self):
        self.set_property("pause", True)

    def play(self):
        self.set_property("pause", False)

    def toggle_pause(self):
        paused = self.get_property("pause")
        self.set_property("pause", not bool(paused))
        return not bool(paused)

    def stop(self):
        self.command("stop")

    def seek(self, seconds):
        self.command("seek", seconds, "relative")

    def seek_absolute(self, seconds):
        self.command("seek", max(0.0, seconds), "absolute", "exact")

    def quit(self):
        try:
            self.command("quit")
        except Exception:
            pass

        try:
            self.process.terminate()
        except Exception:
            pass

        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass


class MeowPlayer:
    def __init__(
        self,
        music_dir,
        serious_mode=False,
        maximum_meow=False,
        saved_state=None,
        restore_session=True,
        mpris_enabled=True,
        rebuild_catalog=False,
    ):
        self.music_dir = Path(music_dir).expanduser().resolve()
        self.serious_mode = serious_mode
        self.maximum_meow = maximum_meow
        self.saved_state = saved_state or {}
        self.restore_session_enabled = restore_session
        self.mpris_enabled = mpris_enabled and not _is_termux()

        self.catalog = None
        self.catalog_error = None
        self.catalog_hits = 0
        self.catalog_refreshed = 0
        self.catalog_pruned = 0

        self.songs = self.find_songs()
        self.metadata = self.load_library_metadata(
            rebuild=rebuild_catalog
        )
        self.library_stats = (
            self.catalog.play_stats()
            if self.catalog is not None
            else {}
        )
        self.drill_artist = None
        self.drill_album = None
        self.song_lookup = {
            song.resolve(): index for index, song in enumerate(self.songs)
        }

        self.selected = 0
        self.stash_selected = 0
        self.current = None
        self.history = []
        self.shuffle_bag = []

        try:
            restored_volume = int(self.saved_state.get("volume", 70))
        except (TypeError, ValueError):
            restored_volume = 70

        self.volume = max(0, min(100, restored_volume))
        self.shuffle = bool(self.saved_state.get("shuffle", False))
        self.repeat = bool(self.saved_state.get("repeat", False))

        self.view = "library"
        restored_view = self.saved_state.get("library_view", "songs")
        self.library_view = (
            restored_view
            if restored_view in LIBRARY_VIEWS
            else "songs"
        )
        self.catnip_stash = []
        for saved_path in self.saved_state.get("catnip_stash", []):
            try:
                resolved = Path(saved_path).expanduser().resolve()
            except (OSError, RuntimeError, TypeError):
                continue

            saved_index = self.song_lookup.get(resolved)
            if saved_index is not None:
                self.catnip_stash.append(saved_index)

        self.history = self.restore_saved_index_list(
            self.saved_state.get("playback_history", []),
            unique=False,
            limit=200,
        )
        self.shuffle_bag = self.restore_saved_index_list(
            self.saved_state.get("shuffle_bag", []),
            unique=True,
        )

        self.search_query = ""
        self.search_active = False

        tagged_count = sum(meta.tagged for meta in self.metadata)
        if self.catalog_error:
            initial_serious = (
                f"Library ready without cache: {tagged_count}/"
                f"{len(self.metadata)} track(s) tagged. "
                f"Catalog error: {self.catalog_error}"
            )
            initial_cat = (
                f"The Cat Catalog fell off the shelf, but the nest still "
                f"loaded {len(self.metadata)} meow(s): {self.catalog_error}"
            )
        else:
            initial_serious = (
                f"Cat Catalog: {self.catalog_hits} cached, "
                f"{self.catalog_refreshed} refreshed, "
                f"{self.catalog_pruned} pruned; "
                f"{tagged_count}/{len(self.metadata)} tagged."
            )
            initial_cat = (
                f"Cat Catalog checked: {self.catalog_hits} remembered, "
                f"{self.catalog_refreshed} re-sniffed, "
                f"{self.catalog_pruned} vanished; "
                f"{tagged_count}/{len(self.metadata)} tagged meow(s)."
            )

            if MutagenFile is None and self.catalog_refreshed:
                initial_serious += (
                    " Mutagen unavailable; refreshed files used fallbacks."
                )
                initial_cat += (
                    " No tag-reader today, so fresh tracks were guessed "
                    "from filenames."
                )

        self.status_message = self.text(initial_serious, initial_cat)
        self.quote = random.choice(CAT_QUOTES)
        self.last_quote_change = time.monotonic()
        self.tail_frame = 0
        self.last_state_save = 0.0
        self.last_mpris_sync = 0.0
        self.external_actions = queue.SimpleQueue()
        self.remote_quit_requested = False

        self.mpv = MPVController()
        self.mpv.set_property("volume", self.volume)
        self.mpv.set_repeat(self.repeat)

        if self.restore_session_enabled:
            self.restore_session(self.saved_state)

        self.sanitize_shuffle_bag()
        if self.shuffle and not self.shuffle_bag and len(self.songs) > 1:
            self.refill_shuffle_bag()

        self.mpris = MPRISBridge(self.external_actions)
        if self.mpris_enabled:
            requested_mpris = True
            self.mpris_enabled = self.mpris.start()
            if requested_mpris and not self.mpris_enabled:
                error = self.mpris.error or "unknown MPRIS startup error"
                self.set_status(
                    f"MPRIS unavailable: {error}",
                    f"The media-key cat tripped over D-Bus: {error}"
                )

    def restore_saved_index_list(self, saved_paths, unique=False, limit=None):
        indices = []
        seen = set()

        if not isinstance(saved_paths, list):
            return indices

        for saved_path in saved_paths:
            try:
                resolved = Path(saved_path).expanduser().resolve()
            except (OSError, RuntimeError, TypeError):
                continue

            index = self.song_lookup.get(resolved)
            if index is None:
                continue
            if unique and index in seen:
                continue

            indices.append(index)
            seen.add(index)

        if limit is not None:
            indices = indices[-limit:]

        return indices

    def sanitize_shuffle_bag(self):
        cleaned = []
        seen = set()

        for index in self.shuffle_bag:
            if not isinstance(index, int):
                continue
            if index < 0 or index >= len(self.songs):
                continue
            if index == self.current:
                continue
            if index in seen:
                continue
            cleaned.append(index)
            seen.add(index)

        self.shuffle_bag = cleaned

    def refill_shuffle_bag(self):
        self.shuffle_bag = [
            index
            for index in range(len(self.songs))
            if index != self.current
        ]
        random.shuffle(self.shuffle_bag)

    def set_shuffle_enabled(self, enabled):
        enabled = bool(enabled)
        changed = enabled != self.shuffle
        self.shuffle = enabled

        if not enabled:
            self.shuffle_bag.clear()
        elif changed or not self.shuffle_bag:
            self.refill_shuffle_bag()

    def restore_session(self, saved_state):
        track = saved_state.get("current_track")
        if not track:
            return

        try:
            track_path = Path(track).expanduser().resolve()
        except (OSError, RuntimeError):
            return

        index = self.song_lookup.get(track_path)
        if index is None:
            return

        try:
            position = max(0.0, float(saved_state.get("position", 0.0)))
        except (TypeError, ValueError):
            position = 0.0

        self.current = index
        self.mpv.pause()
        self.mpv.load(self.songs[index])
        self.mpv.pause()

        if position > 0:
            time.sleep(0.03)
            self.mpv.seek_absolute(position)

        ordered = self.ordered_library_indices()
        if index in ordered:
            self.selected = ordered.index(index)

        meta = self.meta(index)
        self.set_status(
            f"Restored session: {meta.artist_title}",
            f"The cat remembered: {meta.artist_title}"
        )

    def state_snapshot(self):
        position = 0.0
        if self.current is not None:
            try:
                position = float(
                    self.mpv.get_property("time-pos") or 0.0
                )
            except (TypeError, ValueError):
                position = 0.0

        return {
            "volume": self.volume,
            "shuffle": self.shuffle,
            "repeat": self.repeat,
            "library_view": self.library_view,
            "current_track": (
                str(self.songs[self.current].resolve())
                if self.current is not None
                else None
            ),
            "position": max(0.0, position),
            "catnip_stash": [
                str(self.songs[index].resolve())
                for index in self.catnip_stash
            ],
            "shuffle_bag": [
                str(self.songs[index].resolve())
                for index in self.shuffle_bag
                if 0 <= index < len(self.songs)
            ],
            "playback_history": [
                str(self.songs[index].resolve())
                for index in self.history[-200:]
                if 0 <= index < len(self.songs)
            ],
        }

    def persist_state(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_state_save < 5.0:
            return

        save_state(self.state_snapshot())
        self.last_state_save = now

    def mpris_snapshot(self):
        idle = True
        paused = False
        position = 0.0
        duration = 0.0

        if self.current is not None:
            idle = bool(self.mpv.get_property("idle-active"))
            paused = bool(self.mpv.get_property("pause"))

            try:
                position = float(
                    self.mpv.get_property("time-pos") or 0.0
                )
            except (TypeError, ValueError):
                position = 0.0

            try:
                duration = float(
                    self.mpv.get_property("duration") or 0.0
                )
            except (TypeError, ValueError):
                duration = 0.0

        if self.current is None or idle:
            playback_status = "Stopped"
        elif paused:
            playback_status = "Paused"
        else:
            playback_status = "Playing"

        metadata = None
        if self.current is not None:
            meta = self.meta(self.current)
            metadata = {
                "track_id": (
                    f"/org/mpris/MediaPlayer2/track/"
                    f"track_{self.current}"
                ),
                "title": meta.title,
                "artist": (
                    None
                    if meta.artist == "Unknown Artist"
                    else meta.artist
                ),
                "album": (
                    None
                    if meta.album == "Unknown Album"
                    else meta.album
                ),
                "album_artist": (
                    None
                    if meta.album_artist == "Unknown Artist"
                    else meta.album_artist
                ),
                "url": self.songs[self.current].resolve().as_uri(),
                "length_us": int(max(0.0, duration) * 1_000_000),
            }

        return {
            "playback_status": playback_status,
            "loop_status": "Track" if self.repeat else "None",
            "shuffle": self.shuffle,
            "volume": self.volume / 100.0,
            "position_us": int(max(0.0, position) * 1_000_000),
            "metadata": metadata,
            "has_track": self.current is not None and not idle,
            "has_tracks": bool(self.songs),
        }

    def sync_mpris(self, force=False):
        if not self.mpris_enabled:
            return

        now = time.monotonic()
        if not force and now - self.last_mpris_sync < 0.5:
            return

        self.mpris.update(self.mpris_snapshot())
        self.last_mpris_sync = now

    def process_external_actions(self):
        handled = False

        while True:
            try:
                action, args = self.external_actions.get_nowait()
            except queue.Empty:
                break

            handled = True

            if action == "quit":
                self.remote_quit_requested = True
            elif action == "next":
                self.next_song()
            elif action == "previous":
                self.previous_song()
            elif action == "pause":
                if self.current is not None:
                    self.mpv.pause()
            elif action == "play":
                if self.current is None:
                    self.play_selected_library_song()
                elif bool(self.mpv.get_property("idle-active")):
                    self.play(
                        self.current,
                        record_history=False,
                        record_listen=False,
                    )
                else:
                    self.mpv.play()
            elif action == "play_pause":
                if self.current is None:
                    self.play_selected_library_song()
                elif bool(self.mpv.get_property("idle-active")):
                    self.play(
                        self.current,
                        record_history=False,
                        record_listen=False,
                    )
                else:
                    self.mpv.toggle_pause()
            elif action == "stop":
                if self.current is not None:
                    self.mpv.stop()
            elif action == "seek" and self.current is not None:
                self.mpv.seek(args[0])
                position = self.mpv.get_property("time-pos") or 0
                self.mpris.notify_seeked(float(position) * 1_000_000)
            elif action == "set_position" and self.current is not None:
                self.mpv.seek_absolute(args[0])
                self.mpris.notify_seeked(args[0] * 1_000_000)
            elif action == "set_volume":
                self.set_volume_absolute(args[0] * 100.0)
            elif action == "set_shuffle":
                self.set_shuffle_enabled(args[0])
            elif action == "set_repeat":
                self.repeat = bool(args[0])
                self.mpv.set_repeat(self.repeat)

        if handled:
            self.sync_mpris(force=True)

    def shutdown(self):
        self.persist_state(force=True)
        self.mpris.stop()

        if self.catalog is not None:
            try:
                self.catalog.commit()
                self.catalog.close()
            except sqlite3.Error:
                pass
            self.catalog = None

        self.mpv.quit()

    def text(self, serious, cat):
        return serious if self.serious_mode else cat

    def set_status(self, serious, cat):
        self.status_message = self.text(serious, cat)

    def cat_mood(self):
        if self.current is None:
            return "Waiting"

        paused = bool(self.mpv.get_property("pause"))
        if paused:
            return "Loafing"
        if self.repeat:
            return "Tail-Chasing"
        if self.shuffle:
            return "Zoomies"
        if self.catnip_stash:
            return "Guarding Catnip"
        return "Purring"

    def live_cat_mascot(self):
        if self.maximum_meow:
            mood = self.cat_mood()
            middle = {
                "Waiting": r" ( =-.-=)   zZ",
                "Purring": r" ( =^.^=)   ♫",
                "Loafing": r" ( =-.-=)   ...",
                "Zoomies": r" ( =>.<=)   !!",
                "Tail-Chasing": r" ( =@.@=)   ↻",
                "Guarding Catnip": r" ( =o.o=)   ~",
            }[mood]
            return (
                "  /\\_/\\      ♪",
                middle,
                r'  (")_(")   ♪',
            )

        return CAT_MOOD_MASCOTS[self.cat_mood()]

    def next_treat_label(self):
        if not self.songs:
            return "none"

        if self.repeat and self.current is not None:
            return f"{self.meta(self.current).title} ↻"

        if self.catnip_stash:
            return self.meta(self.catnip_stash[0]).artist_title

        if self.shuffle:
            remaining = len(self.shuffle_bag)
            return f"mystery meow ({remaining} left in Pounce Bag)"

        if self.current is None:
            return self.meta(0).artist_title

        next_index = (self.current + 1) % len(self.songs)
        return self.meta(next_index).artist_title

    def find_songs(self):
        songs = []
        for path in self.music_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                songs.append(path)
        return sorted(songs, key=lambda p: p.name.casefold())

    def metadata_from_catalog(self, path, cached):
        return TrackMetadata(
            path=path,
            title=cached["title"],
            artist=cached["artist"],
            album=cached["album"],
            album_artist=cached["album_artist"],
            track_number=int(cached["track_number"]),
            track_text=cached["track_text"],
            year=cached["year"],
            genre=cached["genre"],
            duration=float(cached["duration"]),
            folder=cached["folder"],
            filename=cached["filename"],
            tagged=bool(cached["tagged"]),
        )

    def load_library_metadata(self, rebuild=False):
        try:
            self.catalog = LibraryCatalog(self.music_dir)

            if rebuild:
                self.catalog.invalidate_root()

            metadata = []
            for path in self.songs:
                try:
                    stat_result = path.stat()
                except OSError:
                    metadata.append(self.read_metadata(path))
                    self.catalog_refreshed += 1
                    continue

                cached = self.catalog.get(path, stat_result)
                if cached is not None:
                    metadata.append(
                        self.metadata_from_catalog(path, cached)
                    )
                    self.catalog_hits += 1
                    continue

                parsed = self.read_metadata(path)
                metadata.append(parsed)
                self.catalog.put(path, stat_result, parsed)
                self.catalog_refreshed += 1

            self.catalog_pruned += self.catalog.prune(self.songs)
            self.catalog.commit()
            return metadata

        except (
            OSError,
            RuntimeError,
            sqlite3.Error,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            self.catalog_error = str(exc)

            if self.catalog is not None:
                try:
                    self.catalog.close()
                except sqlite3.Error:
                    pass
                self.catalog = None

            self.catalog_hits = 0
            self.catalog_refreshed = len(self.songs)
            self.catalog_pruned = 0
            return [
                self.read_metadata(path)
                for path in self.songs
            ]

    def read_metadata(self, path):
        title = path.stem
        artist = "Unknown Artist"
        album = "Unknown Album"
        album_artist = ""
        track_number = 0
        track_text = ""
        year = ""
        genre = ""
        duration = 0.0
        tagged = False

        try:
            relative_parent = path.parent.relative_to(self.music_dir)
            folder = (
                str(relative_parent)
                if str(relative_parent) != "."
                else "Music Root"
            )
        except ValueError:
            folder = str(path.parent)

        if MutagenFile is not None:
            try:
                audio = MutagenFile(path, easy=True)
                tags = (
                    getattr(audio, "tags", None)
                    if audio is not None
                    else None
                )

                raw_title = _first_tag(tags, "title", "©nam")
                raw_artist = _first_tag(
                    tags,
                    "artist",
                    "albumartist",
                    "author",
                    "©ART",
                )
                raw_album = _first_tag(tags, "album", "©alb")
                raw_album_artist = _first_tag(
                    tags,
                    "albumartist",
                    "album artist",
                    "aART",
                )
                raw_track = _first_tag(
                    tags,
                    "tracknumber",
                    "track",
                    "trkn",
                )
                raw_year = _first_tag(
                    tags,
                    "date",
                    "year",
                    "©day",
                )
                raw_genre = _first_tag(
                    tags,
                    "genre",
                    "©gen",
                )

                try:
                    duration = float(
                        getattr(getattr(audio, "info", None), "length", 0.0)
                        or 0.0
                    )
                except (TypeError, ValueError):
                    duration = 0.0

                tagged = any(
                    (
                        raw_title,
                        raw_artist,
                        raw_album,
                        raw_album_artist,
                        raw_track,
                        raw_year,
                        raw_genre,
                    )
                )

                if raw_title:
                    title = raw_title
                if raw_artist:
                    artist = raw_artist
                if raw_album:
                    album = raw_album
                if raw_album_artist:
                    album_artist = raw_album_artist

                track_number, track_text = _parse_track_number(raw_track)
                year = _clean_year(raw_year)
                genre = raw_genre

            except Exception:
                # Bad or unsupported tags should never break the library.
                pass

        if not album_artist:
            album_artist = artist

        return TrackMetadata(
            path=path,
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            track_number=track_number,
            track_text=track_text,
            year=year,
            genre=genre,
            duration=max(0.0, duration),
            folder=folder,
            filename=path.name,
            tagged=tagged,
        )

    def meta(self, index):
        return self.metadata[index]

    def search_haystack(self, index):
        meta = self.meta(index)
        try:
            relative = str(meta.path.relative_to(self.music_dir))
        except ValueError:
            relative = str(meta.path)

        fields = [
            meta.title,
            meta.year,
            meta.genre,
            meta.folder,
            meta.filename,
            relative,
        ]

        if meta.artist != "Unknown Artist":
            fields.append(meta.artist)
        if meta.album != "Unknown Album":
            fields.append(meta.album)
        if (
            meta.album_artist
            and meta.album_artist != "Unknown Artist"
        ):
            fields.append(meta.album_artist)

        return _normalize_search_text(" ".join(fields))

    def stats_for(self, index):
        return self.library_stats.get(
            str(self.songs[index].resolve()),
            {
                "favorite": False,
                "play_count": 0,
                "last_played_ns": None,
                "added_at_ns": 0,
            },
        )

    def refresh_library_stats(self):
        if self.catalog is not None:
            self.library_stats = self.catalog.play_stats()

    def filtered_song_indices(self):
        indices = list(range(len(self.songs)))
        query = _normalize_search_text(self.search_query).strip()

        if query:
            indices = [
                index
                for index in indices
                if query in self.search_haystack(index)
            ]

        if self.drill_artist is not None:
            indices = [
                index
                for index in indices
                if self.meta(index).artist == self.drill_artist
            ]

        if self.drill_album is not None:
            album_artist, album = self.drill_album
            indices = [
                index
                for index in indices
                if (
                    self.meta(index).album_artist == album_artist
                    and self.meta(index).album == album
                )
            ]

        if self.library_view == "pawmarks":
            indices = [
                index
                for index in indices
                if self.stats_for(index)["favorite"]
            ]

        if self.library_view == "history":
            indices = [
                index
                for index in indices
                if self.stats_for(index)["last_played_ns"] is not None
            ]

        return indices

    def ordered_track_indices(self):
        indices = self.filtered_song_indices()

        if self.library_view == "history":
            return sorted(
                indices,
                key=lambda i: (
                    -(self.stats_for(i)["last_played_ns"] or 0),
                    self.meta(i).title.casefold(),
                ),
            )

        if self.library_view in ("songs", "pawmarks"):
            return sorted(
                indices,
                key=lambda i: (
                    self.meta(i).title.casefold(),
                    self.meta(i).artist.casefold(),
                    self.meta(i).album.casefold(),
                    self.meta(i).track_number,
                    self.meta(i).filename.casefold(),
                ),
            )

        if self.library_view == "artists":
            return sorted(
                indices,
                key=lambda i: (
                    self.meta(i).artist.casefold(),
                    self.meta(i).album.casefold(),
                    self.meta(i).track_number or 999999,
                    self.meta(i).title.casefold(),
                ),
            )

        if self.library_view == "albums":
            return sorted(
                indices,
                key=lambda i: (
                    self.meta(i).album_artist.casefold(),
                    self.meta(i).album.casefold(),
                    self.meta(i).track_number or 999999,
                    self.meta(i).title.casefold(),
                ),
            )

        return sorted(
            indices,
            key=lambda i: (
                self.meta(i).folder.casefold(),
                self.meta(i).filename.casefold(),
            ),
        )

    def ordered_library_indices(self):
        indices = self.ordered_track_indices()

        if self.library_view == "artists":
            if self.drill_artist is None:
                representatives = {}
                for index in indices:
                    representatives.setdefault(
                        self.meta(index).artist,
                        index,
                    )
                return list(representatives.values())

            if self.drill_album is None:
                representatives = {}
                for index in indices:
                    meta = self.meta(index)
                    representatives.setdefault(
                        (meta.album_artist, meta.album),
                        index,
                    )
                return list(representatives.values())

        if self.library_view == "albums" and self.drill_album is None:
            representatives = {}
            for index in indices:
                meta = self.meta(index)
                representatives.setdefault(
                    (meta.album_artist, meta.album),
                    index,
                )
            return list(representatives.values())

        return indices

    def track_row_text(self, index):
        meta = self.meta(index)
        duration = (
            f" · {self.format_time(meta.duration)}"
            if meta.duration > 0
            else ""
        )
        genre = f" · {meta.genre}" if meta.genre else ""

        if self.library_view in ("songs", "pawmarks"):
            text = meta.artist_title
            if meta.album != "Unknown Album":
                text += f" · {meta.album}"
            if meta.genre:
                text += genre
            if self.stats_for(index)["favorite"]:
                text = f"★ {text}"
            return text + duration

        if self.library_view == "history":
            stats = self.stats_for(index)
            count = stats["play_count"]
            return f"{meta.artist_title} · played {count}×{duration}"

        if self.library_view == "artists":
            text = meta.title
            if meta.album != "Unknown Album":
                text += f" · {meta.album}"
            if meta.year:
                text += f" ({meta.year})"
            if meta.genre:
                text += genre
            return text + duration

        if self.library_view == "albums":
            number = (
                f"{meta.track_number:02d}. "
                if meta.track_number
                else "    "
            )
            return f"{number}{meta.title} — {meta.artist}{duration}"

        return f"{meta.filename}{duration}"

    def library_rows(self):
        ordered = self.ordered_library_indices()

        if self.library_view in ("songs", "pawmarks", "history"):
            return [
                ("track", self.track_row_text(index), index)
                for index in ordered
            ]

        if self.library_view == "artists":
            if self.drill_artist is None:
                all_tracks = self.ordered_track_indices()
                counts = {}
                for index in all_tracks:
                    artist = self.meta(index).artist
                    counts[artist] = counts.get(artist, 0) + 1
                return [
                    (
                        "track",
                        f"{self.meta(index).artist} · "
                        f"{counts[self.meta(index).artist]} track(s) ›",
                        index,
                    )
                    for index in ordered
                ]

            if self.drill_album is None:
                all_tracks = self.ordered_track_indices()
                counts = {}
                for index in all_tracks:
                    meta = self.meta(index)
                    key = (meta.album_artist, meta.album)
                    counts[key] = counts.get(key, 0) + 1

                rows = []
                for index in ordered:
                    meta = self.meta(index)
                    key = (meta.album_artist, meta.album)
                    label = meta.album
                    if meta.year:
                        label += f" ({meta.year})"
                    label += f" · {counts[key]} track(s) ›"
                    rows.append(("track", label, index))
                return rows

            return [
                ("track", self.track_row_text(index), index)
                for index in ordered
            ]

        if self.library_view == "albums":
            if self.drill_album is None:
                all_tracks = self.ordered_track_indices()
                counts = {}
                for index in all_tracks:
                    meta = self.meta(index)
                    key = (meta.album_artist, meta.album)
                    counts[key] = counts.get(key, 0) + 1

                rows = []
                for index in ordered:
                    meta = self.meta(index)
                    key = (meta.album_artist, meta.album)
                    label = meta.album
                    if meta.album_artist != "Unknown Artist":
                        label += f" — {meta.album_artist}"
                    if meta.year:
                        label += f" ({meta.year})"
                    label += f" · {counts[key]} track(s) ›"
                    rows.append(("track", label, index))
                return rows

            return [
                ("track", self.track_row_text(index), index)
                for index in ordered
            ]

        rows = []
        last_group = None
        for index in ordered:
            meta = self.meta(index)
            if meta.folder != last_group:
                rows.append(("header", meta.folder, None))
                last_group = meta.folder
            rows.append(("track", self.track_row_text(index), index))
        return rows

    def selected_library_song(self):
        visible = self.ordered_library_indices()
        if not visible:
            return None

        self.selected = max(0, min(self.selected, len(visible) - 1))
        return visible[self.selected]

    def library_selection_is_track(self):
        if self.library_view == "artists":
            return (
                self.drill_artist is not None
                and self.drill_album is not None
            )
        if self.library_view == "albums":
            return self.drill_album is not None
        return True

    def select_library_view(self, view):
        if view not in LIBRARY_VIEWS:
            return

        self.library_view = view
        self.drill_artist = None
        self.drill_album = None
        self.selected = 0

        serious_label, cat_label = VIEW_LABELS[view]
        self.set_status(
            f"Library view: {serious_label}.",
            f"Music Nest view: {cat_label}."
        )

    def cycle_library_view(self):
        position = LIBRARY_VIEWS.index(self.library_view)
        self.select_library_view(
            LIBRARY_VIEWS[(position + 1) % len(LIBRARY_VIEWS)]
        )

    def library_breadcrumb(self):
        serious, cat = VIEW_LABELS[self.library_view]
        label = serious if self.serious_mode else cat

        if self.drill_artist is not None:
            label += f" / {self.drill_artist}"
        if self.drill_album is not None:
            label += f" / {self.drill_album[1]}"

        return label

    def activate_library_selection(self):
        index = self.selected_library_song()
        if index is None:
            return

        meta = self.meta(index)

        if self.library_view == "artists":
            if self.drill_artist is None:
                self.drill_artist = meta.artist
                self.drill_album = None
                self.selected = 0
                self.set_status(
                    f"Opened artist: {meta.artist}",
                    f"Following {meta.artist}'s scent trail."
                )
                return

            if self.drill_album is None:
                self.drill_album = (meta.album_artist, meta.album)
                self.selected = 0
                self.set_status(
                    f"Opened album: {meta.album}",
                    f"Curled up inside the album: {meta.album}"
                )
                return

        if self.library_view == "albums" and self.drill_album is None:
            self.drill_album = (meta.album_artist, meta.album)
            self.selected = 0
            self.set_status(
                f"Opened album: {meta.album}",
                f"Curled up inside the album: {meta.album}"
            )
            return

        self.play(index)

    def go_back_library(self):
        if self.library_view == "artists" and self.drill_album is not None:
            self.drill_album = None
        elif self.library_view == "artists" and self.drill_artist is not None:
            self.drill_artist = None
        elif self.library_view == "albums" and self.drill_album is not None:
            self.drill_album = None
        else:
            return False

        self.selected = 0
        self.set_status(
            "Went up one library level.",
            "The cat backed out of this nest."
        )
        return True

    def toggle_selected_pawmark(self):
        if not self.library_selection_is_track():
            self.set_status(
                "Open the group before favoriting a track.",
                "Open this nest first, then Pawmark a specific meow."
            )
            return

        index = self.selected_library_song()
        if index is None:
            return

        if self.catalog is None:
            self.set_status(
                "Favorites unavailable without the Cat Catalog.",
                "The cat cannot leave a Pawmark while the Catalog is missing."
            )
            return

        favorite = self.catalog.toggle_favorite(self.songs[index])
        self.refresh_library_stats()
        meta = self.meta(index)

        self.set_status(
            (
                f"{'Favorited' if favorite else 'Unfavorited'}: "
                f"{meta.artist_title}"
            ),
            (
                f"{'Pawmarked' if favorite else 'Pawmark removed'}: "
                f"{meta.artist_title}"
            )
        )

    def play(self, index, automatic=False, record_history=True, record_listen=True):
        if not self.songs:
            return

        index %= len(self.songs)

        if (
            record_history
            and self.current is not None
            and self.current != index
        ):
            self.history.append(self.current)
            if len(self.history) > 200:
                self.history.pop(0)

        if self.shuffle and index in self.shuffle_bag:
            self.shuffle_bag.remove(index)

        self.current = index
        self.mpv.load(self.songs[index])
        self.mpv.play()

        if record_listen and self.catalog is not None:
            self.catalog.record_play(self.songs[index])
            self.refresh_library_stats()

        ordered = self.ordered_library_indices()
        if index in ordered:
            self.selected = ordered.index(index)

        meta = self.meta(index)
        if automatic:
            self.set_status(
                f"Playing next track: {meta.artist_title}",
                f"The cat found the next meow: {meta.artist_title}"
            )
        else:
            self.set_status(
                f"Playing: {meta.artist_title}",
                f"The cat chose: {meta.artist_title}"
            )

    def play_selected_library_song(self):
        index = self.selected_library_song()
        if index is not None:
            self.play(index)

    def add_selected_to_stash(self):
        if not self.library_selection_is_track():
            self.set_status(
                "Open the group before queueing a track.",
                "Open this nest first, then stash a specific meow."
            )
            return

        index = self.selected_library_song()
        if index is None:
            self.set_status(
                "No matching track to add.",
                "The cat found nothing to stash."
            )
            return

        self.catnip_stash.append(index)
        self.stash_selected = len(self.catnip_stash) - 1
        label = self.meta(index).artist_title
        self.set_status(
            f"Added to queue: {label}",
            f"Stashed the meow: {label}"
        )

    def play_stash_position(self, position, automatic=False):
        if not self.catnip_stash:
            return False

        position = max(0, min(position, len(self.catnip_stash) - 1))
        index = self.catnip_stash.pop(position)

        if self.catnip_stash:
            self.stash_selected = min(position, len(self.catnip_stash) - 1)
        else:
            self.stash_selected = 0

        self.play(index, automatic=automatic)

        if automatic:
            self.set_status(
                f"Playing queued track: {self.meta(index).artist_title}",
                "The cat pulled the next treat from The Catnip Stash."
            )
        else:
            self.set_status(
                f"Playing queued track: {self.meta(index).artist_title}",
                f"Pulled from The Catnip Stash: {self.meta(index).artist_title}"
            )

        return True

    def next_song(self, automatic=False):
        if not self.songs:
            return

        if self.catnip_stash:
            self.play_stash_position(0, automatic=automatic)
            return

        if self.shuffle:
            if len(self.songs) == 1:
                index = 0
            else:
                self.sanitize_shuffle_bag()
                if not self.shuffle_bag:
                    self.refill_shuffle_bag()
                index = self.shuffle_bag.pop()
        elif self.current is None:
            index = 0
        else:
            index = (self.current + 1) % len(self.songs)

        self.play(index, automatic=automatic)
        if not automatic:
            self.set_status(
                "Skipped to next track.",
                "Skipped to the next meow."
            )

    def previous_song(self):
        if not self.songs:
            return

        departed = self.current

        if self.history:
            index = self.history.pop()
        elif self.current is None:
            index = 0
        else:
            index = (self.current - 1) % len(self.songs)

        self.play(index, record_history=False)

        if (
            self.shuffle
            and departed is not None
            and departed != index
        ):
            if departed in self.shuffle_bag:
                self.shuffle_bag.remove(departed)
            self.shuffle_bag.append(departed)
        self.set_status(
            "Returned to previous track.",
            "Back to the previous purr."
        )

    def remove_from_stash(self):
        if not self.catnip_stash:
            self.set_status("Queue is empty.", "The Catnip Stash is already empty.")
            return

        index = self.catnip_stash.pop(self.stash_selected)
        if self.catnip_stash:
            self.stash_selected = min(
                self.stash_selected,
                len(self.catnip_stash) - 1
            )
        else:
            self.stash_selected = 0

        label = self.meta(index).artist_title
        self.set_status(
            f"Removed from queue: {label}",
            f"Yeeted from The Catnip Stash: {label}"
        )

    def move_stash_item(self, direction):
        if len(self.catnip_stash) < 2:
            return

        old = self.stash_selected
        new = max(0, min(old + direction, len(self.catnip_stash) - 1))

        if new == old:
            return

        self.catnip_stash[old], self.catnip_stash[new] = (
            self.catnip_stash[new],
            self.catnip_stash[old],
        )
        self.stash_selected = new

        self.set_status(
            "Reordered queue.",
            "Rearranged The Catnip Stash."
        )

    def clear_stash(self):
        count = len(self.catnip_stash)
        self.catnip_stash.clear()
        self.stash_selected = 0

        if count:
            self.set_status(
                f"Cleared {count} queued track(s).",
                f"The cat knocked all {count} treat(s) out of The Catnip Stash."
            )
        else:
            self.set_status(
                "Queue is already empty.",
                "The Catnip Stash contains only imaginary treats."
            )

    def save_stash(self, path):
        path = Path(path).expanduser()
        if path.suffix.lower() not in {".m3u", ".m3u8"}:
            path = path.with_suffix(".m3u")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as playlist:
                playlist.write("#EXTM3U\n")
                for song_index in self.catnip_stash:
                    playlist.write(str(self.songs[song_index].resolve()) + "\n")
        except OSError as exc:
            self.set_status(
                f"Could not save playlist: {exc}",
                f"The cat failed to bury the playlist: {exc}"
            )
            return

        self.set_status(
            f"Saved {len(self.catnip_stash)} track(s) to {path}",
            f"Buried {len(self.catnip_stash)} treat(s) in {path.name}"
        )

    def load_stash(self, path):
        path = Path(path).expanduser()

        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError as exc:
            self.set_status(
                f"Could not load playlist: {exc}",
                f"The cat could not open that stash: {exc}"
            )
            return

        loaded = []
        missing = 0

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            song_path = Path(line).expanduser()
            if not song_path.is_absolute():
                song_path = (path.parent / song_path).resolve()
            else:
                song_path = song_path.resolve()

            song_index = self.song_lookup.get(song_path)
            if song_index is None:
                missing += 1
                continue

            loaded.append(song_index)

        self.catnip_stash = loaded
        self.stash_selected = 0

        self.set_status(
            f"Loaded {len(loaded)} track(s); {missing} unavailable.",
            f"The cat recovered {len(loaded)} treat(s); {missing} escaped."
        )

    def set_volume_absolute(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return

        self.volume = int(round(max(0.0, min(100.0, value))))
        self.mpv.set_property("volume", self.volume)

    def update_volume(self, amount):
        self.set_volume_absolute(self.volume + amount)

        if amount > 0:
            self.set_status("Volume increased.", "Meow level increased.")
        else:
            self.set_status("Volume decreased.", "The cat has quieted down.")

    @staticmethod
    def format_time(seconds):
        if seconds is None:
            return "00:00"

        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            return "00:00"

        minutes = seconds // 60
        seconds %= 60
        return f"{minutes:02}:{seconds:02}"

    def progress_bar(self, width):
        position = self.mpv.get_property("time-pos") or 0
        duration = self.mpv.get_property("duration") or 0
        bar_width = max(5, width - 20)

        progress = min(1, position / duration) if duration > 0 else 0
        filled = int(bar_width * progress)

        if self.serious_mode:
            marker = "●"
        else:
            marker = TAIL_FRAMES[self.tail_frame % len(TAIL_FRAMES)]
            self.tail_frame += 1

        bar = (
            "━" * filled
            + marker
            + "─" * max(0, bar_width - filled - 1)
        )

        return (
            f"{self.format_time(position)} "
            f"{bar} "
            f"{self.format_time(duration)}"
        )

    def splash(self, stdscr):
        if self.serious_mode:
            return

        stdscr.erase()
        height, width = stdscr.getmaxyx()
        mascot = MAXIMUM_MEOW_MASCOT if self.maximum_meow else CAT_MASCOT
        lines = list(mascot) + [
            "",
            "Welcome to MeowPlayer",
            "Sniffing metadata and indexing your music nest..."
        ]

        start_y = max(0, (height - len(lines)) // 2)
        for offset, line in enumerate(lines):
            x = max(0, (width - len(line)) // 2)
            try:
                stdscr.addstr(
                    start_y + offset,
                    x,
                    line[:max(0, width - x - 1)]
                )
            except curses.error:
                pass

        stdscr.refresh()
        time.sleep(1.2 if self.maximum_meow else 0.8)

    def draw_header(self, stdscr, width):
        if self.serious_mode:
            try:
                stdscr.addstr(
                    0,
                    0,
                    " ♫ MEOWPLAYER ",
                    curses.A_BOLD | curses.color_pair(1)
                )
            except curses.error:
                pass
            return 2

        mascot = self.live_cat_mascot()
        mood = self.cat_mood()
        title = f"♫ MEOWPLAYER v{__version__} — {mood}"

        for row, cat_line in enumerate(mascot):
            try:
                if row == 0:
                    header = f"{cat_line}   {title}"
                    stdscr.addstr(
                        row,
                        0,
                        header[:width - 1],
                        curses.A_BOLD | curses.color_pair(1)
                    )
                else:
                    stdscr.addstr(
                        row,
                        0,
                        cat_line[:width - 1],
                        curses.color_pair(1)
                    )
            except curses.error:
                pass

        return len(mascot) + 1

    def prompt_path(self, stdscr, prompt, default):
        height, width = stdscr.getmaxyx()
        label = f"{prompt} [{default}]: "

        stdscr.nodelay(False)
        stdscr.timeout(-1)
        curses.echo()

        try:
            curses.curs_set(1)
        except curses.error:
            pass

        try:
            stdscr.move(height - 1, 0)
            stdscr.clrtoeol()
            stdscr.addstr(height - 1, 0, label[:width - 1])
            stdscr.refresh()

            max_input = max(1, width - min(len(label), width - 1) - 1)
            raw = stdscr.getstr(
                height - 1,
                min(len(label), width - 2),
                max_input
            )
            value = raw.decode("utf-8", errors="replace").strip()
        except curses.error:
            value = ""
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            stdscr.nodelay(True)
            stdscr.timeout(100)

        return value or default

    def handle_search_key(self, key):
        if key in ("\x1b", 27):
            self.search_active = False
            self.search_query = ""
            self.selected = 0
            self.set_status("Search cleared.", "Scent trail cleared.")
            return

        if key in ("\n", "\r", 10, 13, curses.KEY_ENTER):
            self.search_active = False
            matches = len(self.filtered_song_indices())
            self.set_status(
                f"Search applied: {matches} match(es).",
                f"Scent locked: {matches} possible meow(s)."
            )
            return

        if key in ("\b", "\x7f", curses.KEY_BACKSPACE, 127, 8):
            self.search_query = self.search_query[:-1]
            self.selected = 0
            return

        if isinstance(key, str):
            if key.isprintable():
                self.search_query += key
                self.selected = 0
            return

        if isinstance(key, int) and 32 <= key <= 126:
            self.search_query += chr(key)
            self.selected = 0

    def draw_library(
        self,
        stdscr,
        width,
        list_start,
        list_height,
        scroll,
    ):
        ordered = self.ordered_library_indices()
        rows = self.library_rows()

        if ordered:
            self.selected = max(
                0,
                min(self.selected, len(ordered) - 1)
            )
            selected_index = ordered[self.selected]
        else:
            self.selected = 0
            selected_index = None

        selected_row = 0
        if selected_index is not None:
            for row_index, (_, _, song_index) in enumerate(rows):
                if song_index == selected_index:
                    selected_row = row_index
                    break

        if selected_row < scroll:
            scroll = selected_row
        if selected_row >= scroll + list_height:
            scroll = selected_row - list_height + 1

        if not rows:
            message = self.text(
                "No tracks match the current search.",
                "No meows match that scent trail."
            )
            try:
                stdscr.addstr(
                    list_start,
                    2,
                    message[:width - 4],
                    curses.A_DIM
                )
            except curses.error:
                pass
            return scroll

        for screen_row, row_index in enumerate(
            range(scroll, min(len(rows), scroll + list_height))
        ):
            kind, label, song_index = rows[row_index]
            y = list_start + screen_row

            if kind == "header":
                marker = "▾ " if not self.serious_mode else "— "
                text = marker + label
                try:
                    stdscr.addstr(
                        y,
                        2,
                        text[:width - 4],
                        curses.A_BOLD | curses.color_pair(1)
                    )
                except curses.error:
                    pass
                continue

            is_selected = song_index == selected_index
            if song_index == self.current:
                prefix = "▶  " if self.serious_mode else "🐾 "
            elif is_selected and not self.serious_mode:
                prefix = ">^.^< "
            else:
                prefix = "   "

            text = prefix + label
            attr = curses.A_NORMAL

            if is_selected:
                attr |= curses.A_REVERSE
            if song_index == self.current:
                attr |= curses.color_pair(2)

            try:
                stdscr.addstr(y, 2, text[:width - 4], attr)
            except curses.error:
                pass

        return scroll

    def draw_stash(
        self,
        stdscr,
        width,
        list_start,
        list_height,
        scroll,
    ):
        if self.catnip_stash:
            self.stash_selected = max(
                0,
                min(self.stash_selected, len(self.catnip_stash) - 1)
            )
        else:
            self.stash_selected = 0

        if self.stash_selected < scroll:
            scroll = self.stash_selected
        if self.stash_selected >= scroll + list_height:
            scroll = self.stash_selected - list_height + 1

        if not self.catnip_stash:
            message = self.text(
                "Queue is empty. Press Q to return to the library.",
                "The Catnip Stash is empty. Press Q and go hunt for treats."
            )
            try:
                stdscr.addstr(list_start, 2, message[:width - 4], curses.A_DIM)
            except curses.error:
                pass
            return scroll

        for screen_row, stash_position in enumerate(
            range(
                scroll,
                min(len(self.catnip_stash), scroll + list_height)
            )
        ):
            song_index = self.catnip_stash[stash_position]
            meta = self.meta(song_index)
            number = stash_position + 1

            if stash_position == self.stash_selected and not self.serious_mode:
                prefix = f">^.^< {number:02d}. "
            else:
                prefix = f"     {number:02d}. "

            text = prefix + meta.queue_label
            y = list_start + screen_row
            attr = curses.A_NORMAL

            if stash_position == self.stash_selected:
                attr |= curses.A_REVERSE

            try:
                stdscr.addstr(y, 2, text[:width - 4], attr)
            except curses.error:
                pass

        return scroll

    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(100)

        try:
            curses.use_default_colors()
        except curses.error:
            pass

        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_MAGENTA, -1)

        self.splash(stdscr)
        library_scroll = 0
        stash_scroll = 0
        self.sync_mpris(force=True)

        while True:
            self.process_external_actions()
            self.persist_state()
            self.sync_mpris()

            if self.remote_quit_requested:
                break

            height, width = stdscr.getmaxyx()
            stdscr.erase()

            minimum_width = 32 if _is_termux() else 46
            if height < 16 or width < minimum_width:
                message = self.text(
                    (
                        f"Terminal too small. Resize to at least "
                        f"{minimum_width}x16."
                    ),
                    (
                        f"Terminal too small — give this cat at least "
                        f"{minimum_width}x16."
                    )
                )
                try:
                    stdscr.addstr(0, 0, message[:max(1, width - 1)])
                except curses.error:
                    pass

                stdscr.refresh()
                key = stdscr.getch()
                if key in (ord("x"), ord("X")):
                    break
                continue

            content_start = self.draw_header(stdscr, width)

            if self.current is not None:
                meta = self.meta(self.current)
                paused = self.mpv.get_property("pause")
                icon = "⏸" if paused else "▶"
                label = "Now Playing" if self.serious_mode else "Now Purring"
                now_playing = f"{icon}  {label}: {meta.artist_title}"
            else:
                now_playing = self.text(
                    "No song playing",
                    "No song meowing right now"
                )

            progress_y = content_start + 2
            info_y = content_start + 4
            status_y = content_start + 5
            mode_y = content_start + 6
            list_start = content_start + 8

            try:
                stdscr.addstr(
                    content_start,
                    2,
                    now_playing[:width - 4],
                    curses.A_BOLD | curses.color_pair(2)
                )
                stdscr.addstr(
                    progress_y,
                    2,
                    self.progress_bar(width - 4)[:width - 4]
                )
            except curses.error:
                pass

            if self.serious_mode:
                info = (
                    f"Volume: {self.volume}%   "
                    f"Shuffle: {'ON' if self.shuffle else 'OFF'}   "
                    f"Repeat: {'ON' if self.repeat else 'OFF'}   "
                    f"Queue: {len(self.catnip_stash)}"
                )
            else:
                info = (
                    f"Meow Level: {self.volume}%   "
                    f"Pounce: {'ON' if self.shuffle else 'OFF'}   "
                    f"Tail-Chase: {'ON' if self.repeat else 'OFF'}   "
                    f"Catnip: {len(self.catnip_stash)}   "
                    f"Mood: {self.cat_mood()}"
                )

            try:
                stdscr.addstr(
                    info_y,
                    2,
                    info[:width - 4],
                    curses.color_pair(3)
                )
                stdscr.addstr(
                    status_y,
                    2,
                    self.status_message[:width - 4],
                    curses.color_pair(4)
                    if not self.serious_mode
                    else curses.A_DIM
                )
            except curses.error:
                pass

            if self.view == "library":
                matches = len(self.filtered_song_indices())
                current_view = self.library_breadcrumb()

                if self.search_active:
                    mode_line = self.text(
                        (
                            f"SEARCH > {self.search_query}_   "
                            f"({matches} match(es)) · {current_view}"
                        ),
                        (
                            f"SCENT SEARCH > {self.search_query}_   "
                            f"({matches} meow(s)) · {current_view}"
                        )
                    )
                elif self.search_query:
                    mode_line = self.text(
                        (
                            f"Library / {current_view} — filter: "
                            f"{self.search_query!r} ({matches})"
                        ),
                        (
                            f"Music Nest / {current_view} — scent: "
                            f"{self.search_query!r} ({matches})"
                        )
                    )
                else:
                    mode_line = self.text(
                        (
                            f"Library / {current_view} — "
                            f"{matches} track(s) · "
                            f"Next: {self.next_treat_label()}"
                        ),
                        (
                            f"Music Nest / {current_view} — "
                            f"{matches} meow(s) · "
                            f"Next Treat: {self.next_treat_label()}"
                        )
                    )
            else:
                mode_line = self.text(
                    (
                        f"Queue — {len(self.catnip_stash)} track(s) · "
                        f"Next: {self.next_treat_label()}"
                    ),
                    (
                        f"THE CATNIP STASH — {len(self.catnip_stash)} treat(s) · "
                        f"Next Treat: {self.next_treat_label()}"
                    )
                )

            try:
                stdscr.addstr(
                    mode_y,
                    2,
                    mode_line[:width - 4],
                    curses.A_BOLD
                )
            except curses.error:
                pass

            footer_lines = 3 if not self.serious_mode else 2
            list_height = max(
                1,
                height - list_start - footer_lines - 1
            )

            if self.view == "library":
                library_scroll = self.draw_library(
                    stdscr,
                    width,
                    list_start,
                    list_height,
                    library_scroll,
                )
            else:
                stash_scroll = self.draw_stash(
                    stdscr,
                    width,
                    list_start,
                    list_height,
                    stash_scroll,
                )

            if (
                not self.serious_mode
                and time.monotonic() - self.last_quote_change > 20
            ):
                self.quote = random.choice(CAT_QUOTES)
                self.last_quote_change = time.monotonic()

            if self.view == "library":
                if self.serious_mode:
                    controls = (
                        "↑↓ Select  ENTER Open/Play  1-6 Views  F Favorite  "
                        "B Back  / Search  A Queue  Q Queue  X Quit"
                    )
                    quote = ""
                else:
                    controls = (
                        "↑↓ Choose  ENTER Open/Purr  1-6 Nests  F Pawmark  "
                        "B Back  / Scent  A Stash  Q Catnip  X Escape"
                    )
                    quote = f"🐱 {self.quote}"
            else:
                if self.serious_mode:
                    controls = (
                        "↑↓ Select  ENTER Play  D Remove  J/K Move  C Clear  "
                        "W Save .m3u  O Load .m3u  Q Library  X Quit"
                    )
                    quote = ""
                else:
                    controls = (
                        "↑↓ Choose  ENTER Devour  D Yeet  J/K Rearrange  C Spill  "
                        "W Bury .m3u  O Dig up .m3u  Q Nest  X Escape"
                    )
                    quote = f"🐱 {self.quote}"

            if self.maximum_meow and quote:
                quote = f"🐱 MAXIMUM MEOW: {self.quote} 🐾♫🐾"

            try:
                if quote:
                    stdscr.addstr(
                        height - 3,
                        1,
                        quote[:width - 2],
                        curses.A_DIM
                    )
                stdscr.addstr(
                    height - 2,
                    1,
                    controls[:width - 2],
                    curses.A_DIM
                )
            except curses.error:
                pass

            stdscr.refresh()

            if self.current is not None and not self.repeat:
                eof = self.mpv.get_property("eof-reached")
                if eof:
                    self.next_song(automatic=True)

            try:
                if self.search_active:
                    key = stdscr.get_wch()
                else:
                    key = stdscr.getch()
            except curses.error:
                continue

            if key == -1:
                continue

            if self.search_active:
                self.handle_search_key(key)
                continue

            if key in (ord("x"), ord("X")):
                self.set_status(
                    "Quitting.",
                    "Escaping before the cat notices..."
                )
                break

            if key in (ord("q"), ord("Q")):
                self.view = (
                    "stash" if self.view == "library" else "library"
                )
                if self.view == "stash":
                    self.set_status(
                        "Opened queue.",
                        "Opened THE CATNIP STASH."
                    )
                else:
                    self.set_status(
                        "Returned to library.",
                        "Back to the Music Nest."
                    )
                continue

            if key == ord(" "):
                paused = self.mpv.toggle_pause()
                if paused:
                    self.set_status(
                        "Paused.",
                        "Pawsed. The cat is loafing."
                    )
                else:
                    self.set_status(
                        "Resumed.",
                        "Purr resumed. The loaf has awakened."
                    )
                continue

            if key == curses.KEY_RIGHT:
                self.mpv.seek(5)
                self.set_status(
                    "Seeked forward 5 seconds.",
                    "Scritched 5 seconds into the future."
                )
                continue

            if key == curses.KEY_LEFT:
                self.mpv.seek(-5)
                self.set_status(
                    "Seeked backward 5 seconds.",
                    "Backtracked 5 seconds on tiny paws."
                )
                continue

            if key in (ord("n"), ord("N")):
                self.next_song()
                continue

            if key in (ord("p"), ord("P")):
                self.previous_song()
                continue

            if key in (ord("+"), ord("=")):
                self.update_volume(5)
                continue

            if key == ord("-"):
                self.update_volume(-5)
                continue

            if key in (ord("s"), ord("S")):
                self.set_shuffle_enabled(not self.shuffle)
                remaining = len(self.shuffle_bag)
                self.set_status(
                    (
                        f"Shuffle {'enabled' if self.shuffle else 'disabled'}"
                        + (
                            f" with {remaining} track(s) in the bag."
                            if self.shuffle
                            else "."
                        )
                    ),
                    (
                        f"Pounce Mode {'ENGAGED' if self.shuffle else 'disengaged'}"
                        + (
                            f" — {remaining} meow(s) in the Pounce Bag."
                            if self.shuffle
                            else "."
                        )
                    )
                )
                continue

            if key in (ord("r"), ord("R")):
                self.repeat = not self.repeat
                self.mpv.set_repeat(self.repeat)
                self.set_status(
                    f"Repeat {'enabled' if self.repeat else 'disabled'}.",
                    f"Tail-Chase {'ENGAGED' if self.repeat else 'disengaged'}."
                )
                continue

            if self.view == "library":
                visible = self.ordered_library_indices()

                if key == curses.KEY_UP and visible:
                    self.selected = max(0, self.selected - 1)
                elif key == curses.KEY_DOWN and visible:
                    self.selected = min(
                        len(visible) - 1,
                        self.selected + 1
                    )
                elif key in (10, 13, curses.KEY_ENTER):
                    self.activate_library_selection()
                    library_scroll = 0
                elif key in (ord("f"), ord("F")):
                    self.toggle_selected_pawmark()
                elif key in (ord("b"), ord("B"), curses.KEY_BACKSPACE, 127, 8):
                    if self.go_back_library():
                        library_scroll = 0
                elif key in (ord("a"), ord("A")):
                    self.add_selected_to_stash()
                elif key == ord("/"):
                    self.search_active = True
                    self.search_query = ""
                    self.selected = 0
                    self.set_status(
                        (
                            "Type to search tags and paths. "
                            "Enter keeps filter; Esc clears it."
                        ),
                        (
                            "Sniff tags, albums, artists, and folders. "
                            "Enter locks scent; Esc forgets it."
                        )
                    )
                elif key == 27 and self.search_query:
                    self.search_query = ""
                    self.selected = 0
                    self.set_status(
                        "Search cleared.",
                        "Scent trail cleared."
                    )
                elif key == ord("\t"):
                    self.cycle_library_view()
                    library_scroll = 0
                elif key in (
                    ord("1"),
                    ord("2"),
                    ord("3"),
                    ord("4"),
                    ord("5"),
                    ord("6"),
                ):
                    self.select_library_view(
                        LIBRARY_VIEWS[int(chr(key)) - 1]
                    )
                    library_scroll = 0

            else:
                if key == curses.KEY_UP and self.catnip_stash:
                    self.stash_selected = max(
                        0,
                        self.stash_selected - 1
                    )
                elif key == curses.KEY_DOWN and self.catnip_stash:
                    self.stash_selected = min(
                        len(self.catnip_stash) - 1,
                        self.stash_selected + 1
                    )
                elif key in (10, 13, curses.KEY_ENTER):
                    self.play_stash_position(self.stash_selected)
                elif key in (ord("d"), ord("D")):
                    self.remove_from_stash()
                elif key in (ord("k"), ord("K")):
                    self.move_stash_item(-1)
                elif key in (ord("j"), ord("J")):
                    self.move_stash_item(1)
                elif key in (ord("c"), ord("C")):
                    self.clear_stash()
                elif key in (ord("w"), ord("W")):
                    default = str(
                        self.music_dir / "catnip-stash.m3u"
                    )
                    path = self.prompt_path(
                        stdscr,
                        self.text(
                            "Save queue playlist",
                            "Bury Catnip Stash"
                        ),
                        default,
                    )
                    self.save_stash(path)
                elif key in (ord("o"), ord("O")):
                    default = str(
                        self.music_dir / "catnip-stash.m3u"
                    )
                    path = self.prompt_path(
                        stdscr,
                        self.text(
                            "Load queue playlist",
                            "Dig up Catnip Stash"
                        ),
                        default,
                    )
                    self.load_stash(path)

        self.persist_state(force=True)
        self.sync_mpris(force=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "MeowPlayer — a cat-themed terminal music player powered by mpv."
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"MeowPlayer {__version__}",
    )
    parser.add_argument(
        "music_dir",
        nargs="?",
        default=None,
        help=(
            "music directory to scan recursively "
            "(default: ~/Music, or ~/storage/music in Termux)"
        )
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--serious-mode",
        action="store_true",
        help="disable cat jokes and use conventional UI labels"
    )
    mode.add_argument(
        "--maximum-meow",
        action="store_true",
        help="enable maximum feline energy"
    )

    parser.add_argument(
        "--no-mpris",
        action="store_true",
        help="disable MPRIS/D-Bus integration for this run"
    )
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="do not restore the previous playback session"
    )
    parser.add_argument(
        "--rebuild-catalog",
        action="store_true",
        help="discard cached metadata for this library and rebuild it"
    )

    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()

    configured_music_dir = config.get("music_dir")
    music_dir = (
        Path(args.music_dir).expanduser()
        if args.music_dir
        else (
            Path(configured_music_dir).expanduser()
            if configured_music_dir
            else _default_music_dir()
        )
    )

    if not music_dir.exists():
        print(_missing_music_dir_message(music_dir))
        sys.exit(1)

    config["music_dir"] = str(music_dir.resolve())
    save_config(config)

    state = load_state()
    mpris_enabled = (
        bool(config.get("mpris_enabled", True))
        and not args.no_mpris
    )
    restore_session = (
        bool(config.get("restore_session", True))
        and not args.no_restore
    )

    try:
        player = MeowPlayer(
            music_dir,
            serious_mode=args.serious_mode,
            maximum_meow=args.maximum_meow,
            saved_state=state,
            restore_session=restore_session,
            mpris_enabled=mpris_enabled,
            rebuild_catalog=args.rebuild_catalog,
        )
    except FileNotFoundError:
        print(
            "MPV was not found.\n"
            + _platform_install_hint()
        )
        sys.exit(1)

    if not player.songs:
        message = f"No supported music files found in:\n{music_dir}"
        if not args.serious_mode:
            message += (
                "\n\nThe cat searched the entire nest. No tunes. :<"
            )
        print(message)
        player.shutdown()
        sys.exit(0)

    try:
        curses.wrapper(player.run)
    finally:
        player.shutdown()


if __name__ == "__main__":
    main()
