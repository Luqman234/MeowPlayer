#!/usr/bin/env python3

import argparse
import curses
import json
import logging
import os
import queue
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

from album_art import AlbumArtManager
from bad_larry import (
    DANGEROUS_DISMISS_PHRASE,
    PlaybackSaboteur,
    apology_matches,
    confirm_dangerous_cat,
)
from bad_larry_math import QUANTUM_EXAM_SECONDS, QUANTUM_FINAL_EXAM
from lyrics_support import LyricsManager
from library_watcher import LibraryWatcher
from meow_catalog import LibraryCatalog
from meow_smart import (
    build_smart_playlists,
    load_custom_mix_definitions,
)
from meow_logging import (
    configure_debug_logging,
    mpv_debug_log_path,
    shutdown_debug_logging,
)
from meow_persistence import (
    load_config,
    load_state,
    save_config,
    save_state,
    smart_mixes_path,
)
from mpris_support import MPRISBridge
from online_metadata import (
    OnlineMetadataManager,
    merge_missing_metadata,
    metadata_lookup_due,
    needs_online_metadata,
)
from visualizer import AudioVisualizer
from settings_nest import (
    SETTINGS_SPECS,
    adjust_setting_value,
    format_setting_value,
    normalize_setting_value,
)
from youtube_online import (
    YouTubeBrowseSession,
    YouTubeCatalog,
    YouTubeDownloadSession,
    YouTubePlaylist,
    YouTubeStreamResolver,
    YouTubeSearchSession,
    network_subprocess_env,
    normalize_youtube_search,
)


__version__ = "0.18.0"


LOGGER = logging.getLogger("meowplayer")
MPV_LOGGER = logging.getLogger("meowplayer.mpv")


SUPPORTED_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".opus",
    ".wav", ".m4a", ".aac", ".wma"
}
ONLINE_RETRY_GUARD_SECONDS = 8.0

LIBRARY_VIEWS = (
    "songs",
    "artists",
    "albums",
    "folders",
    "pawmarks",
    "history",
    "smart",
)
VIEW_LABELS = {
    "songs": ("Songs", "Songs"),
    "artists": ("Artists", "Artists"),
    "albums": ("Albums", "Albums"),
    "folders": ("Folders", "Nests"),
    "pawmarks": ("Favorites", "Pawmarks"),
    "history": ("Listening History", "Purr History"),
    "smart": ("Smart Playlists", "Smart Mixes"),
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
    "The cat has reviewed your bitrate and refuses to elaborate.",
    "Please do not feed the SQLite database after midnight.",
    "This FFT has been stared at intensely. Results inconclusive.",
    "The cat says gapless playback tastes smoother.",
    "D-Bus has been bapped. It appears to still function.",
    "Your music library has passed the sniff test.",
    "The cat has unionized. Demands include more scritches.",
    "No, the cat does not know why that file is tagged 'Unknown Artist'.",
    "One does not simply empty The Catnip Stash.",
    "The terminal is warm. This is now legally a cat bed.",
    "ReplayGain: because apparently the cat has standards.",
    "The cat has read the documentation. This changes nothing.",
    "The cat has discovered Unicode stars and become judgmental.",
    "The album art has been inspected for legally sufficient rectangles.",
    "The cat insists the lyrics are about it. Evidence remains weak.",
    "One paw on the keyboard is apparently a valid UI event.",
    "Your queue has developed a small but manageable ecosystem.",
    "The visualizer is expensive string wiggling. The cat approves.",
    "SQLite remembers. The cat absolutely does not.",
    "Five stars were found in Unicode. Authority has been abused.",
    "The cat has outsourced missing tags to MusicBrainz.",
    "Unknown Artist has been placed under investigation.",
    "The metadata cat has returned from the internet with paperwork.",
]

CAT_INCIDENTS = (
    "sat directly on the play button and is pretending it was intentional.",
    "attempted to eat the waveform. The waveform survived.",
    "filed a bug report against gravity.",
    "opened /dev/null and stared into the abyss.",
    "bapped D-Bus once. No witnesses came forward.",
    "inspected SQLite by lying on top of it.",
    "declared the current album legally part of its territory.",
    "mistook the spectrum visualizer for a tiny fence and attacked it.",
    "moved absolutely nothing, then demanded credit for optimization.",
    "is conducting a surprise audit of The Catnip Stash.",
    "has entered the server room despite there being no server room.",
    "briefly became root in spirit only.",
    "found one byte under the sofa. Ownership remains disputed.",
    "pressed a key nobody mapped. Somehow nothing exploded.",
    "has determined that 100% volume is an indoor voice.",
    "gave the current track one star, then knocked the scorecard off the desk.",
    "attempted to climb into the album art. Perspective remains confusing.",
    "misheard the lyrics and is now confidently singing the wrong song.",
    "has begun rating every silence between tracks.",
    "found five Unicode stars and immediately formed a review board.",
    "sat on the right half of the split view and called it usability testing.",
    "declared the lyrics panel a legally protected sunbeam.",
)

PET_REACTIONS = (
    "purred with suspiciously high clock stability.",
    "accepted the scritch. Latency improved by an unverifiable 0.0001 ms.",
    "leaned into the scritch and nearly fell off the terminal.",
    "has forgiven exactly one software bug.",
    "made a tiny 'mrrp' noise. Engineering productivity increased.",
    "approved the current track by closing both eyes.",
    "received affection and immediately demanded another interrupt.",
    "is now emotionally cached.",
    "has started purring in semver.",
    "accepted the scritch and closed one unresolved issue.",
    "bapped the rating system and accidentally gave you five stars.",
)

RATING_REACTIONS = {
    0: (
        "The scorecard has been shredded. This track is officially unjudged.",
        "The cat has recused itself from musical criticism.",
    ),
    1: (
        "One star. The cat stared at the speaker and slowly left the room.",
        "The cat requests that the waveform explain itself.",
    ),
    2: (
        "Two stars. The cat has heard worse and refuses to provide examples.",
        "Two stars. One ear moved. No further praise was authorized.",
    ),
    3: (
        "Three stars. The cat remains cautiously seated.",
        "Three stars. Acceptable purring conditions have been detected.",
    ),
    4: (
        "Four stars. One ear has perked up with measurable enthusiasm.",
        "Four stars. The cat has stopped pretending not to enjoy it.",
    ),
    5: (
        "FIVE STARS. The cat has declared this legally excellent.",
        "Five stars. The track has passed the extremely unofficial sniff test.",
    ),
}

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
    "Screaming": (
        " /\\_/\\",
        r"( O.O )",
        r" > !!! <",
    ),
    "Whispering": (
        " /\\_/\\",
        r"( o.o )",
        r" > . <  pspsps",
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


def _prompt_input_window(value, width):
    """Return the visible tail of an unbounded prompt buffer.

    Terminal width controls presentation only. It must never become the
    maximum query length, especially on narrow Termux screens.
    """
    value = str(value or "")
    width = max(1, int(width))
    if len(value) <= width:
        return value
    if width == 1:
        return value[-1:]
    return "<" + value[-(width - 1):]


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


def build_mpv_command(
    socket_path,
    gapless_mode="weak",
    replaygain_mode="track",
    replaygain_preamp=0.0,
    debug_log_path=None,
):
    gapless_mode = (
        gapless_mode
        if gapless_mode in {"no", "weak", "yes"}
        else "weak"
    )
    replaygain_mode = (
        replaygain_mode
        if replaygain_mode in {"no", "track", "album"}
        else "track"
    )

    try:
        replaygain_preamp = float(replaygain_preamp)
    except (TypeError, ValueError):
        replaygain_preamp = 0.0

    command = [
        "mpv",
        "--no-video",
        "--idle=yes",
        "--keep-open=yes",
        "--really-quiet",
        f"--gapless-audio={gapless_mode}",
        f"--replaygain={replaygain_mode}",
        f"--replaygain-preamp={replaygain_preamp}",
        "--replaygain-clip=no",
        "--ytdl=yes",
        "--ytdl-format=bestaudio/best",
        f"--input-ipc-server={socket_path}",
    ]

    if debug_log_path:
        command.extend([
            f"--log-file={Path(debug_log_path).expanduser()}",
            "--msg-level=all=v",
        ])

    return command


class MPVController:
    def __init__(
        self,
        gapless_mode="weak",
        replaygain_mode="track",
        replaygain_preamp=0.0,
        debug_log_path=None,
        network_resolver_workaround=False,
    ):
        self.socket_path = os.path.join(
            tempfile.gettempdir(),
            f"meowplayer-{os.getpid()}.sock"
        )

        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

        self.debug_log_path = (
            Path(debug_log_path).expanduser()
            if debug_log_path
            else None
        )
        command = build_mpv_command(
            self.socket_path,
            gapless_mode=gapless_mode,
            replaygain_mode=replaygain_mode,
            replaygain_preamp=replaygain_preamp,
            debug_log_path=self.debug_log_path,
        )
        MPV_LOGGER.debug(
            "Starting mpv pid-pending socket=%s debug_log=%s",
            self.socket_path,
            self.debug_log_path,
        )
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=network_subprocess_env(
                resolver_workaround=network_resolver_workaround,
            ),
        )
        MPV_LOGGER.info("mpv started pid=%s", self.process.pid)

        socket_ready = False
        for _ in range(50):
            if os.path.exists(self.socket_path):
                socket_ready = True
                break
            time.sleep(0.02)

        self._init_ipc()
        if not socket_ready:
            MPV_LOGGER.warning("mpv IPC socket did not appear within startup window")

    OBSERVED_PROPERTIES = (
        "pause", "idle-active", "path", "time-pos", "duration", "volume",
        "eof-reached",
    )

    def _init_ipc(self):
        self._ipc_socket = None
        self._ipc_lock = threading.RLock()
        self._ipc_request_id = 0
        self._ipc_timeout = 0.75
        self._pending = {}
        self._properties = {}
        self._reader = None
        self._readers = []
        self._closing = False
        self._stats_started = time.monotonic()
        self._commands = 0
        self._events = 0
        self.playback_events = {}

    def _close_ipc(self, expected=None):
        with self._ipc_lock:
            sock = self._ipc_socket
            if expected is not None and sock is not expected:
                return
            self._ipc_socket = None
            self._properties.clear()
            for waiter, box in self._pending.values():
                waiter.set()
            self._pending.clear()
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()

    def _send_ipc(self, sock, command):
        self._ipc_request_id += 1
        self._commands += 1
        request_id = self._ipc_request_id
        sock.sendall((json.dumps({
            "command": command, "request_id": request_id,
        }) + "\n").encode("utf-8"))
        return request_id

    def _ensure_ipc(self):
        # Called under the send/state lock; only the reader receives bytes.
        if self._closing:
            raise ConnectionError("mpv controller closed")
        if self._ipc_socket is not None:
            return self._ipc_socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._ipc_timeout)
        try:
            sock.connect(self.socket_path)
        except OSError:
            sock.close()
            raise
        self._ipc_socket = sock
        self._properties.clear()
        self._reader = threading.Thread(
            target=self._read_ipc, args=(sock,), name="mpv-ipc", daemon=True,
        )
        self._readers = [r for r in self._readers if r.is_alive()]
        self._readers.append(self._reader)
        self._reader.start()
        for index, name in enumerate(self.OBSERVED_PROPERTIES):
            self._send_ipc(sock, ["observe_property", index + 1, name])
        MPV_LOGGER.debug("Persistent mpv IPC connection established")
        return sock

    def _read_ipc(self, sock):
        buffer = b""
        try:
            while not self._closing:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    try:
                        message = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        MPV_LOGGER.warning("Ignoring malformed mpv IPC line")
                        continue
                    if not isinstance(message, dict):
                        continue
                    with self._ipc_lock:
                        if sock is not self._ipc_socket:
                            return
                        event = message.get("event")
                        if event:
                            self._events += 1
                            if event == "property-change":
                                name, value = message.get("name"), message.get("data")
                                self._properties[name] = value
                                if name == "time-pos" and isinstance(value, (int, float)) and value > 0:
                                    self.playback_events.setdefault("first-nonzero-time-pos", time.monotonic())
                            else:
                                if event == "start-file":
                                    # A prior entry's end/error may arrive after
                                    # loadfile was sent but before this start.
                                    self.playback_events.clear()
                                self.playback_events[event] = time.monotonic()
                                if event == "end-file":
                                    self.playback_events["end-reason"] = message.get("reason")
                                MPV_LOGGER.debug("mpv event=%s monotonic=%.6f", event, time.monotonic())
                        pending = self._pending.pop(message.get("request_id"), None)
                        if pending:
                            waiter, box = pending
                            box.append(message)
                            waiter.set()
        except OSError:
            pass
        finally:
            self._close_ipc(expected=sock)

    def command(self, *args):
        waiter, box = threading.Event(), []
        with self._ipc_lock:
            try:
                sock = self._ensure_ipc()
                # Register before releasing the lock to the reader.
                command = (
                    args[0] if len(args) == 1 and isinstance(args[0], dict)
                    else list(args)
                )
                request_id = self._send_ipc(sock, command)
                self._pending[request_id] = (waiter, box)
            except OSError:
                self._close_ipc()
                return None
        if not waiter.wait(self._ipc_timeout):
            with self._ipc_lock:
                self._pending.pop(request_id, None)
            self._close_ipc(expected=sock)
        return box[0] if box else None

    def get_property(self, name):
        if name in self.OBSERVED_PROPERTIES:
            with self._ipc_lock:
                try:
                    self._ensure_ipc()
                except OSError:
                    return None
                return self._properties.get(name)
        # Playlist mutation safety requires fresh replies, not stale observations.
        response = self.command("get_property", name)
        if response and response.get("error") == "success":
            return response.get("data")
        return None

    def ipc_stats(self):
        elapsed = max(0.001, time.monotonic() - self._stats_started)
        return {"commands": self._commands, "events": self._events,
                "duration": elapsed, "commands_per_second": self._commands / elapsed,
                "events_per_second": self._events / elapsed}

    def playback_snapshot(self):
        with self._ipc_lock:
            return dict(self.playback_events)

    def begin_load(self):
        with self._ipc_lock:
            self.playback_events.clear()
            for name in ("path", "time-pos", "duration", "eof-reached"):
                self._properties.pop(name, None)

    def load_stream(self, stream):
        self.begin_load()
        # Named arguments work both before and after mpv 0.38's index addition.
        headers = ",".join(
            (key + ": " + value).replace("\\", "\\\\").replace(",", "\\,")
            for key, value in stream.headers.items()
        )
        return self.command({"name": "loadfile", "url": stream.url,
                             "flags": "replace", "options": {
                                 "ytdl": "no", "http-header-fields": headers}})

    def set_property(self, name, value):
        self.command("set_property", name, value)

    def set_repeat(self, enabled):
        self.set_property("loop-file", "inf" if enabled else "no")

    def load(self, filename):
        self.begin_load()
        MPV_LOGGER.info("loadfile replace: %s", str(filename).split("?", 1)[0])
        self.command("loadfile", str(filename), "replace")

    def append(self, filename):
        MPV_LOGGER.debug("loadfile append: %s", filename)
        return self.command("loadfile", str(filename), "append")

    def advance_playlist(self):
        try:
            current = int(self.get_property("playlist-current-pos"))
            count = int(self.get_property("playlist-count"))
        except (TypeError, ValueError):
            return None

        target = current + 1
        if current < 0 or target >= count:
            return None

        return self.command("playlist-play-index", target)

    def clear_future_playlist(self):
        try:
            current = int(self.get_property("playlist-current-pos"))
            count = int(self.get_property("playlist-count"))
        except (TypeError, ValueError):
            return False

        # During loadfile/playlist transitions mpv can temporarily report -1.
        # That is not a safe moment to mutate the future playlist.
        if current < 0:
            MPV_LOGGER.debug(
                "Deferring future-playlist cleanup while current-pos=%s "
                "playlist-count=%s",
                current,
                count,
            )
            return False

        for index in range(count - 1, current, -1):
            response = self.command("playlist-remove", index)
            if not response or response.get("error") != "success":
                return False

        return True

    def trim_playlist_before_current(self):
        try:
            current = int(self.get_property("playlist-current-pos"))
        except (TypeError, ValueError):
            return

        # -1 means mpv is between playlist entries / still loading.
        if current < 0:
            return

        while current > 0:
            self.command("playlist-remove", 0)
            current -= 1

    def prime_next(self, filename):
        # Never append while mpv reports playlist-current-pos == -1.
        # Appending in that transition window can leave mpv stranded between
        # entries and can accumulate duplicate reservations.
        if not self.clear_future_playlist():
            return False

        response = self.append(filename)
        return bool(response and response.get("error") == "success")

    def current_path(self):
        # The gapless scheduler uses this as a mutation barrier. An observed
        # path can lag a playlist transition, so preserve its synchronous read.
        response = self.command("get_property", "path")
        value = response.get("data") if response and response.get("error") == "success" else None
        return str(value) if value else None

    def wait_for_path(self, filename, timeout=0.35):
        try:
            expected = Path(filename).expanduser().resolve()
        except (OSError, RuntimeError, TypeError):
            return False

        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            current = self.current_path()
            if current:
                try:
                    if Path(current).expanduser().resolve() == expected:
                        return True
                except (OSError, RuntimeError, TypeError):
                    pass
            time.sleep(0.01)

        return False

    def pause(self):
        self.set_property("pause", True)

    def play(self):
        self.set_property("pause", False)

    def toggle_pause(self):
        paused = self.get_property("pause")
        self.set_property("pause", not bool(paused))
        return not bool(paused)

    def stop(self):
        MPV_LOGGER.info("stop")
        self.command("stop")

    def seek(self, seconds):
        MPV_LOGGER.debug("seek relative: %s", seconds)
        self.command("seek", seconds, "relative")

    def seek_absolute(self, seconds):
        MPV_LOGGER.debug("seek absolute: %s", seconds)
        self.command("seek", max(0.0, seconds), "absolute", "exact")

    def quit(self):
        MPV_LOGGER.info("mpv shutdown requested")
        try:
            self.command("quit")
        except Exception:
            pass
        finally:
            self._close_ipc()

        self._closing = True
        for reader in self._readers:
            reader.join(timeout=1.0)
        MPV_LOGGER.info("IPC_STATS %s", self.ipc_stats())

        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1.0)
        except OSError:
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
        album_art_enabled=True,
        gapless_mode="weak",
        replaygain_mode="track",
        replaygain_preamp=0.0,
        lyrics_enabled=True,
        lyrics_online_enabled=True,
        online_metadata_enabled=True,
        visualizer_enabled=True,
        filesystem_watch_enabled=True,
        cat_chaos_mode=None,
        youtube_enabled=False,
        debug_log_path=None,
        mpv_log_path=None,
        app_config=None,
    ):
        self.music_dir = Path(music_dir).expanduser().resolve()
        self.debug_log_path = (
            Path(debug_log_path).expanduser()
            if debug_log_path
            else None
        )
        self.mpv_log_path = (
            Path(mpv_log_path).expanduser()
            if mpv_log_path
            else None
        )
        self.serious_mode = serious_mode
        self.maximum_meow = maximum_meow
        self.cat_chaos_mode = (
            cat_chaos_mode
            if cat_chaos_mode in {"bad-bad", "very-bad", "dangerous"}
            else None
        )
        self.playback_saboteur = PlaybackSaboteur(self.cat_chaos_mode)
        self.youtube = YouTubeCatalog(enabled=youtube_enabled)
        LOGGER.info(
            "Initializing player music_dir=%s youtube=%s serious=%s "
            "maximum_meow=%s cat_chaos=%s",
            self.music_dir,
            youtube_enabled,
            serious_mode,
            maximum_meow,
            self.cat_chaos_mode,
        )
        self.stream_resolver = (
            YouTubeStreamResolver(self.youtube.executable)
            if self.youtube.available else None
        )
        self.youtube_search_session = None
        self.youtube_download_session = None
        self.youtube_download_track = None
        self._prefetch_selection = None
        self._online_future = None
        self._online_retry = 0
        self._online_path = None
        self.youtube_results = []
        self.youtube_selected = 0
        self.youtube_query = ""
        self.youtube_search_mode = "all"
        self.creator_session = None
        self.creator_name = ""
        self.creator_channel_url = ""
        self.creator_level = "menu"
        self.creator_items = []
        self.creator_selected = 0
        self.creator_playlist = None
        self.online_current = None
        self.online_load_state = "idle"
        self.online_load_started_at = 0.0
        self.saved_state = saved_state or {}
        self.app_config = dict(app_config or {})
        self.settings_selected = 0
        self.settings_return_view = "library"
        self.restore_session_enabled = restore_session
        self.mpris_enabled = mpris_enabled and not _is_termux()
        self.album_art = AlbumArtManager(
            enabled=album_art_enabled and not _is_termux()
        )
        self.lyrics = LyricsManager(
            enabled=lyrics_enabled,
            online_enabled=lyrics_online_enabled,
        )
        self.visualizer = AudioVisualizer(enabled=visualizer_enabled)
        self.online_metadata = OnlineMetadataManager(
            enabled=online_metadata_enabled
        )
        self.current_lyrics = None
        self.lyrics_track_index = None
        self.lyrics_follow = True
        self.lyrics_scroll = 0
        self.previous_view = "library"
        self.custom_mix_definitions = []
        self.custom_mix_errors = []
        self.gapless_mode = (
            gapless_mode
            if gapless_mode in {"no", "weak", "yes"}
            else "weak"
        )
        self.replaygain_mode = (
            replaygain_mode
            if replaygain_mode in {"no", "track", "album"}
            else "track"
        )
        try:
            self.replaygain_preamp = float(replaygain_preamp)
        except (TypeError, ValueError):
            self.replaygain_preamp = 0.0

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
        self.smart_playlist_key = None
        self.song_lookup = {
            song.resolve(): index for index, song in enumerate(self.songs)
        }
        self.metadata_lookup_queued = (
            self.queue_missing_metadata_enrichment()
        )
        self.reload_custom_smart_mixes(silent=True)

        self.selected = 0
        self.stash_selected = 0
        self.current = None
        self.history = []
        self.shuffle_bag = []
        self.playback_sequence = []
        self.gapless_next_index = None
        self._awaiting_mpv_path = False

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
        self.playback_sequence = self.restore_saved_index_list(
            self.saved_state.get("playback_sequence", []),
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

        initial_serious += (
            f" Audio: gapless={self.gapless_mode}, "
            f"ReplayGain={self.replaygain_mode}."
        )
        initial_cat += (
            f" Audio paws: gapless={self.gapless_mode}, "
            f"ReplayGain={self.replaygain_mode}."
        )
        if self.playback_saboteur.enabled:
            initial_cat += (
                f" {self.playback_saboteur.label} has playback access."
            )
        if self.metadata_lookup_queued:
            initial_serious += (
                f" Online metadata queued for "
                f"{self.metadata_lookup_queued} incomplete track(s)."
            )
            initial_cat += (
                f" The metadata cat is sniffing the internet for "
                f"{self.metadata_lookup_queued} incomplete meow(s)."
            )
        if self.youtube.enabled:
            if self.youtube.available:
                initial_serious += " Internet Nest ready."
                initial_cat += " The internet cat found yt-dlp and opened the hatch."
            else:
                initial_serious += (
                    " Internet Nest unavailable: yt-dlp was not found."
                )
                initial_cat += (
                    " The internet cat cannot find yt-dlp and is staring "
                    "accusingly at PATH."
                )
        if self.debug_log_path is not None:
            initial_serious += f" Debug log: {self.debug_log_path}."
            initial_cat += f" Debug paws: {self.debug_log_path}."

        self.status_message = self.text(initial_serious, initial_cat)
        LOGGER.debug("Initial status: %s", self.status_message)
        self.quote = random.choice(CAT_QUOTES)
        now = time.monotonic()
        self.last_quote_change = now
        self.scritches = 0
        self.cat_incident = None
        self.cat_incident_until = 0.0
        self.next_cat_incident_at = now + random.uniform(35.0, 70.0)
        self.tail_frame = 0
        self.last_state_save = 0.0
        self.last_mpris_sync = 0.0
        self.external_actions = queue.SimpleQueue()
        self.remote_quit_requested = False
        self.library_watcher = LibraryWatcher(
            self.music_dir,
            SUPPORTED_EXTENSIONS,
            enabled=filesystem_watch_enabled,
        )

        self.mpv = MPVController(
            gapless_mode=self.gapless_mode,
            replaygain_mode=self.replaygain_mode,
            replaygain_preamp=self.replaygain_preamp,
            debug_log_path=self.mpv_log_path,
            network_resolver_workaround=self.youtube.enabled,
        )
        self.mpv.set_property("volume", self.volume)
        self.mpv.set_repeat(self.repeat)

        if self.restore_session_enabled:
            self.restore_session(self.saved_state)

        self.sanitize_shuffle_bag()
        if self.shuffle:
            if not self.restore_session_enabled:
                self.refill_shuffle_bag()
            elif not self.shuffle_bag and len(self.songs) > 1:
                self.refill_shuffle_bag()

        self.library_watcher.start()

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

    def shuffle_pool(self):
        if self.playback_sequence:
            return list(self.playback_sequence)
        return list(range(len(self.songs)))

    def sanitize_shuffle_bag(self):
        cleaned = []
        seen = set()
        pool = set(self.shuffle_pool())

        for index in self.shuffle_bag:
            if not isinstance(index, int):
                continue
            if index < 0 or index >= len(self.songs):
                continue
            if index not in pool:
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
            for index in self.shuffle_pool()
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

        self.prime_gapless_next()

    def peek_next_index(self):
        if not self.songs or self.current is None or self.repeat:
            return None

        if self.catnip_stash:
            return self.catnip_stash[0]

        if self.shuffle:
            pool = self.shuffle_pool()
            if not pool:
                return None

            if len(pool) == 1:
                return pool[0]

            self.sanitize_shuffle_bag()
            if not self.shuffle_bag:
                self.refill_shuffle_bag()

            return self.shuffle_bag[-1] if self.shuffle_bag else pool[0]

        if self.playback_sequence:
            if self.current in self.playback_sequence:
                position = self.playback_sequence.index(self.current)
                return self.playback_sequence[
                    (position + 1) % len(self.playback_sequence)
                ]
            return self.playback_sequence[0]

        return (self.current + 1) % len(self.songs)

    def prime_gapless_next(self):
        # A manual loadfile replace is asynchronous inside mpv. Until mpv
        # reports the requested file as current, playlist-current-pos may be
        # -1. Mutating the playlist in that window can delete the song that is
        # still loading. Record the intended reservation, but defer actual
        # priming until sync_gapless_transition() confirms the current path.
        if self._awaiting_mpv_path:
            self.gapless_next_index = self.peek_next_index()
            return

        if (
            self.gapless_mode == "no"
            or self.current is None
            or self.repeat
        ):
            self.gapless_next_index = None
            try:
                self.mpv.clear_future_playlist()
            except AttributeError:
                pass
            return

        next_index = self.peek_next_index()
        self.gapless_next_index = next_index

        if next_index is None:
            self.mpv.clear_future_playlist()
            return

        self.mpv.trim_playlist_before_current()
        primed = self.mpv.prime_next(self.songs[next_index])
        if primed is False:
            # Keep the intended reservation, but require another stable-path
            # confirmation before trying to mutate mpv's playlist again.
            self._awaiting_mpv_path = True
            MPV_LOGGER.debug(
                "Deferred gapless reservation index=%s path=%s",
                next_index,
                self.songs[next_index],
            )

    def _consume_gapless_reservation(self, index):
        if self.catnip_stash and self.catnip_stash[0] == index:
            self.catnip_stash.pop(0)
            self.stash_selected = 0

        if self.shuffle and index in self.shuffle_bag:
            self.shuffle_bag.remove(index)

    def sync_gapless_transition(self):
        if (
            self.gapless_mode == "no"
            or self.current is None
        ):
            return False

        current_path = self.mpv.current_path()
        if not current_path:
            return False

        try:
            resolved = Path(current_path).expanduser().resolve()
        except (OSError, RuntimeError):
            return False

        mpv_index = self.song_lookup.get(resolved)
        if mpv_index is None:
            return False

        if self._awaiting_mpv_path:
            if mpv_index == self.current:
                self._awaiting_mpv_path = False
                self.prime_gapless_next()
            return False

        if mpv_index == self.current:
            return False

        departed = self.current
        self._consume_gapless_reservation(mpv_index)

        if departed is not None and departed != mpv_index:
            self.history.append(departed)
            if len(self.history) > 200:
                self.history.pop(0)

        self.current = mpv_index
        self.load_current_lyrics(mpv_index)

        if self.catalog is not None:
            self.catalog.record_play(self.songs[mpv_index])
            self.refresh_library_stats()

        ordered = self.ordered_library_indices()
        if mpv_index in ordered:
            self.selected = ordered.index(mpv_index)

        meta = self.meta(mpv_index)
        self.set_status(
            f"Gapless transition: {meta.artist_title}",
            f"The next meow landed without a gap: {meta.artist_title}"
        )

        self.mpv.trim_playlist_before_current()
        self.prime_gapless_next()
        self.sync_mpris(force=True)
        return True

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
        self.load_current_lyrics(index)
        self.mpv.pause()
        self.mpv.load(self.songs[index])
        self._awaiting_mpv_path = True
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
        self.prime_gapless_next()

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
            "playback_sequence": [
                str(self.songs[index].resolve())
                for index in self.playback_sequence
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
        active = self.has_active_track()
        idle = True
        paused = False
        position = 0.0
        duration = 0.0

        if active:
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

            if duration <= 0:
                duration = self.current_duration_fallback()

        if not active or idle:
            playback_status = "Stopped"
        elif paused:
            playback_status = "Paused"
        else:
            playback_status = "Playing"

        metadata = None
        if self.online_current is not None:
            track = self.online_current
            safe_id = "".join(
                char if char.isalnum() else "_"
                for char in track.video_id
            )
            metadata = {
                "track_id": (
                    f"/org/mpris/MediaPlayer2/track/youtube_{safe_id}"
                ),
                "title": track.title,
                "artist": track.artist,
                "album": "YouTube",
                "album_artist": track.artist,
                "genre": "YouTube",
                "art_url": track.thumbnail_url or None,
                "url": track.url,
                "length_us": int(max(0.0, duration) * 1_000_000),
            }
        elif self.current is not None:
            meta = self.meta(self.current)
            cover_path = (
                self.album_art.cover_for(self.songs[self.current])
                if self.album_art.enabled
                else None
            )
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
                "genre": meta.genre or None,
                "art_url": (
                    cover_path.resolve().as_uri()
                    if cover_path is not None
                    else None
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
            "has_track": active and not idle,
            "has_tracks": bool(
                self.songs or self.youtube_results or self.youtube.enabled
            ),
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
                if self.has_active_track():
                    self.mpv.pause()
            elif action == "play":
                if self.online_current is not None:
                    if bool(self.mpv.get_property("idle-active")):
                        self.play_online(self.online_current)
                    else:
                        self.mpv.play()
                elif self.current is None:
                    self.play_selected_library_song()
                elif bool(self.mpv.get_property("idle-active")):
                    self.play(
                        self.current,
                        record_history=False,
                        record_listen=False,
                        preserve_sequence=True,
                    )
                else:
                    self.mpv.play()
            elif action == "play_pause":
                if self.online_current is not None:
                    if bool(self.mpv.get_property("idle-active")):
                        self.play_online(self.online_current)
                    else:
                        self.mpv.toggle_pause()
                elif self.current is None:
                    self.play_selected_library_song()
                elif bool(self.mpv.get_property("idle-active")):
                    self.play(
                        self.current,
                        record_history=False,
                        record_listen=False,
                        preserve_sequence=True,
                    )
                else:
                    self.mpv.toggle_pause()
            elif action == "stop":
                if self.has_active_track():
                    self.mpv.stop()
                    if self.online_current is not None:
                        self._online_future = None
                        self.online_load_state = "idle"
            elif action == "seek" and self.has_active_track():
                self.mpv.seek(args[0])
                position = self.mpv.get_property("time-pos") or 0
                self.mpris.notify_seeked(float(position) * 1_000_000)
            elif action == "set_position" and self.has_active_track():
                self.mpv.seek_absolute(args[0])
                self.mpris.notify_seeked(args[0] * 1_000_000)
            elif action == "set_volume":
                self.set_volume_absolute(args[0] * 100.0)
            elif action == "set_shuffle":
                self.set_shuffle_enabled(args[0])
            elif action == "set_repeat":
                self.repeat = bool(args[0])
                self.mpv.set_repeat(self.repeat)
                self.prime_gapless_next()

        if handled:
            self.sync_mpris(force=True)

    def shutdown(self):
        LOGGER.info("Player shutdown starting")
        self.persist_state(force=True)
        self.playback_saboteur.dismiss(self)
        if self.youtube_search_session:
            self.youtube_search_session.close()
        if self.youtube_download_session:
            self.youtube_download_session.close()
        if self.creator_session:
            self.creator_session.close()
        if self.stream_resolver:
            self.stream_resolver.close()
        self.online_metadata.stop()
        self.mpris.stop()
        self.library_watcher.stop()
        self.album_art.clear(free_data=True)
        self.visualizer.stop()

        if self.catalog is not None:
            try:
                self.catalog.commit()
                self.catalog.close()
            except sqlite3.Error:
                pass
            self.catalog = None

        self.mpv.quit()
        LOGGER.info("Player shutdown complete")

    def text(self, serious, cat):
        return serious if self.serious_mode else cat

    def set_status(self, serious, cat):
        self.status_message = self.text(serious, cat)
        LOGGER.debug("status=%s", self.status_message)

    def open_settings_nest(self):
        if self.view != "settings":
            self.settings_return_view = self.view
        self.view = "settings"
        self.settings_selected = max(
            0,
            min(self.settings_selected, len(SETTINGS_SPECS) - 1),
        )
        self.set_status(
            "Opened settings.",
            "Opened the Settings Nest. Please do not let the cat edit JSON directly.",
        )

    def close_settings_nest(self):
        target = self.settings_return_view
        if target == "settings":
            target = "library"
        self.view = target
        self.set_status(
            "Settings saved.",
            "Settings Nest closed. The household rules have been filed under P for Paws.",
        )

    def setting_value(self, spec):
        return normalize_setting_value(
            spec,
            self.app_config.get(spec.key, spec.default),
        )

    def _persist_setting(self, spec, value):
        self.app_config[spec.key] = value
        saved = save_config(self.app_config)
        LOGGER.info(
            "Settings Nest changed key=%s value=%r saved=%s",
            spec.key,
            value,
            saved,
        )
        return saved

    def _apply_live_setting(self, spec, value):
        if not spec.live:
            return False

        key = spec.key
        if key == "gapless_mode":
            self.gapless_mode = value
            self.mpv.set_property("gapless-audio", value)
            self.prime_gapless_next()
        elif key == "replaygain_mode":
            self.replaygain_mode = value
            self.mpv.set_property("replaygain", value)
        elif key == "replaygain_preamp":
            self.replaygain_preamp = float(value)
            self.mpv.set_property("replaygain-preamp", float(value))
        elif key == "lyrics_enabled":
            self.lyrics.enabled = bool(value)
            if not value:
                self.current_lyrics = None
        elif key == "lyrics_online_enabled":
            self.lyrics.online_enabled = bool(value)
        elif key == "online_metadata_enabled":
            self.online_metadata.enabled = bool(value)
        elif key == "visualizer_enabled":
            self.visualizer.stop()
            self.visualizer = AudioVisualizer(enabled=bool(value))
        elif key == "album_art_enabled":
            self.album_art.clear(free_data=True)
            self.album_art = AlbumArtManager(
                enabled=bool(value) and not _is_termux()
            )
        elif key == "filesystem_watch_enabled":
            self.library_watcher.stop()
            self.library_watcher = LibraryWatcher(
                self.music_dir,
                SUPPORTED_EXTENSIONS,
                enabled=bool(value),
            )
            self.library_watcher.start()
        else:
            return False

        return True

    def change_selected_setting(self, direction=1, reset=False):
        if not SETTINGS_SPECS:
            return False

        self.settings_selected = max(
            0,
            min(self.settings_selected, len(SETTINGS_SPECS) - 1),
        )
        spec = SETTINGS_SPECS[self.settings_selected]
        old_value = self.setting_value(spec)
        new_value = (
            normalize_setting_value(spec, spec.default)
            if reset
            else adjust_setting_value(spec, old_value, direction)
        )

        if new_value == old_value:
            return False

        saved = self._persist_setting(spec, new_value)
        applied_live = self._apply_live_setting(spec, new_value)

        if not saved:
            self.set_status(
                f"Changed {spec.label}, but config could not be saved.",
                f"The cat changed {spec.cat_label}, then misplaced the config file.",
            )
        elif applied_live:
            self.set_status(
                f"{spec.label}: {format_setting_value(spec, new_value)} (live).",
                (
                    f"{spec.cat_label}: {format_setting_value(spec, new_value)}. "
                    "The cat applied it immediately."
                ),
            )
        else:
            self.set_status(
                (
                    f"{spec.label}: {format_setting_value(spec, new_value)} "
                    "(saved for next launch)."
                ),
                (
                    f"{spec.cat_label}: {format_setting_value(spec, new_value)}. "
                    "The cat wrote it down for the next summoning."
                ),
            )
        return True

    def has_active_track(self):
        return self.current is not None or self.online_current is not None

    def current_artist_title(self):
        if self.online_current is not None:
            return self.online_current.artist_title
        if self.current is not None:
            return self.meta(self.current).artist_title
        return ""

    def current_title(self):
        if self.online_current is not None:
            return self.online_current.title
        if self.current is not None:
            return self.meta(self.current).title
        return ""

    def current_duration_fallback(self):
        if self.online_current is not None:
            return float(self.online_current.duration or 0.0)
        if self.current is not None:
            return float(self.meta(self.current).duration or 0.0)
        return 0.0

    def cat_intercepts(self, action):
        return self.playback_saboteur.handle_user_action(self, action)

    def cat_chaos_summary(self):
        saboteur = self.playback_saboteur
        if not saboteur.enabled:
            return ""
        if saboteur.mode == "dangerous":
            return (
                f"BAD LARRY {saboteur.malice}% · "
                f"Human Authority {saboteur.human_authority}% · "
                f"Sabotages {saboteur.sabotage_count}"
            )
        return (
            f"{saboteur.label} · Malice {saboteur.malice}% · "
            f"Sabotages {saboteur.sabotage_count}"
        )

    def cat_mood(self):
        if not self.has_active_track():
            return "Waiting"

        paused = bool(self.mpv.get_property("pause"))
        if paused:
            return "Loafing"
        if self.volume >= 90:
            return "Screaming"
        if self.volume <= 10:
            return "Whispering"
        if self.repeat:
            return "Tail-Chasing"
        if self.shuffle:
            return "Zoomies"
        if self.catnip_stash:
            return "Guarding Catnip"
        return "Purring"

    def trigger_cat_incident(self, message=None, duration=8.0, now=None):
        if self.serious_mode:
            return False

        timestamp = time.monotonic() if now is None else float(now)
        self.cat_incident = message or random.choice(CAT_INCIDENTS)
        self.cat_incident_until = timestamp + max(1.0, float(duration))
        self.next_cat_incident_at = timestamp + random.uniform(45.0, 95.0)
        return True

    def maybe_trigger_cat_incident(self, now=None):
        if self.serious_mode:
            return False

        timestamp = time.monotonic() if now is None else float(now)

        if self.cat_incident is not None:
            if timestamp < self.cat_incident_until:
                return False
            self.cat_incident = None

        if timestamp < self.next_cat_incident_at:
            return False

        return self.trigger_cat_incident(now=timestamp)

    def cat_footer_message(self, now=None):
        if self.serious_mode:
            return ""

        timestamp = time.monotonic() if now is None else float(now)
        if (
            self.cat_incident is not None
            and timestamp < self.cat_incident_until
        ):
            return f"🚨 CAT INCIDENT: {self.cat_incident}"

        if self.cat_incident is not None:
            self.cat_incident = None

        return f"🐱 {self.quote}"

    def pet_cat(self):
        if self.serious_mode:
            self.set_status(
                "Mascot interaction unavailable in Serious Mode.",
                ""
            )
            return False

        self.scritches += 1

        if self.scritches % 10 == 0:
            reaction = (
                f"SCRITCH MILESTONE {self.scritches}: the cat has become "
                "too powerful to benchmark."
            )
        else:
            reaction = random.choice(PET_REACTIONS)

        self.trigger_cat_incident(
            f"SCRITCH #{self.scritches}: {reaction}",
            duration=7.0,
        )
        self.set_status(
            f"Cat interaction #{self.scritches}.",
            f"Scritch #{self.scritches} accepted. {reaction}"
        )
        return True

    def live_cat_mascot(self):
        if self.playback_saboteur.mode == "dangerous":
            return (
                " /\\_/\\",
                r"( O_O )",
                r" > ^ <  !!",
            )
        if self.playback_saboteur.mode == "very-bad":
            return (
                " /\\_/\\",
                r"( >.< )",
                r" > ~ <  ...",
            )
        if self.playback_saboteur.mode == "bad-bad":
            return (
                " /\\_/\\",
                r"( -_- )",
                r" > ~ <",
            )
        if self.maximum_meow:
            mood = self.cat_mood()
            middle = {
                "Waiting": r" ( =-.-=)   zZ",
                "Purring": r" ( =^.^=)   ♫",
                "Loafing": r" ( =-.-=)   ...",
                "Zoomies": r" ( =>.<=)   !!",
                "Tail-Chasing": r" ( =@.@=)   ↻",
                "Guarding Catnip": r" ( =o.o=)   ~",
                "Screaming": r" ( =O.O=)   !!!",
                "Whispering": r" ( =o.o=)   pspsps",
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

    def _paths_from_indices(self, indices):
        paths = []
        for index in indices:
            if not isinstance(index, int):
                continue
            if 0 <= index < len(self.songs):
                paths.append(str(self.songs[index].resolve()))
        return paths

    def _indices_from_paths(self, paths, unique=False, limit=None):
        indices = []
        seen = set()

        for raw_path in paths:
            try:
                path = Path(raw_path).expanduser().resolve()
            except (OSError, RuntimeError, TypeError):
                continue

            index = self.song_lookup.get(path)
            if index is None:
                continue
            if unique and index in seen:
                continue

            indices.append(index)
            seen.add(index)

        if limit is not None:
            indices = indices[-limit:]

        return indices

    def rescan_library(self, event_summary=None):
        old_paths = {
            str(song.resolve())
            for song in self.songs
        }
        current_path = (
            str(self.songs[self.current].resolve())
            if self.current is not None
            and 0 <= self.current < len(self.songs)
            else None
        )

        selected_song = self.selected_library_song()
        selected_path = (
            str(self.songs[selected_song].resolve())
            if selected_song is not None
            and 0 <= selected_song < len(self.songs)
            else None
        )

        stash_paths = self._paths_from_indices(self.catnip_stash)
        history_paths = self._paths_from_indices(self.history)
        bag_paths = self._paths_from_indices(self.shuffle_bag)
        sequence_paths = self._paths_from_indices(self.playback_sequence)

        if self.catalog is not None:
            try:
                self.catalog.commit()
                self.catalog.close()
            except sqlite3.Error:
                pass
            self.catalog = None

        self.catalog_error = None
        self.catalog_hits = 0
        self.catalog_refreshed = 0
        self.catalog_pruned = 0

        self.songs = self.find_songs()
        self.metadata = self.load_library_metadata(rebuild=False)
        self.library_stats = (
            self.catalog.play_stats()
            if self.catalog is not None
            else {}
        )
        self.song_lookup = {
            song.resolve(): index
            for index, song in enumerate(self.songs)
        }

        self.catnip_stash = self._indices_from_paths(stash_paths)
        self.history = self._indices_from_paths(
            history_paths,
            unique=False,
            limit=200,
        )
        self.shuffle_bag = self._indices_from_paths(
            bag_paths,
            unique=True,
        )
        self.playback_sequence = self._indices_from_paths(
            sequence_paths,
            unique=True,
        )

        if current_path is not None:
            try:
                resolved_current = Path(current_path).resolve()
            except (OSError, RuntimeError):
                resolved_current = None
            self.current = (
                self.song_lookup.get(resolved_current)
                if resolved_current is not None
                else None
            )
        else:
            self.current = None

        if current_path is not None and self.current is None:
            self.mpv.stop()
            self.current_lyrics = None
            self.lyrics_track_index = None
            self.gapless_next_index = None

        if selected_path is not None:
            try:
                resolved_selected = Path(selected_path).resolve()
            except (OSError, RuntimeError):
                resolved_selected = None
            selected_index = (
                self.song_lookup.get(resolved_selected)
                if resolved_selected is not None
                else None
            )
        else:
            selected_index = None

        ordered = self.ordered_library_indices()
        if selected_index is not None and selected_index in ordered:
            self.selected = ordered.index(selected_index)
        elif ordered:
            self.selected = min(self.selected, len(ordered) - 1)
        else:
            self.selected = 0

        self.sanitize_shuffle_bag()
        self.queue_missing_metadata_enrichment()

        if self.current is not None:
            self.load_current_lyrics(self.current)
            self.prime_gapless_next()

        new_paths = {
            str(song.resolve())
            for song in self.songs
        }
        added = len(new_paths - old_paths)
        removed = len(old_paths - new_paths)

        changed_count = 0
        if event_summary:
            changed_count = len(event_summary.get("paths", ()))

        self.sync_mpris(force=True)
        self.set_status(
            (
                f"Library refreshed: +{added} / -{removed}; "
                f"{self.catalog_refreshed} metadata refresh(es)."
            ),
            (
                f"Filesystem cat noticed {changed_count or 'some'} change(s): "
                f"+{added} / -{removed} meow(s), "
                f"{self.catalog_refreshed} re-sniffed."
            )
        )

    def process_filesystem_watch(self):
        summary = self.library_watcher.poll()
        if summary is None:
            return False

        self.rescan_library(summary)
        return True

    def queue_missing_metadata_enrichment(self):
        queued = 0
        for metadata in self.metadata:
            if not needs_online_metadata(metadata):
                continue

            if self.catalog is not None:
                try:
                    state = self.catalog.online_metadata_state(
                        metadata.path
                    )
                except sqlite3.Error:
                    state = None
                if state is not None and not metadata_lookup_due(state):
                    continue

            if self.online_metadata.enqueue(metadata):
                queued += 1
        return queued

    def process_online_metadata(self):
        results = self.online_metadata.poll()
        if not results:
            return 0

        changed_current = False
        stored = False

        for result in results:
            try:
                resolved = Path(result.path).expanduser().resolve()
            except (OSError, RuntimeError, TypeError):
                continue

            index = self.song_lookup.get(resolved)
            if index is None:
                continue

            metadata = self.metadata[index]

            if result.status == "found":
                merged_values = merge_missing_metadata(
                    metadata,
                    result,
                )
                merged = replace(metadata, **merged_values)
                self.metadata[index] = merged

                if self.catalog is not None:
                    try:
                        stored = (
                            self.catalog.store_online_metadata_result(
                                resolved,
                                merged,
                                status="found",
                                source="musicbrainz",
                                source_id=result.source_id,
                                query=result.query,
                            )
                            or stored
                        )
                    except sqlite3.Error:
                        pass

                if index == self.current:
                    changed_current = True
                    self.set_status(
                        (
                            f"Metadata enriched from MusicBrainz: "
                            f"{merged.artist_title}"
                        ),
                        (
                            f"The internet cat identified this meow: "
                            f"{merged.artist_title}"
                        )
                    )
            elif self.catalog is not None:
                try:
                    stored = (
                        self.catalog.mark_online_metadata_result(
                            resolved,
                            status=result.status,
                            source="musicbrainz",
                            source_id=result.source_id,
                            query=result.query,
                        )
                        or stored
                    )
                except sqlite3.Error:
                    pass

        if stored and self.catalog is not None:
            try:
                self.catalog.commit()
            except sqlite3.Error:
                pass

        if changed_current:
            self.sync_mpris(force=True)

        return len(results)

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
                "rating": 0,
                "play_count": 0,
                "last_played_ns": None,
                "added_at_ns": 0,
            },
        )

    def refresh_library_stats(self):
        if self.catalog is not None:
            self.library_stats = self.catalog.play_stats()

    def reload_custom_smart_mixes(self, silent=False):
        definitions, errors = load_custom_mix_definitions(
            smart_mixes_path()
        )
        self.custom_mix_definitions = definitions
        self.custom_mix_errors = errors

        if self.smart_playlist_key:
            valid_keys = {
                playlist.key
                for playlist in build_smart_playlists(
                    self.metadata,
                    self.library_stats,
                    self.custom_mix_definitions,
                )
            }
            if self.smart_playlist_key not in valid_keys:
                self.smart_playlist_key = None
                self.selected = 0

        if silent:
            return

        if errors:
            self.set_status(
                (
                    f"Loaded {len(definitions)} custom mix(es); "
                    f"{len(errors)} rule error(s)."
                ),
                (
                    f"The cat loaded {len(definitions)} custom mix(es), "
                    f"but hissed at {len(errors)} rule(s)."
                )
            )
        else:
            self.set_status(
                f"Loaded {len(definitions)} custom Smart Mix(es).",
                f"Reloaded {len(definitions)} custom Smart Mix(es)."
            )

    def smart_playlists(self):
        return build_smart_playlists(
            self.metadata,
            self.library_stats,
            self.custom_mix_definitions,
        )

    def current_smart_playlist(self):
        if not self.smart_playlist_key:
            return None

        for playlist in self.smart_playlists():
            if playlist.key == self.smart_playlist_key:
                return playlist
        return None

    def smart_top_level(self):
        return (
            self.library_view == "smart"
            and self.smart_playlist_key is None
        )

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

        if self.library_view == "smart" and self.smart_playlist_key:
            playlist = self.current_smart_playlist()
            allowed = set(playlist.indices) if playlist is not None else set()
            indices = [
                index
                for index in indices
                if index in allowed
            ]

        return indices

    def ordered_track_indices(self):
        indices = self.filtered_song_indices()

        if self.library_view == "smart" and self.smart_playlist_key:
            playlist = self.current_smart_playlist()
            if playlist is None:
                return []
            visible = set(indices)
            return [
                index
                for index in playlist.indices
                if index in visible
            ]

        if self.library_view == "history":
            return sorted(
                indices,
                key=lambda i: (
                    -(self.stats_for(i)["last_played_ns"] or 0),
                    self.meta(i).title.casefold(),
                ),
            )

        if self.library_view in ("songs", "pawmarks", "smart"):
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
        if self.smart_top_level():
            return []

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

    def rating_stars(self, index, include_unrated=False):
        if index is None or index < 0 or index >= len(self.songs):
            return ""

        rating = int(self.stats_for(index).get("rating", 0) or 0)
        rating = max(0, min(5, rating))
        if rating == 0 and not include_unrated:
            return ""
        return "★" * rating + "☆" * (5 - rating)

    def decorate_track_row(self, index, text):
        stats = self.stats_for(index)
        prefix = ""
        if stats.get("favorite"):
            prefix = "♥ " if self.serious_mode else "🐾 "

        stars = self.rating_stars(index)
        suffix = f" · {stars}" if stars else ""
        return f"{prefix}{text}{suffix}"

    def track_row_text(self, index):
        meta = self.meta(index)
        duration = (
            f" · {self.format_time(meta.duration)}"
            if meta.duration > 0
            else ""
        )
        genre = f" · {meta.genre}" if meta.genre else ""

        if self.library_view in ("songs", "pawmarks", "smart"):
            text = meta.artist_title
            if meta.album != "Unknown Album":
                text += f" · {meta.album}"
            if meta.genre:
                text += genre
            return self.decorate_track_row(index, text) + duration

        if self.library_view == "history":
            stats = self.stats_for(index)
            count = stats["play_count"]
            text = f"{meta.artist_title} · played {count}×"
            return self.decorate_track_row(index, text) + duration

        if self.library_view == "artists":
            text = meta.title
            if meta.album != "Unknown Album":
                text += f" · {meta.album}"
            if meta.year:
                text += f" ({meta.year})"
            if meta.genre:
                text += genre
            return self.decorate_track_row(index, text) + duration

        if self.library_view == "albums":
            number = (
                f"{meta.track_number:02d}. "
                if meta.track_number
                else "    "
            )
            text = f"{number}{meta.title} — {meta.artist}"
            return self.decorate_track_row(index, text) + duration

        return self.decorate_track_row(index, meta.filename) + duration

    def library_rows(self):
        if self.smart_top_level():
            return [
                (
                    "smart",
                    (
                        f"{playlist.label} · "
                        f"{len(playlist.indices)} track(s) ›"
                    ),
                    playlist.key,
                )
                for playlist in self.smart_playlists()
            ]

        ordered = self.ordered_library_indices()

        if self.library_view in ("songs", "pawmarks", "history", "smart"):
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
        if self.smart_top_level():
            return None

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
        if self.library_view == "smart":
            return self.smart_playlist_key is not None
        return True

    def select_library_view(self, view):
        if view not in LIBRARY_VIEWS:
            return

        self.library_view = view
        self.drill_artist = None
        self.drill_album = None
        self.smart_playlist_key = None
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

        playlist = self.current_smart_playlist()
        if playlist is not None:
            label += f" / {playlist.label}"

        return label

    def activate_library_selection(self):
        if self.smart_top_level():
            playlists = self.smart_playlists()
            if not playlists:
                return

            self.selected = max(
                0,
                min(self.selected, len(playlists) - 1),
            )
            playlist = playlists[self.selected]
            self.smart_playlist_key = playlist.key
            self.selected = 0
            self.set_status(
                f"Opened smart playlist: {playlist.label}",
                f"The cat assembled: {playlist.label}"
            )
            return

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

        if self.library_view == "smart":
            playlist = self.current_smart_playlist()
            sequence = list(playlist.indices) if playlist is not None else []
            self.play(index, sequence=sequence)
            return

        self.play(index)

    def go_back_library(self):
        if self.library_view == "artists" and self.drill_album is not None:
            self.drill_album = None
        elif self.library_view == "artists" and self.drill_artist is not None:
            self.drill_artist = None
        elif self.library_view == "albums" and self.drill_album is not None:
            self.drill_album = None
        elif self.library_view == "smart" and self.smart_playlist_key is not None:
            self.smart_playlist_key = None
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

    def rating_target_index(self):
        if self.view == "library":
            if not self.library_selection_is_track():
                return None
            return self.selected_library_song()

        if self.view == "stash" and self.catnip_stash:
            position = max(
                0,
                min(self.stash_selected, len(self.catnip_stash) - 1),
            )
            return self.catnip_stash[position]

        return self.current

    def adjust_rating(self, delta):
        index = self.rating_target_index()
        if index is None:
            self.set_status(
                "Select a track before changing its rating.",
                "Open a real meow before the cat can judge it."
            )
            return False

        if self.catalog is None:
            self.set_status(
                "Ratings unavailable without the Cat Catalog.",
                "The rating clipboard fell out of the Cat Catalog."
            )
            return False

        old_rating = int(self.stats_for(index).get("rating", 0) or 0)
        new_rating = max(0, min(5, old_rating + int(delta)))
        if new_rating == old_rating:
            self.set_status(
                f"Rating already at {new_rating}/5.",
                "The cat has reached the edge of its extremely scientific scale."
            )
            return False

        stored = self.catalog.set_rating(self.songs[index], new_rating)
        if stored is None:
            self.set_status(
                "Could not store rating for this track.",
                "The Cat Catalog ate the scorecard."
            )
            return False

        self.refresh_library_stats()
        meta = self.meta(index)
        stars = self.rating_stars(index, include_unrated=True)
        reaction = random.choice(RATING_REACTIONS[new_rating])

        self.set_status(
            (
                f"Rating {new_rating}/5: {meta.artist_title}"
                if new_rating
                else f"Rating cleared: {meta.artist_title}"
            ),
            f"Cat verdict {stars}: {meta.artist_title} — {reaction}"
        )

        if not self.serious_mode:
            self.trigger_cat_incident(
                f"REVIEW BOARD: {reaction}",
                duration=6.0,
            )
        return True

    def play_online(self, track, now=None):
        if track is None:
            return False

        timestamp = time.monotonic() if now is None else float(now)
        same_track = (
            self.online_current is not None
            and self.online_current.video_id == track.video_id
        )

        if same_track:
            elapsed = max(0.0, timestamp - self.online_load_started_at)
            idle = bool(self.mpv.get_property("idle-active"))

            if self.online_load_state in {"resolving", "loading"} or not idle or elapsed < ONLINE_RETRY_GUARD_SECONDS:
                state = (
                    "resolving"
                    if self.online_load_state == "resolving"
                    else "already active"
                )
                LOGGER.info(
                    "Ignoring duplicate online playback request "
                    "video_id=%s state=%s elapsed=%.2fs idle=%s",
                    track.video_id,
                    self.online_load_state,
                    elapsed,
                    idle,
                )
                self.set_status(
                    (
                        f"YouTube stream {state}: {track.artist_title}. "
                        "Repeated Enter ignored."
                    ),
                    (
                        f"The internet cat is {state}: {track.artist_title}. "
                        "More Enter will not make the router go faster."
                    ),
                )
                return False

            LOGGER.info(
                "Retrying online playback after idle/failed attempt "
                "video_id=%s elapsed=%.2fs",
                track.video_id,
                elapsed,
            )

        LOGGER.info(
            "Starting online playback video_id=%s title=%r artist=%r url=%s",
            track.video_id,
            track.title,
            track.artist,
            track.url,
        )

        self.online_current = track
        self.online_load_state = "resolving"
        self.online_load_started_at = timestamp
        self.current = None
        self.current_lyrics = None
        self.lyrics_track_index = None
        lyrics = getattr(self, "lyrics", None)
        if lyrics is not None and hasattr(lyrics, "load_transient"):
            lyrics.load_transient(
                track.video_id,
                title=track.title,
                artist=track.artist,
                duration=track.duration,
            )
        self.gapless_next_index = None
        self._awaiting_mpv_path = False

        self._online_retry = 0
        self._online_path = None
        LOGGER.debug("YT_LATENCY user_enter=%.6f video_id=%s", timestamp, track.video_id)
        resolver = getattr(self, "stream_resolver", None)
        if resolver:
            self.mpv.stop()
            cached = resolver.cached(track)
            self._online_future = resolver.request(track)
            self._online_resolver_path = "cache" if cached else "fresh"
            self._finish_online_resolve()
        else:
            self._load_online_fallback()

        state = "Loading" if self.online_load_state == "loading" else "Resolving"
        self.set_status(
            f"{state} YouTube stream: {track.artist_title}",
            f"The internet cat is {state.lower()}: {track.artist_title}",
        )
        self.sync_mpris(force=True)
        return True

    def _load_online_fallback(self):
        self._online_path = "mpv-fallback"
        self._online_expected_path = None
        self._online_load_sent = time.monotonic()
        self.mpv.load(self.online_current.url)
        self.mpv.play()
        self.online_load_state = "loading"
        LOGGER.debug("YT_PLAY resolver=mpv-fallback cache_hit=false "
                     "mpv_loadfile_sent=%.6f enter_to_loadfile_ms=%.3f",
                     self._online_load_sent,
                     (self._online_load_sent - self.online_load_started_at) * 1000)

    def _finish_online_resolve(self):
        future = getattr(self, "_online_future", None)
        if future is None or not future.done():
            return False
        self._online_future = None
        try:
            stream = future.result()
            if not stream.valid():
                raise ValueError("expired stream")
        except Exception:
            self._load_online_fallback()
            return True
        self._online_path = self._online_resolver_path
        self._online_expected_path = stream.url
        self._online_load_sent = time.monotonic()
        response = self.mpv.load_stream(stream)
        if not response or response.get("error") != "success":
            self._load_online_fallback()
            return True
        self.mpv.play()
        self.online_load_state = "loading"
        LOGGER.debug("YT_PLAY resolver=%s cache_hit=%s mpv_loadfile_sent=%.6f enter_to_loadfile_ms=%.3f",
                     self._online_path, str(self._online_path == "cache").lower(), self._online_load_sent,
                     (self._online_load_sent - self.online_load_started_at) * 1000)
        return True

    def refresh_online_playback_state(self, now=None):
        if self.online_current is None:
            self.online_load_state = "idle"
            return False
        if self.online_load_state == "resolving":
            return self._finish_online_resolve()
        if self.online_load_state != "loading":
            return False
        timestamp = time.monotonic() if now is None else float(now)
        events = (
            self.mpv.playback_snapshot() if hasattr(self.mpv, "playback_snapshot")
            else dict(getattr(self.mpv, "playback_events", {}))
        )
        sent = self._online_load_sent
        started = events.get("start-file", 0) >= sent
        position = self.mpv.get_property("time-pos")
        # Duration/file-loaded alone is not evidence of audible playback.
        expected = getattr(self, "_online_expected_path", None)
        same_file = expected is None or self.mpv.get_property("path") == expected
        ready = (same_file and started and events.get("file-loaded", 0) >= sent
                 and events.get("playback-restart", 0) >= sent
                 and position is not None and float(position) > 0
                 and not self.mpv.get_property("idle-active"))
        if ready:
            timestamp = max(events.get("first-nonzero-time-pos", timestamp),
                            events["playback-restart"])
            self._online_playback_started_at = timestamp
            self.online_load_state = "streaming"
            LOGGER.debug(
                "YT_LATENCY enter_to_playback_ms=%.3f loadfile_to_file_loaded_ms=%.3f "
                "file_loaded_to_playback_ms=%.3f mpv_start_file_event=%.6f "
                "mpv_file_loaded_event=%.6f mpv_audio_reconfig_event=%.6f "
                "mpv_playback_restart_event=%.6f first_nonzero_time_pos=%.6f",
                (timestamp - self.online_load_started_at) * 1000,
                (events["file-loaded"] - sent) * 1000,
                (timestamp - events["file-loaded"]) * 1000,
                events["start-file"], events["file-loaded"],
                events.get("audio-reconfig", 0), events["playback-restart"], timestamp)
            self.set_status(f"Streaming from YouTube: {self.online_current.artist_title}",
                            f"The internet cat is streaming: {self.online_current.artist_title}")
            return True
        failed = (events.get("end-file", 0) >= sent and events.get("end-reason") == "error")
        if failed or timestamp - sent >= 30.0:
            resolver = getattr(self, "stream_resolver", None)
            if resolver and self._online_path != "mpv-fallback":
                resolver.invalidate(self.online_current)
                if self._online_retry == 0:
                    self._online_retry += 1
                    self._online_future = resolver.request(self.online_current)
                    self._online_resolver_path = "fresh"
                    self.online_load_state = "resolving"
                else:
                    self._load_online_fallback()
            else:
                self.online_load_state = "failed"
                self.set_status("YouTube stream did not start. Press Enter to retry.",
                                "The internet cat returned empty-pawed. Enter to retry.")
            return True
        return False

    def process_youtube(self):
        session = self.youtube_search_session
        if session:
            while True:
                try:
                    kind, value = session.results.get_nowait()
                except queue.Empty:
                    break
                if kind == "track":
                    self.youtube_results.append(value)
                    if self.youtube_search_mode == "artist":
                        self.set_status(
                            f"Artist search: {len(self.youtube_results)} result(s)...",
                            f"The artist-scent cat found {len(self.youtube_results)} meow(s)...",
                        )
                    else:
                        self.set_status(
                            f"Searching YouTube: {len(self.youtube_results)} result(s)...",
                            f"The internet cat found {len(self.youtube_results)} meow(s)...",
                        )
                else:
                    self.youtube_search_session = None
                    if kind == "error":
                        self.set_status(value, value)
                    elif self.youtube_search_mode == "artist":
                        self.set_status(
                            f"Artist search: {len(self.youtube_results)} result(s).",
                            f"The artist-scent cat found {len(self.youtube_results)} meow(s).",
                        )
                    else:
                        self.set_status(
                            f"YouTube search: {len(self.youtube_results)} result(s).",
                            f"The internet cat found {len(self.youtube_results)} meow(s).",
                        )
        if self.stream_resolver and self.youtube_results:
            track = self.youtube_results[self.youtube_selected]
            if self._prefetch_selection != track.video_id:
                first = self._prefetch_selection is None
                self._prefetch_selection = track.video_id
                self.stream_resolver.request(track, prefetch=True, debounce=0 if first else 0.15)

    def play_selected_youtube_result(self):
        if not self.youtube_results:
            return False

        self.youtube_selected = max(
            0,
            min(self.youtube_selected, len(self.youtube_results) - 1),
        )
        return self.play_online(self.youtube_results[self.youtube_selected])

    def download_youtube_track(self, track):
        if track is None:
            return False

        if self.youtube_download_session is not None:
            active = self.youtube_download_track
            label = active.artist_title if active is not None else "another track"
            self.set_status(
                f"Download already in progress: {label}",
                f"The adoption cat is already carrying home: {label}",
            )
            return False

        destination = self.music_dir / "Internet Nest"
        self.youtube_download_track = track
        self.youtube_download_session = YouTubeDownloadSession(
            self.youtube.executable,
            track,
            destination,
        )
        self.set_status(
            f"Downloading to library: {track.artist_title}",
            f"Adopting this meow into the Music Nest: {track.artist_title}",
        )
        return True

    def download_selected_youtube_result(self):
        if not self.youtube_results:
            return False

        self.youtube_selected = max(
            0,
            min(self.youtube_selected, len(self.youtube_results) - 1),
        )
        return self.download_youtube_track(
            self.youtube_results[self.youtube_selected]
        )

    def open_selected_youtube_creator(self):
        if not self.youtube_results:
            return False

        self.youtube_selected = max(
            0,
            min(self.youtube_selected, len(self.youtube_results) - 1),
        )
        track = self.youtube_results[self.youtube_selected]
        if not track.channel_url:
            self.set_status(
                "This result does not expose a browsable YouTube channel.",
                "This meow left no trail back to its creator nest.",
            )
            return False

        if self.creator_session is not None:
            self.creator_session.close()
            self.creator_session = None

        self.creator_name = track.artist
        self.creator_channel_url = track.channel_url
        self.creator_level = "menu"
        self.creator_items = []
        self.creator_selected = 0
        self.creator_playlist = None
        self.view = "creator"
        self.set_status(
            f"Opened creator channel: {self.creator_name}",
            f"Found {self.creator_name}'s Creator Nest.",
        )
        return True

    def start_creator_browse(self, level, playlist=None):
        if level not in {"uploads", "playlists", "playlist"}:
            return False

        if self.creator_session is not None:
            self.creator_session.close()

        if level == "playlist":
            if playlist is None:
                return False
            source_url = playlist.url
            mode = "playlist"
            self.creator_playlist = playlist
        else:
            source_url = self.creator_channel_url
            mode = level
            self.creator_playlist = None

        self.creator_level = level
        self.creator_items = []
        self.creator_selected = 0
        self.creator_session = YouTubeBrowseSession(
            self.youtube,
            source_url,
            mode,
            creator_name=self.creator_name,
        )

        if level == "uploads":
            serious = f"Loading uploads from {self.creator_name}..."
            cat = f"Sniffing {self.creator_name}'s singles and uploads..."
        elif level == "playlists":
            serious = f"Loading playlists / releases from {self.creator_name}..."
            cat = f"Digging through {self.creator_name}'s release basket..."
        else:
            serious = f"Loading playlist: {playlist.title}..."
            cat = f"Opening playlist: {playlist.title}..."

        self.set_status(serious, cat)
        return True

    def process_creator_browse(self):
        session = self.creator_session
        if session is None:
            return False

        changed = False
        while True:
            try:
                kind, value = session.results.get_nowait()
            except queue.Empty:
                break

            changed = True
            if kind in {"track", "playlist"}:
                self.creator_items.append(value)
                continue

            self.creator_session = None
            if kind == "error":
                self.set_status(value, value)
            else:
                self.set_status(
                    f"Creator browse: {len(self.creator_items)} item(s).",
                    f"Creator Nest found {len(self.creator_items)} thing(s).",
                )
            session.close()
            break

        if (
            self.stream_resolver
            and self.creator_level in {"uploads", "playlist"}
            and self.creator_items
        ):
            self.creator_selected = max(
                0,
                min(self.creator_selected, len(self.creator_items) - 1),
            )
            track = self.creator_items[self.creator_selected]
            if hasattr(track, "video_id") and self._prefetch_selection != track.video_id:
                self._prefetch_selection = track.video_id
                self.stream_resolver.request(
                    track,
                    prefetch=True,
                    debounce=0.15,
                )

        return changed

    def activate_creator_selection(self):
        if self.creator_level == "menu":
            if self.creator_selected == 0:
                return self.start_creator_browse("uploads")
            return self.start_creator_browse("playlists")

        if not self.creator_items:
            return False

        self.creator_selected = max(
            0,
            min(self.creator_selected, len(self.creator_items) - 1),
        )
        item = self.creator_items[self.creator_selected]
        if self.creator_level == "playlists":
            return self.start_creator_browse("playlist", item)
        return self.play_online(item)

    def download_selected_creator_track(self):
        if (
            self.creator_level not in {"uploads", "playlist"}
            or not self.creator_items
        ):
            return False
        self.creator_selected = max(
            0,
            min(self.creator_selected, len(self.creator_items) - 1),
        )
        return self.download_youtube_track(
            self.creator_items[self.creator_selected]
        )

    def go_back_creator(self):
        if self.creator_session is not None:
            self.creator_session.close()
            self.creator_session = None

        if self.creator_level == "playlist":
            return self.start_creator_browse("playlists")
        if self.creator_level in {"uploads", "playlists"}:
            self.creator_level = "menu"
            self.creator_items = []
            self.creator_selected = 0
            self.creator_playlist = None
            self.set_status(
                f"Creator channel: {self.creator_name}",
                f"Back at {self.creator_name}'s Creator Nest.",
            )
            return True

        self.view = "online"
        self.set_status(
            "Returned to Internet Nest results.",
            "The cat backed out to the Internet Nest.",
        )
        return True

    def process_youtube_download(self):
        session = self.youtube_download_session
        if session is None:
            return False

        try:
            kind, value = session.results.get_nowait()
        except queue.Empty:
            return False

        track = self.youtube_download_track
        session.close()
        self.youtube_download_session = None
        self.youtube_download_track = None

        if kind == "error":
            self.set_status(
                f"Download failed: {value}",
                f"The adoption cat came home empty-pawed: {value}",
            )
            return True

        downloaded = Path(value)
        self.rescan_library({"paths": (str(downloaded),)})
        label = track.artist_title if track is not None else downloaded.stem
        self.set_status(
            f"Downloaded to library: {label} → {downloaded.name}",
            f"Adopted into the Music Nest: {label} → {downloaded.name}",
        )
        return True

    def play(
        self,
        index,
        automatic=False,
        record_history=True,
        record_listen=True,
        preserve_sequence=False,
        sequence=None,
    ):
        if not self.songs:
            return

        index %= len(self.songs)
        LOGGER.info(
            "Starting local playback index=%s path=%s automatic=%s",
            index,
            self.songs[index],
            automatic,
        )
        self.online_current = None
        self._online_future = None
        self.online_load_state = "idle"
        self.online_load_started_at = 0.0

        reset_shuffle_bag = False
        if not preserve_sequence:
            self.playback_sequence = list(sequence or [])
            reset_shuffle_bag = self.shuffle

        if (
            record_history
            and self.current is not None
            and self.current != index
        ):
            self.history.append(self.current)
            if len(self.history) > 200:
                self.history.pop(0)

        if (
            self.shuffle
            and not reset_shuffle_bag
            and index in self.shuffle_bag
        ):
            self.shuffle_bag.remove(index)

        self.current = index
        self.load_current_lyrics(index)
        if reset_shuffle_bag:
            self.refill_shuffle_bag()

        # If this exact track is already sitting in mpv's playlist as the
        # one-track-ahead gapless reservation, advance to it directly instead
        # of deleting it and issuing loadfile replace for the same file.
        # mpv can otherwise end up with playlist-count=1 but current-pos=-1.
        use_primed_entry = (
            self.gapless_next_index == index
            and not self._awaiting_mpv_path
        )

        advanced = False
        if use_primed_entry:
            response = self.mpv.advance_playlist()
            advanced = bool(
                response
                and response.get("error") == "success"
            )

            # mpv can acknowledge playlist-play-index while an EOF handoff is
            # happening, then briefly end up between entries
            # (playlist-current-pos == -1). Verify the target really became
            # current before trusting the successful command. If it did not,
            # recover through an explicit load below.
            if advanced:
                # playlist-play-index is asynchronous. On a busy CI runner
                # (and occasionally on a loaded desktop) mpv can spend more
                # than a few hundred milliseconds at current-pos=-1 while it
                # hands off to the reserved entry. Falling back too early
                # races that handoff and can strand mpv with no current path.
                advanced = self.mpv.wait_for_path(
                    self.songs[index],
                    timeout=1.25,
                )

        if not advanced:
            # If a successful primed advance genuinely did not settle, abort
            # the in-flight handoff before issuing loadfile replace. This
            # makes the recovery deterministic instead of racing mpv's
            # asynchronous playlist transition.
            if use_primed_entry:
                self.mpv.stop()
            self.mpv.clear_future_playlist()
            self.mpv.load(self.songs[index])
            self.mpv.play()

        self.gapless_next_index = None
        # Even a successfully observed playlist-play-index handoff can still
        # pass through a short current-pos == -1 transition immediately after
        # this method returns. Defer *all* future playlist mutation until
        # sync_gapless_transition() confirms the new current path again.
        # This prevents an eager append from turning a 2-entry playlist into
        # 3 entries while mpv is between tracks.
        self._awaiting_mpv_path = True

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

        self.prime_gapless_next()

    def play_selected_library_song(self):
        index = self.selected_library_song()
        if index is None:
            return

        if self.library_view == "smart":
            playlist = self.current_smart_playlist()
            sequence = list(playlist.indices) if playlist is not None else []
            self.play(index, sequence=sequence)
        else:
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
        self.prime_gapless_next()

    def play_stash_position(self, position, automatic=False):
        if not self.catnip_stash:
            return False

        position = max(0, min(position, len(self.catnip_stash) - 1))
        index = self.catnip_stash.pop(position)

        if self.catnip_stash:
            self.stash_selected = min(position, len(self.catnip_stash) - 1)
        else:
            self.stash_selected = 0

        self.play(
            index,
            automatic=automatic,
            preserve_sequence=True,
        )

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
            pool = self.shuffle_pool()
            if not pool:
                return
            if len(pool) == 1:
                index = pool[0]
            else:
                self.sanitize_shuffle_bag()
                if not self.shuffle_bag:
                    self.refill_shuffle_bag()
                if not self.shuffle_bag:
                    index = pool[0]
                else:
                    index = self.shuffle_bag.pop()
        elif self.current is None:
            if self.playback_sequence:
                index = self.playback_sequence[0]
            else:
                index = 0
        elif self.playback_sequence:
            if self.current in self.playback_sequence:
                position = self.playback_sequence.index(self.current)
                index = self.playback_sequence[
                    (position + 1) % len(self.playback_sequence)
                ]
            else:
                index = self.playback_sequence[0]
        else:
            index = (self.current + 1) % len(self.songs)

        self.play(
            index,
            automatic=automatic,
            preserve_sequence=True,
        )
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
            index = (
                self.playback_sequence[0]
                if self.playback_sequence
                else 0
            )
        elif (
            self.playback_sequence
            and self.current in self.playback_sequence
        ):
            position = self.playback_sequence.index(self.current)
            index = self.playback_sequence[
                (position - 1) % len(self.playback_sequence)
            ]
        else:
            index = (self.current - 1) % len(self.songs)

        self.play(
            index,
            record_history=False,
            preserve_sequence=True,
        )

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
        self.prime_gapless_next()

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
        self.prime_gapless_next()

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

        self.prime_gapless_next()

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
        self.prime_gapless_next()

    def set_volume_absolute(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return

        self.volume = int(round(max(0.0, min(100.0, value))))
        self.mpv.set_property("volume", self.volume)

    def update_volume(self, amount):
        self.set_volume_absolute(self.volume + amount)

        if self.volume == 100:
            self.set_status(
                "Volume set to 100%.",
                "MEOW LEVEL MAXIMUM. The cat is now yelling directly into the DAC."
            )
        elif self.volume >= 90:
            self.set_status(
                f"Volume set to {self.volume}%.",
                f"Meow Level {self.volume}%. Indoor voice privileges revoked."
            )
        elif self.volume == 0:
            self.set_status(
                "Volume muted.",
                "Silent meow achieved. The cat is now aggressively lip-syncing."
            )
        elif self.volume <= 10:
            self.set_status(
                f"Volume set to {self.volume}%.",
                f"Meow Level {self.volume}%. Tiny indoor voice enabled."
            )
        elif amount > 0:
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

        if self.playback_saboteur.mode == "dangerous":
            mascot = (
                " /\\_/\\",
                r"( O_O )",
                r" > ^ <",
            )
            lines = list(mascot) + [
                "",
                "BAD LARRY HAS ENTERED THE ROOM",
                "Playback authority: CONTESTED",
            ]
            start_y = max(0, (height - len(lines)) // 2)
            for offset, line in enumerate(lines):
                x = max(0, (width - len(line)) // 2)
                try:
                    stdscr.addstr(
                        start_y + offset,
                        x,
                        line[:max(0, width - x - 1)],
                    )
                except curses.error:
                    pass
            stdscr.refresh()
            time.sleep(1.3)
            return

        mascot = MAXIMUM_MEOW_MASCOT if self.maximum_meow else CAT_MASCOT
        startup_lines = (
            "Sniffing metadata and indexing your music nest...",
            "Counting songs. Losing count. Counting again...",
            "Checking The Catnip Stash for contraband...",
            "Asking mpv very politely to do the difficult part...",
            "Warming the terminal until it qualifies as a cat bed...",
            "Inspecting tags with absolutely unnecessary seriousness...",
        )
        lines = list(mascot) + [
            "",
            "Welcome to MeowPlayer",
            random.choice(startup_lines)
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

    def load_current_lyrics(self, index):
        if (
            index is None
            or index < 0
            or index >= len(self.songs)
        ):
            self.current_lyrics = None
            self.lyrics_track_index = None
            return

        self.current_lyrics = self.lyrics.load(self.songs[index])
        self.lyrics_track_index = index
        self.lyrics_follow = True
        self.lyrics_scroll = 0

    def refresh_current_lyrics(self):
        online_track = getattr(self, "online_current", None)
        if online_track is not None:
            poll_transient = getattr(self.lyrics, "poll_transient", None)
            if poll_transient is None:
                return False
            document = poll_transient(online_track.video_id)
            track_index = None
            fetched_message = (
                f"Lyrics fetched for this session: {document.source}."
                if document is not None
                else ""
            )
        elif self.current is not None:
            document = self.lyrics.poll(self.songs[self.current])
            track_index = self.current
            fetched_message = (
                f"Lyrics downloaded: {document.source}."
                if document is not None
                else ""
            )
        else:
            return False

        if document is None:
            return False

        self.current_lyrics = document
        self.lyrics_track_index = track_index
        self.lyrics_follow = True
        self.lyrics_scroll = 0
        self.set_status(
            fetched_message,
            "Lyrics acquired. The cat can now sing them incorrectly."
        )
        return True

    def lyrics_lookup_message(self):
        online_track = getattr(self, "online_current", None)
        if online_track is not None:
            status_fn = getattr(self.lyrics, "transient_status", None)
            state = (
                status_fn(online_track.video_id)
                if status_fn is not None
                else {"status": "idle", "query": "", "attempts": 0}
            )
        elif self.current is not None:
            state = self.lyrics.online_status(self.songs[self.current])
        else:
            return self.text(
                "Play a track to view lyrics.",
                "Pick a meow before opening the songbook."
            )

        status = state.get("status", "idle")
        query = state.get("query", "").strip()

        if status == "searching":
            if query:
                return self.text(
                    f"Searching LRCLIB for: {query}",
                    f"The cat is sniffing LRCLIB for: {query}"
                )
            return self.text(
                "Searching LRCLIB for lyrics...",
                "The cat is sniffing LRCLIB for words..."
            )

        if status == "network-error":
            return self.text(
                "LRCLIB lookup failed after retry. Reopen Songbook to retry.",
                "LRCLIB escaped twice. Close and reopen the Songbook for another pounce."
            )

        if status == "not-found":
            if query:
                return self.text(
                    f"No lyrics found on LRCLIB for: {query}",
                    f"LRCLIB found no lyrics for this scent: {query}"
                )
            return self.text(
                "No lyrics found on LRCLIB.",
                "LRCLIB found no lyrics for this meow."
            )

        if status == "offline":
            return self.text(
                "No local lyrics found. Online lyrics are disabled.",
                "No local words found, and the cat is not allowed onto the internet."
            )

        if status == "disabled":
            return self.text(
                "Lyrics are disabled.",
                "The Songbook is currently sleeping."
            )

        return self.text(
            "No local lyrics found yet.",
            "No lyrics found yet. The cat may still be improvising."
        )

    def current_lyric_text(self):
        if (
            not self.has_active_track()
            or self.current_lyrics is None
            or not self.current_lyrics.synced
        ):
            return ""

        try:
            position = float(
                self.mpv.get_property("time-pos") or 0.0
            )
        except (TypeError, ValueError):
            position = 0.0

        return self.current_lyrics.current_line(position)

    def toggle_lyrics_view(self):
        if self.view == "lyrics":
            self.view = self.previous_view
            self.set_status(
                "Returned from lyrics.",
                "The cat closed the songbook."
            )
            return

        self.previous_view = (
            self.view
            if self.view in {"library", "stash", "online"}
            else "library"
        )
        self.view = "lyrics"
        self.lyrics_follow = True

        if self.current_lyrics is None:
            online_track = getattr(self, "online_current", None)
            if online_track is not None:
                status_fn = getattr(self.lyrics, "transient_status", None)
                retry_fn = getattr(self.lyrics, "retry_transient", None)
                if status_fn is not None and retry_fn is not None:
                    state = status_fn(online_track.video_id)
                    if state.get("status") == "network-error":
                        retry_fn(
                            online_track.video_id,
                            title=online_track.title,
                            artist=online_track.artist,
                            duration=online_track.duration,
                        )
            elif self.current is not None:
                state = self.lyrics.online_status(self.songs[self.current])
                if state.get("status") == "network-error":
                    self.lyrics.retry_online(self.songs[self.current])
            message = self.lyrics_lookup_message()
            self.status_message = message
        else:
            source = self.current_lyrics.source
            self.set_status(
                f"Lyrics opened: {source}",
                f"Songbook opened: {source}"
            )

    def draw_lyrics(
        self,
        stdscr,
        width,
        list_start,
        list_height,
    ):
        document = self.current_lyrics

        if not self.has_active_track():
            message = self.text(
                "Play a track to view lyrics.",
                "Pick a meow before opening the songbook."
            )
            try:
                stdscr.addstr(
                    list_start,
                    2,
                    message[:max(1, width - 4)],
                    curses.A_DIM,
                )
            except curses.error:
                pass
            return

        if document is None or not document.lines:
            message = self.lyrics_lookup_message()
            try:
                stdscr.addstr(
                    list_start,
                    2,
                    message[:max(1, width - 4)],
                    curses.A_DIM,
                )
            except curses.error:
                pass
            return

        try:
            position = float(
                self.mpv.get_property("time-pos") or 0.0
            )
        except (TypeError, ValueError):
            position = 0.0

        current_index = (
            document.current_index(position)
            if document.synced
            else None
        )

        if document.synced and self.lyrics_follow:
            center = current_index or 0
            start = max(0, center - list_height // 2)
            start = min(
                start,
                max(0, len(document.lines) - list_height),
            )
            self.lyrics_scroll = start
        else:
            self.lyrics_scroll = max(
                0,
                min(
                    self.lyrics_scroll,
                    max(0, len(document.lines) - list_height),
                ),
            )

        end = min(
            len(document.lines),
            self.lyrics_scroll + list_height,
        )

        for row, index in enumerate(
            range(self.lyrics_scroll, end)
        ):
            line = document.lines[index]
            selected = (
                document.synced
                and current_index is not None
                and index == current_index
            )

            if selected and not self.serious_mode:
                prefix = ">♫< "
            elif selected:
                prefix = "▶ "
            else:
                prefix = "   "

            attr = curses.A_BOLD if selected else curses.A_DIM
            try:
                stdscr.addstr(
                    list_start + row,
                    2,
                    (prefix + line.text)[:max(1, width - 4)],
                    attr,
                )
            except curses.error:
                pass

    def current_album_art(self):
        if (
            not self.album_art.supported
            or self.current is None
            or self.current < 0
            or self.current >= len(self.songs)
        ):
            return None
        return self.album_art.cover_for(self.songs[self.current])

    def album_art_layout(self, height, width, image_path):
        if image_path is None or width < 88 or height < 18:
            return None

        columns = min(22, max(16, width // 5))
        rows = min(9, max(6, height // 3))
        column = max(0, width - columns - 2)

        return {
            "row": 1,
            "column": column,
            "columns": columns,
            "rows": rows,
            "text_width": max(46, column - 2),
        }

    def lyrics_album_art_layout(
        self,
        height,
        width,
        image_path,
        list_start,
        list_height,
    ):
        if (
            image_path is None
            or width < 88
            or height < 18
            or list_height < 6
        ):
            return None

        columns = min(30, max(18, width // 3))
        column = width - columns - 2
        lyrics_width = column - 1
        if lyrics_width < 42:
            return None

        rows = min(list_height, max(6, min(14, list_height)))
        row = list_start + max(0, (list_height - rows) // 2)

        return {
            "row": row,
            "column": column + 1,
            "columns": columns,
            "rows": rows,
            "lyrics_width": lyrics_width,
            "divider_column": column,
        }

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
        if self.playback_saboteur.mode == "dangerous":
            title = f"♫ MEOWPLAYER v{__version__} — BAD LARRY IN THE ROOM"
        elif self.playback_saboteur.enabled:
            title = (
                f"♫ MEOWPLAYER v{__version__} — "
                f"{self.playback_saboteur.label}"
            )
        else:
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

    def prompt_bad_larry_apology(self, stdscr):
        phrase = DANGEROUS_DISMISS_PHRASE
        stdscr.nodelay(False)
        stdscr.timeout(-1)
        curses.echo()

        try:
            curses.curs_set(1)
        except curses.error:
            pass

        try:
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            lines = [
                "BAD LARRY EMERGENCY EXIT",
                "",
                "Bad Larry requires a formal apology.",
                "Type exactly:",
                phrase,
                "",
            ]
            start_y = max(0, min(2, height - len(lines) - 2))
            for offset, line in enumerate(lines):
                stdscr.addstr(
                    start_y + offset,
                    1,
                    line[:max(1, width - 2)],
                )

            input_y = min(height - 1, start_y + len(lines))
            stdscr.addstr(input_y, 0, "> "[:max(1, width - 1)])
            stdscr.refresh()
            raw = stdscr.getstr(
                input_y,
                min(2, max(0, width - 2)),
                max(1, width - 3),
            )
            return raw.decode("utf-8", errors="replace")
        except curses.error:
            return ""
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            stdscr.nodelay(True)
            stdscr.timeout(100)

    @staticmethod
    def _wrap_bad_larry_text(text, width):
        width = max(12, int(width))
        lines = []
        for raw_line in str(text).splitlines():
            if not raw_line:
                lines.append("")
                continue
            wrapped = textwrap.wrap(
                raw_line,
                width=width,
                replace_whitespace=False,
                drop_whitespace=True,
            )
            lines.extend(wrapped or [""])
        return lines

    def prompt_bad_larry_math(self, stdscr, question):
        stdscr.nodelay(False)
        stdscr.timeout(-1)
        curses.echo()

        try:
            curses.curs_set(1)
        except curses.error:
            pass

        try:
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            body = self._wrap_bad_larry_text(
                question.prompt,
                max(12, width - 4),
            )
            lines = [
                "BAD LARRY MATHEMATICS INCIDENT",
                f"Difficulty: {question.label}",
                "",
            ] + body + [
                "",
                "Type your answer, SKIP to surrender, or ESCAPE for dismissal.",
            ]

            visible = lines[:max(1, height - 2)]
            for row, line in enumerate(visible):
                stdscr.addstr(row, 1, line[:max(1, width - 2)])

            input_y = min(height - 1, len(visible))
            stdscr.move(input_y, 0)
            stdscr.clrtoeol()
            stdscr.addstr(input_y, 0, "> "[:max(1, width - 1)])
            stdscr.refresh()
            raw = stdscr.getstr(
                input_y,
                min(2, max(0, width - 2)),
                max(1, width - 3),
            )
            return raw.decode("utf-8", errors="replace").strip()
        except curses.error:
            return ""
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            stdscr.nodelay(True)
            stdscr.timeout(100)

    def show_bad_larry_no(self, stdscr):
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        lines = [
            "IMO P6-STYLE: CORRECT",
            "",
            "Bad Larry:",
            "No.",
        ]
        start_y = max(0, (height - len(lines)) // 2)
        for offset, line in enumerate(lines):
            x = max(0, (width - len(line)) // 2)
            try:
                stdscr.addstr(start_y + offset, x, line[:max(1, width - x - 1)])
            except curses.error:
                pass
        stdscr.refresh()
        time.sleep(1.0)

    def run_bad_larry_quantum_exam(self, stdscr):
        deadline = time.monotonic() + QUANTUM_EXAM_SECONDS
        scroll = 0
        stdscr.nodelay(False)
        stdscr.timeout(200)
        curses.noecho()

        try:
            curses.curs_set(0)
        except curses.error:
            pass

        try:
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    return "timeout"

                stdscr.erase()
                height, width = stdscr.getmaxyx()
                wrapped = self._wrap_bad_larry_text(
                    QUANTUM_FINAL_EXAM,
                    max(18, width - 4),
                )
                content_height = max(1, height - 5)
                max_scroll = max(0, len(wrapped) - content_height)
                scroll = max(0, min(scroll, max_scroll))
                minutes = int(remaining) // 60
                seconds = int(remaining) % 60

                header = (
                    f"BAD LARRY FINAL EXAM — {minutes:02d}:{seconds:02d} remaining"
                )
                try:
                    stdscr.addstr(0, 1, header[:max(1, width - 2)], curses.A_BOLD)
                    stdscr.addstr(
                        1,
                        1,
                        "Bad Larry: No. New subject."[:max(1, width - 2)],
                    )
                except curses.error:
                    pass

                for row, line in enumerate(
                    wrapped[scroll:scroll + content_height],
                    start=2,
                ):
                    try:
                        stdscr.addstr(row, 1, line[:max(1, width - 2)])
                    except curses.error:
                        pass

                controls = (
                    "UP/DOWN scroll | D = declare complete | "
                    "S = surrender | Ctrl+E = dismiss Larry"
                )
                try:
                    stdscr.addstr(
                        height - 2,
                        1,
                        controls[:max(1, width - 2)],
                        curses.A_DIM,
                    )
                except curses.error:
                    pass
                stdscr.refresh()

                key = stdscr.getch()
                if key == curses.KEY_UP:
                    scroll = max(0, scroll - 1)
                elif key == curses.KEY_DOWN:
                    scroll = min(max_scroll, scroll + 1)
                elif key in (ord("s"), ord("S")):
                    return "skip"
                elif key in (ord("d"), ord("D")):
                    return "submitted"
                elif key == 5:
                    return "emergency"
        finally:
            stdscr.nodelay(True)
            stdscr.timeout(100)

    def handle_bad_larry_math_incident(self, stdscr, question):
        answer = self.prompt_bad_larry_math(stdscr, question)
        command = answer.strip().casefold()

        if command == "escape":
            apology = self.prompt_bad_larry_apology(stdscr)
            if apology_matches(apology):
                self.playback_saboteur.dismiss(self)
                self.cat_chaos_mode = None
                self.set_status(
                    "Dangerous Cat Mode disabled.",
                    "Bad Larry accepts your apology and has left The Room.",
                )
            else:
                self.set_status(
                    "Emergency dismissal denied.",
                    "Bad Larry: that did not sound sincere.",
                )
            return

        if command == "skip":
            self.playback_saboteur.apply_math_skip(
                self,
                question.difficulty,
            )
            return

        if not self.playback_saboteur.grade_math_answer(question, answer):
            self.playback_saboteur.apply_math_wrong(self, question)
            return

        if question.difficulty != "imo-p6":
            self.set_status(
                "Math answer accepted.",
                (
                    "BAD LARRY: correct. This is becoming irritating. "
                    f"Math streak: {self.playback_saboteur.math_correct}."
                ),
            )
            return

        self.show_bad_larry_no(stdscr)
        result = self.run_bad_larry_quantum_exam(stdscr)
        if result in {"skip", "timeout"}:
            self.playback_saboteur.apply_math_skip(self, "quantum")
            if result == "timeout":
                self.set_status(
                    "Quantum final exam timed out.",
                    "BAD LARRY: five whole minutes. Disappointing.",
                )
            return

        if result == "emergency":
            apology = self.prompt_bad_larry_apology(stdscr)
            if apology_matches(apology):
                self.playback_saboteur.dismiss(self)
                self.cat_chaos_mode = None
                self.set_status(
                    "Dangerous Cat Mode disabled.",
                    "Bad Larry accepts your apology and has left The Room.",
                )
            else:
                self.set_status(
                    "Emergency dismissal denied.",
                    "Bad Larry: formal apology rejected.",
                )
            return

        self.set_status(
            "Quantum final exam submitted.",
            "BAD LARRY: I refuse to admit that counted.",
        )

    def prompt_text(self, stdscr, prompt):
        """Read an uncapped line while horizontally scrolling on narrow screens."""
        value = ""
        full_label = f"{prompt}: "

        stdscr.nodelay(False)
        stdscr.timeout(-1)
        curses.noecho()

        try:
            curses.curs_set(1)
        except curses.error:
            pass

        try:
            while True:
                height, width = stdscr.getmaxyx()
                row = max(0, height - 1)

                # Long descriptive prompts are useful on desktops but can consume
                # nearly the whole line in Termux. Collapse only the presentation;
                # the input buffer itself remains completely independent of width.
                usable_width = max(1, width - 1)
                if len(full_label) + 8 <= usable_width:
                    label = full_label
                elif usable_width >= 3:
                    label = "> "
                else:
                    label = ""

                field_width = max(1, usable_width - len(label))
                visible = _prompt_input_window(value, field_width)

                try:
                    stdscr.move(row, 0)
                    stdscr.clrtoeol()
                    if label:
                        stdscr.addstr(row, 0, label[:usable_width])
                    if visible and len(label) < usable_width:
                        stdscr.addstr(
                            row,
                            len(label),
                            visible[:field_width],
                        )
                    cursor_x = min(
                        usable_width,
                        len(label) + len(visible),
                    )
                    stdscr.move(row, cursor_x)
                    stdscr.refresh()
                except curses.error:
                    pass

                try:
                    key = stdscr.get_wch()
                except curses.error:
                    continue

                if key in ("\n", "\r", 10, 13, curses.KEY_ENTER):
                    return value.strip()
                if key in ("\x1b", 27):
                    return ""
                if key in ("\b", "\x7f", curses.KEY_BACKSPACE, 127, 8):
                    value = value[:-1]
                    continue
                if key in ("\x15", 21):  # Ctrl+U
                    value = ""
                    continue
                if key == curses.KEY_RESIZE:
                    continue

                if isinstance(key, str):
                    if key.isprintable():
                        value += key
                    continue

                if isinstance(key, int) and 32 <= key <= 126:
                    value += chr(key)
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            stdscr.nodelay(True)
            stdscr.timeout(100)

    def open_youtube_search(self, stdscr, search_mode="all"):
        if not self.youtube.enabled:
            self.set_status(
                "Internet Nest is disabled for this run. Restart without --no-youtube.",
                "The internet cat was told to stay home. Restart without --no-youtube.",
            )
            return False

        if not self.youtube.available:
            self.set_status(
                "YouTube unavailable: yt-dlp was not found on PATH.",
                "The internet cat cannot find yt-dlp.",
            )
            return False

        requested_mode = "artist" if search_mode == "artist" else "all"
        prompt = self.text(
            "YouTube artist search" if requested_mode == "artist" else "YouTube search",
            (
                "Internet Nest artist scent"
                if requested_mode == "artist"
                else "Internet Nest search (artist:Name also works)"
            ),
        )
        query = self.prompt_text(stdscr, prompt)
        query, search_mode = normalize_youtube_search(query, requested_mode)
        if not query:
            LOGGER.debug("YouTube search cancelled or empty")
            return False

        LOGGER.info(
            "YouTube search requested mode=%s query=%r",
            search_mode,
            query,
        )
        if self.youtube_search_session:
            self.youtube_search_session.close()
        self.youtube_query = query
        self.youtube_search_mode = search_mode
        self.youtube_results = []
        self.youtube_selected = 0
        self._prefetch_selection = None
        self.youtube_search_session = YouTubeSearchSession(
            self.youtube,
            query,
            search_mode=search_mode,
        )
        self.view = "online"
        if search_mode == "artist":
            self.set_status(
                f"Searching YouTube for artist: {query}...",
                f'The internet cat is stalking artist "{query}"...',
            )
        else:
            self.set_status("Searching YouTube...", "The internet cat is hunting...")
        return True

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
        rows = self.library_rows()

        if self.smart_top_level():
            if rows:
                self.selected = max(
                    0,
                    min(self.selected, len(rows) - 1),
                )
            else:
                self.selected = 0

            if self.selected < scroll:
                scroll = self.selected
            if self.selected >= scroll + list_height:
                scroll = self.selected - list_height + 1

            if not rows:
                message = self.text(
                    "No smart playlists are available.",
                    "The cat could not assemble any Smart Mixes."
                )
                try:
                    stdscr.addstr(
                        list_start,
                        2,
                        message[:width - 4],
                        curses.A_DIM,
                    )
                except curses.error:
                    pass
                return scroll

            for screen_row, row_index in enumerate(
                range(
                    scroll,
                    min(len(rows), scroll + list_height),
                )
            ):
                _, label, _ = rows[row_index]
                selected = row_index == self.selected
                prefix = (
                    ">^.^< "
                    if selected and not self.serious_mode
                    else "▶  "
                    if selected
                    else "   "
                )
                attr = curses.A_REVERSE if selected else curses.A_NORMAL

                try:
                    stdscr.addstr(
                        list_start + screen_row,
                        2,
                        (prefix + label)[:width - 4],
                        attr,
                    )
                except curses.error:
                    pass

            return scroll

        ordered = self.ordered_library_indices()

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

    def draw_youtube(
        self,
        stdscr,
        width,
        list_start,
        list_height,
        scroll,
    ):
        results = self.youtube_results

        if results:
            self.youtube_selected = max(
                0,
                min(self.youtube_selected, len(results) - 1),
            )
        else:
            self.youtube_selected = 0

        if self.youtube_selected < scroll:
            scroll = self.youtube_selected
        if self.youtube_selected >= scroll + list_height:
            scroll = self.youtube_selected - list_height + 1

        if not results:
            message = self.text(
                "No YouTube results. Press / or Y to search, A for artist search.",
                "The Internet Nest is empty. / hunts songs; A stalks an artist.",
            )
            try:
                stdscr.addstr(
                    list_start,
                    2,
                    message[:max(1, width - 4)],
                    curses.A_DIM,
                )
            except curses.error:
                pass
            return scroll

        for screen_row, result_index in enumerate(
            range(scroll, min(len(results), scroll + list_height))
        ):
            track = results[result_index]
            selected = result_index == self.youtube_selected
            playing = (
                self.online_current is not None
                and track.video_id == self.online_current.video_id
            )
            download_track = getattr(self, "youtube_download_track", None)
            downloading = (
                download_track is not None
                and track.video_id == download_track.video_id
            )

            if playing:
                prefix = "▶  " if self.serious_mode else "🐾 "
            elif selected and not self.serious_mode:
                prefix = ">^.^< "
            else:
                prefix = "   "

            label = (
                f"{track.artist_title} · {track.duration_label} · YouTube"
            )
            if downloading:
                label += self.text(" · downloading", " · adopting")
            attr = curses.A_REVERSE if selected else curses.A_NORMAL
            if playing:
                attr |= curses.color_pair(2)

            try:
                stdscr.addstr(
                    list_start + screen_row,
                    2,
                    (prefix + label)[:max(1, width - 4)],
                    attr,
                )
            except curses.error:
                pass

        return scroll

    def draw_creator(
        self,
        stdscr,
        width,
        list_start,
        list_height,
        scroll,
    ):
        if self.creator_level == "menu":
            items = [
                self.text("Singles / Uploads", "Singles / Uploads"),
                self.text("Playlists / Releases", "Release Basket"),
            ]
        else:
            items = self.creator_items

        if items:
            self.creator_selected = max(
                0,
                min(self.creator_selected, len(items) - 1),
            )
        else:
            self.creator_selected = 0

        if self.creator_selected < scroll:
            scroll = self.creator_selected
        if self.creator_selected >= scroll + list_height:
            scroll = self.creator_selected - list_height + 1

        if not items:
            message = self.text(
                "Loading creator items...",
                "The creator cat is still sniffing around...",
            )
            if self.creator_session is None:
                message = self.text(
                    "No items found in this creator section.",
                    "This corner of the Creator Nest is empty.",
                )
            try:
                stdscr.addstr(
                    list_start,
                    2,
                    message[:max(1, width - 4)],
                    curses.A_DIM,
                )
            except curses.error:
                pass
            return scroll

        for screen_row, item_index in enumerate(
            range(scroll, min(len(items), scroll + list_height))
        ):
            item = items[item_index]
            selected = item_index == self.creator_selected
            prefix = ">^.^< " if selected and not self.serious_mode else "   "

            if self.creator_level == "menu":
                label = str(item)
            elif self.creator_level == "playlists":
                label = f"{item.title} · {item.count_label}"
            else:
                playing = (
                    self.online_current is not None
                    and item.video_id == self.online_current.video_id
                )
                if playing:
                    prefix = "▶  " if self.serious_mode else "🐾 "
                label = f"{item.artist_title} · {item.duration_label} · YouTube"
                active_download = getattr(self, "youtube_download_track", None)
                if (
                    active_download is not None
                    and item.video_id == active_download.video_id
                ):
                    label += self.text(" · downloading", " · adopting")

            attr = curses.A_REVERSE if selected else curses.A_NORMAL
            try:
                stdscr.addstr(
                    list_start + screen_row,
                    2,
                    (prefix + label)[:max(1, width - 4)],
                    attr,
                )
            except curses.error:
                pass

        return scroll

    def draw_settings(
        self,
        stdscr,
        width,
        list_start,
        list_height,
        scroll,
    ):
        count = len(SETTINGS_SPECS)
        if not count:
            return 0

        self.settings_selected = max(
            0,
            min(self.settings_selected, count - 1),
        )
        if self.settings_selected < scroll:
            scroll = self.settings_selected
        if self.settings_selected >= scroll + list_height:
            scroll = self.settings_selected - list_height + 1

        for screen_row, setting_index in enumerate(
            range(scroll, min(count, scroll + list_height))
        ):
            spec = SETTINGS_SPECS[setting_index]
            selected = setting_index == self.settings_selected
            value = format_setting_value(spec, self.setting_value(spec))
            label = spec.label if self.serious_mode else spec.cat_label
            scope = "LIVE" if spec.live else "NEXT LAUNCH"
            prefix = (
                "> " if self.serious_mode and selected
                else ">^.^< " if selected
                else "  "
            )
            text = f"{prefix}{label:<34} [{value:^12}]  {scope}"
            attr = curses.A_REVERSE if selected else curses.A_NORMAL
            if not spec.live:
                attr |= curses.A_DIM

            try:
                stdscr.addstr(
                    list_start + screen_row,
                    2,
                    text[:max(1, width - 4)],
                    attr,
                )
            except curses.error:
                pass

        detail_row = list_start + min(count - scroll, list_height)
        if detail_row < list_start + list_height:
            spec = SETTINGS_SPECS[self.settings_selected]
            detail = spec.description
            if not spec.live:
                detail += " Saved now; takes effect on the next launch."
            try:
                stdscr.addstr(
                    detail_row,
                    2,
                    detail[:max(1, width - 4)],
                    curses.A_DIM,
                )
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
        youtube_scroll = 0
        creator_scroll = 0
        settings_scroll = 0
        self.sync_mpris(force=True)

        while True:
            self.process_external_actions()
            self.process_youtube()
            self.process_creator_browse()
            self.process_youtube_download()
            self.refresh_online_playback_state()
            self.playback_saboteur.tick(self)
            math_question = self.playback_saboteur.pop_math_question()
            if math_question is not None:
                self.handle_bad_larry_math_incident(stdscr, math_question)
            self.process_filesystem_watch()
            self.process_online_metadata()
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

            album_art_path = self.current_album_art()
            art_layout = (
                None
                if self.view in {"lyrics", "settings"}
                else self.album_art_layout(
                    height,
                    width,
                    album_art_path,
                )
            )
            top_width = (
                art_layout["text_width"]
                if art_layout is not None
                else width
            )

            content_start = self.draw_header(stdscr, top_width)

            if self.online_current is not None:
                paused = self.mpv.get_property("pause")
                if self.online_load_state in {"resolving", "loading"}:
                    icon = "…"
                    label = self.text(
                        "Loading Stream" if self.online_load_state == "loading" else "Resolving Stream",
                        "Internet Cat Hunting",
                    )
                elif self.online_load_state == "failed":
                    icon = "!"
                    label = self.text(
                        "Stream Failed",
                        "Internet Cat Returned Empty-Pawed",
                    )
                else:
                    icon = "⏸" if paused else "▶"
                    label = self.text(
                        "Now Streaming",
                        "Now Internet-Purring",
                    )
                now_playing = (
                    f"{icon}  {label}: {self.online_current.artist_title} "
                    "· YouTube"
                )
            elif self.current is not None:
                meta = self.meta(self.current)
                paused = self.mpv.get_property("pause")
                icon = "⏸" if paused else "▶"
                if self.serious_mode:
                    label = "Now Playing"
                else:
                    mood = self.cat_mood()
                    label = {
                        "Screaming": "Now YOWLING",
                        "Whispering": "Now tiny-purring",
                    }.get(mood, "Now Purring")
                now_playing = f"{icon}  {label}: {meta.artist_title}"
            else:
                now_playing = self.text(
                    "No song playing",
                    "No song meowing right now"
                )

            progress_y = content_start + 2
            visualizer_y = content_start + 3
            inline_lyric = self.current_lyric_text()
            has_synced_lyrics = bool(
                self.current_lyrics is not None
                and self.current_lyrics.synced
            )
            lyric_shift = 1 if has_synced_lyrics else 0
            lyric_y = content_start + 4
            info_y = content_start + 4 + lyric_shift
            status_y = content_start + 5 + lyric_shift
            mode_y = content_start + 6 + lyric_shift
            list_start = content_start + 8 + lyric_shift

            try:
                stdscr.addstr(
                    content_start,
                    2,
                    now_playing[:top_width - 4],
                    curses.A_BOLD | curses.color_pair(2)
                )
                stdscr.addstr(
                    progress_y,
                    2,
                    self.progress_bar(top_width - 4)[:top_width - 4]
                )
            except curses.error:
                pass

            spectrum = self.visualizer.render(
                max(1, top_width - 4)
            )
            if spectrum:
                try:
                    stdscr.addstr(
                        visualizer_y,
                        2,
                        spectrum[:top_width - 4],
                        curses.color_pair(1),
                    )
                except curses.error:
                    pass

            if inline_lyric:
                lyric_label = (
                    inline_lyric
                    if self.serious_mode
                    else f"♫ {inline_lyric}"
                )
                try:
                    stdscr.addstr(
                        lyric_y,
                        2,
                        lyric_label[:top_width - 4],
                        curses.A_BOLD,
                    )
                except curses.error:
                    pass

            current_rating = (
                int(self.stats_for(self.current).get("rating", 0) or 0)
                if self.current is not None
                else 0
            )
            current_stars = (
                self.rating_stars(self.current, include_unrated=True)
                if self.current is not None
                else "☆☆☆☆☆"
            )

            if self.serious_mode:
                shuffle_info = (
                    f"ON ({len(self.shuffle_bag)} left)"
                    if self.shuffle
                    else "OFF"
                )
                info = (
                    f"Volume: {self.volume}%   "
                    f"Shuffle: {shuffle_info}   "
                    f"Repeat: {'ON' if self.repeat else 'OFF'}   "
                    f"Queue: {len(self.catnip_stash)}   "
                    f"Rating: {current_rating}/5"
                )
            else:
                pounce_info = (
                    f"ON ({len(self.shuffle_bag)} left)"
                    if self.shuffle
                    else "OFF"
                )
                info = (
                    f"Meow Level: {self.volume}%   "
                    f"Pounce: {pounce_info}   "
                    f"Tail-Chase: {'ON' if self.repeat else 'OFF'}   "
                    f"Catnip: {len(self.catnip_stash)}   "
                    f"Verdict: {current_stars}   "
                    f"Mood: {self.cat_mood()}"
                    + (
                        f"   Scritches: {self.scritches}"
                        if self.scritches
                        else ""
                    )
                    + (
                        f"   {self.cat_chaos_summary()}"
                        if self.playback_saboteur.enabled
                        else ""
                    )
                )

            try:
                stdscr.addstr(
                    info_y,
                    2,
                    info[:top_width - 4],
                    curses.color_pair(3)
                )
                stdscr.addstr(
                    status_y,
                    2,
                    self.status_message[:top_width - 4],
                    curses.color_pair(4)
                    if not self.serious_mode
                    else curses.A_DIM
                )
            except curses.error:
                pass

            if self.view == "lyrics":
                if self.current_lyrics is None:
                    mode_line = self.text(
                        "Lyrics — unavailable for this track",
                        "Songbook — no words found for this meow"
                    )
                else:
                    lyric_kind = (
                        "synchronized"
                        if self.current_lyrics.synced
                        else "plain"
                    )
                    follow = (
                        "follow"
                        if self.lyrics_follow
                        else "manual scroll"
                    )
                    mode_line = self.text(
                        (
                            f"Lyrics — {lyric_kind} · "
                            f"{self.current_lyrics.source} · {follow}"
                        ),
                        (
                            f"Songbook — {lyric_kind} · "
                            f"{self.current_lyrics.source} · {follow}"
                        )
                    )
            elif self.view == "settings":
                spec = SETTINGS_SPECS[self.settings_selected]
                mode_line = self.text(
                    (
                        f"Settings — {len(SETTINGS_SPECS)} option(s) · "
                        f"selected: {spec.label}"
                    ),
                    (
                        f"SETTINGS NEST — {len(SETTINGS_SPECS)} household rule(s) · "
                        f"paw on: {spec.cat_label}"
                    ),
                )
            elif self.view == "creator":
                if self.creator_level == "menu":
                    section = "channel"
                    count = 2
                elif self.creator_level == "uploads":
                    section = "singles / uploads"
                    count = len(self.creator_items)
                elif self.creator_level == "playlists":
                    section = "playlists"
                    count = len(self.creator_items)
                else:
                    section = (
                        self.creator_playlist.title
                        if self.creator_playlist is not None
                        else "playlist"
                    )
                    count = len(self.creator_items)
                mode_line = self.text(
                    f"Creator — {self.creator_name} / {section} · {count} item(s)",
                    f"Creator Nest — {self.creator_name} / {section} · {count} thing(s)",
                )
            elif self.view == "online":
                query = self.youtube_query or "none"
                artist_search = self.youtube_search_mode == "artist"
                serious_label = "artist" if artist_search else "query"
                cat_label = "artist scent" if artist_search else "scent"
                mode_line = self.text(
                    (
                        f"YouTube Online — {serious_label}: {query} · "
                        f"{len(self.youtube_results)} result(s)"
                    ),
                    (
                        f"Internet Nest — {cat_label}: {query} · "
                        f"{len(self.youtube_results)} meow(s)"
                    ),
                )
            elif self.view == "library":
                current_view = self.library_breadcrumb()

                if self.smart_top_level():
                    mix_count = len(self.smart_playlists())
                    mode_line = self.text(
                        (
                            f"Library / {current_view} — "
                            f"{mix_count} smart playlist(s) · Enter to open"
                        ),
                        (
                            f"Music Nest / {current_view} — "
                            f"{mix_count} Smart Mix(es) · Enter to inspect"
                        )
                    )
                else:
                    matches = len(self.filtered_song_indices())

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
                    mode_line[:top_width - 4],
                    curses.A_BOLD
                )
            except curses.error:
                pass

            footer_lines = 3 if not self.serious_mode else 2
            list_height = max(
                1,
                height - list_start - footer_lines - 1
            )

            lyrics_art_layout = None
            if self.view == "lyrics":
                lyrics_art_layout = self.lyrics_album_art_layout(
                    height,
                    width,
                    album_art_path,
                    list_start,
                    list_height,
                )
                lyrics_width = (
                    lyrics_art_layout["lyrics_width"]
                    if lyrics_art_layout is not None
                    else width
                )

                if lyrics_art_layout is not None:
                    try:
                        stdscr.vline(
                            list_start,
                            lyrics_art_layout["divider_column"],
                            curses.ACS_VLINE,
                            list_height,
                            curses.A_DIM,
                        )
                    except curses.error:
                        pass

                self.draw_lyrics(
                    stdscr,
                    lyrics_width,
                    list_start,
                    list_height,
                )
            elif self.view == "library":
                library_scroll = self.draw_library(
                    stdscr,
                    width,
                    list_start,
                    list_height,
                    library_scroll,
                )
            elif self.view == "settings":
                settings_scroll = self.draw_settings(
                    stdscr,
                    width,
                    list_start,
                    list_height,
                    settings_scroll,
                )
            elif self.view == "creator":
                creator_scroll = self.draw_creator(
                    stdscr,
                    width,
                    list_start,
                    list_height,
                    creator_scroll,
                )
            elif self.view == "online":
                youtube_scroll = self.draw_youtube(
                    stdscr,
                    width,
                    list_start,
                    list_height,
                    youtube_scroll,
                )
            else:
                stash_scroll = self.draw_stash(
                    stdscr,
                    width,
                    list_start,
                    list_height,
                    stash_scroll,
                )

            self.maybe_trigger_cat_incident()

            if (
                not self.serious_mode
                and time.monotonic() - self.last_quote_change > 20
            ):
                self.quote = random.choice(CAT_QUOTES)
                self.last_quote_change = time.monotonic()

            if self.view == "lyrics":
                if self.serious_mode:
                    controls = (
                        "↑↓ Scroll  ENTER Follow  [ ] Rate  L Back  V Visualizer  "
                        "N/P Track  , Settings  Space Pause  X Quit"
                    )
                    quote = ""
                else:
                    controls = (
                        "↑↓ Scroll  ENTER Follow  [ ] Judge  L Close Songbook  "
                        "N/P Meow  , Settings  G Pet  Space Paws  X Escape"
                    )
                    quote = self.cat_footer_message()
            elif self.view == "library":
                if self.serious_mode:
                    controls = (
                        "↑↓ Select  ENTER Open/Play  1-7 Views  F Favorite  "
                        "[ ] Rate  L Lyrics  V Viz  M Mixes  Y YouTube  , Settings  Q Queue  X Quit"
                    )
                    quote = ""
                else:
                    controls = (
                        "↑↓ Choose  ENTER Open/Purr  1-7 Nests  F Pawmark  "
                        "[ ] Judge  L Songbook  M Mixes  Y Internet  , Settings  G Pet  Q Catnip"
                    )
                    quote = self.cat_footer_message()
            elif self.view == "settings":
                if self.serious_mode:
                    controls = (
                        "↑↓ Select  ←→ Change  Enter/Space Toggle  "
                        "R Reset  ,/Q/Esc Back  X Quit"
                    )
                    quote = ""
                else:
                    controls = (
                        "↑↓ Paw  ←→ Nudge  Enter/Space Change  "
                        "R Factory Meow  ,/Q/Esc Leave Nest  X Escape"
                    )
                    quote = self.cat_footer_message()
            elif self.view == "creator":
                if self.creator_level == "menu":
                    controls = self.text(
                        "↑↓ Select  ENTER Open  Esc Back  Q Library  X Quit",
                        "↑↓ Choose  ENTER Enter  Esc Back  Q Music Nest  X Escape",
                    )
                elif self.creator_level == "playlists":
                    controls = self.text(
                        "↑↓ Select  ENTER Open Release  Esc Back  Q Library  X Quit",
                        "↑↓ Choose  ENTER Open Release  Esc Back  Q Music Nest  X Escape",
                    )
                else:
                    controls = self.text(
                        "↑↓ Select  ENTER Stream  D Download  Esc Back  Q Library  X Quit",
                        "↑↓ Choose  ENTER Stream  D Adopt  Esc Back  Q Music Nest  X Escape",
                    )
                quote = "" if self.serious_mode else self.cat_footer_message()
            elif self.view == "online":
                if self.serious_mode:
                    controls = (
                        "↑↓ Select  ENTER Stream  C Creator  D Download  / Search  "
                        "A Artist  Y Search  , Settings  Q Library  Space Pause  X Quit"
                    )
                    quote = ""
                else:
                    controls = (
                        "↑↓ Choose  ENTER Stream  C Creator Nest  D Adopt  / Hunt  "
                        "A Artist Scent  Y Search  , Settings  Q Nest  Space Paws  X Escape"
                    )
                    quote = self.cat_footer_message()
            else:
                if self.serious_mode:
                    controls = (
                        "↑↓ Select  ENTER Play  [ ] Rate  D Remove  J/K Move  "
                        "C Clear  W Save .m3u  O Load .m3u  , Settings  Q Library  X Quit"
                    )
                    quote = ""
                else:
                    controls = (
                        "↑↓ Choose  ENTER Devour  [ ] Judge  D Yeet  J/K Rearrange  "
                        "C Spill  W Bury .m3u  O Dig up .m3u  , Settings  G Pet  Q Nest  X Escape"
                    )
                    quote = self.cat_footer_message()

            if self.maximum_meow and quote:
                quote = f"🐱 MAXIMUM MEOW: {self.quote} 🐾♫🐾"

            if self.playback_saboteur.mode == "dangerous":
                controls += "  Ctrl+E Dismiss Larry"

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

            render_art_layout = (
                None
                if self.view == "settings"
                else (
                    lyrics_art_layout
                    if self.view == "lyrics"
                    else art_layout
                )
            )
            if render_art_layout is not None:
                self.album_art.render(
                    album_art_path,
                    render_art_layout["row"],
                    render_art_layout["column"],
                    render_art_layout["columns"],
                    render_art_layout["rows"],
                )
            else:
                self.album_art.clear(free_data=False)

            self.refresh_current_lyrics()
            transitioned = self.sync_gapless_transition()

            if (
                self.current is not None
                and not self.repeat
                and not transitioned
            ):
                eof = self.mpv.get_property("eof-reached")
                if (
                    eof
                    and (
                        self.gapless_mode == "no"
                        or self.gapless_next_index is None
                    )
                ):
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

            if (
                key == 5
                and self.playback_saboteur.mode == "dangerous"
            ):
                apology = self.prompt_bad_larry_apology(stdscr)
                if apology_matches(apology):
                    self.playback_saboteur.dismiss(self)
                    self.cat_chaos_mode = None
                    self.set_status(
                        "Dangerous Cat Mode disabled.",
                        "Bad Larry accepts your apology and has left The Room.",
                    )
                else:
                    self.set_status(
                        "Emergency dismissal denied.",
                        "Bad Larry: that did not sound sincere. Try again, human.",
                    )
                    self.trigger_cat_incident(
                        "BAD LARRY: FORMAL APOLOGY REJECTED.",
                        duration=6.0,
                    )
                continue

            if self.view == "settings":
                if key == curses.KEY_UP:
                    self.settings_selected = max(
                        0,
                        self.settings_selected - 1,
                    )
                    continue
                if key == curses.KEY_DOWN:
                    self.settings_selected = min(
                        len(SETTINGS_SPECS) - 1,
                        self.settings_selected + 1,
                    )
                    continue
                if key == curses.KEY_LEFT:
                    self.change_selected_setting(direction=-1)
                    continue
                if key == curses.KEY_RIGHT:
                    self.change_selected_setting(direction=1)
                    continue
                if key in (10, 13, curses.KEY_ENTER, ord(" ")):
                    self.change_selected_setting(direction=1)
                    continue
                if key in (ord("r"), ord("R")):
                    self.change_selected_setting(reset=True)
                    continue
                if key in (ord(","), ord("q"), ord("Q"), 27):
                    self.close_settings_nest()
                    continue
                if key not in (ord("x"), ord("X")):
                    continue

            if key == ord(","):
                self.open_settings_nest()
                settings_scroll = 0
                continue

            if key in (ord("x"), ord("X")):
                if self.cat_intercepts("quit"):
                    continue
                self.set_status(
                    "Quitting.",
                    "Escaping before the cat notices..."
                )
                break

            if key in (ord("l"), ord("L")):
                self.toggle_lyrics_view()
                continue

            if key in (ord("m"), ord("M")):
                self.reload_custom_smart_mixes()
                continue

            if key in (ord("y"), ord("Y")):
                if self.open_youtube_search(stdscr):
                    youtube_scroll = 0
                continue

            if key in (ord("g"), ord("G")):
                self.pet_cat()
                continue

            if key == ord("["):
                self.adjust_rating(-1)
                continue

            if key == ord("]"):
                self.adjust_rating(1)
                continue

            if key in (ord("v"), ord("V")):
                if not self.visualizer.available:
                    self.set_status(
                        "Visualizer unavailable: install CAVA.",
                        "No spectrum cat found. Install CAVA first."
                    )
                else:
                    visible = self.visualizer.toggle()
                    self.set_status(
                        (
                            f"Visualizer {'enabled' if visible else 'disabled'}."
                        ),
                        (
                            f"Spectrum {'purring' if visible else 'sleeping'}."
                        )
                    )
                continue

            if key in (ord("q"), ord("Q")):
                if self.view == "lyrics":
                    self.view = self.previous_view
                    self.set_status(
                        "Returned from lyrics.",
                        "The cat closed the songbook."
                    )
                    continue

                if self.view in {"online", "creator"}:
                    self.view = "library"
                    self.set_status(
                        "Returned to local library.",
                        "The internet cat came back to the Music Nest.",
                    )
                    continue

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
                if self.cat_intercepts("pause"):
                    continue
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
                if self.cat_intercepts("seek_forward"):
                    continue
                self.mpv.seek(5)
                self.set_status(
                    "Seeked forward 5 seconds.",
                    "Scritched 5 seconds into the future."
                )
                continue

            if key == curses.KEY_LEFT:
                if self.cat_intercepts("seek_backward"):
                    continue
                self.mpv.seek(-5)
                self.set_status(
                    "Seeked backward 5 seconds.",
                    "Backtracked 5 seconds on tiny paws."
                )
                continue

            if key in (ord("n"), ord("N")):
                if not self.cat_intercepts("next"):
                    self.next_song()
                continue

            if key in (ord("p"), ord("P")):
                if not self.cat_intercepts("previous"):
                    self.previous_song()
                continue

            if key in (ord("+"), ord("=")):
                if not self.cat_intercepts("volume_up"):
                    self.update_volume(5)
                continue

            if key == ord("-"):
                if not self.cat_intercepts("volume_down"):
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
                self.prime_gapless_next()
                continue

            if self.view == "lyrics":
                document = self.current_lyrics
                if key == curses.KEY_UP and document is not None:
                    self.lyrics_follow = False
                    self.lyrics_scroll = max(
                        0,
                        self.lyrics_scroll - 1,
                    )
                elif key == curses.KEY_DOWN and document is not None:
                    self.lyrics_follow = False
                    self.lyrics_scroll = min(
                        max(0, len(document.lines) - 1),
                        self.lyrics_scroll + 1,
                    )
                elif key in (10, 13, curses.KEY_ENTER):
                    self.lyrics_follow = True
                    self.set_status(
                        "Lyrics follow resumed.",
                        "The songbook is following the meow again."
                    )

            elif self.view == "library":
                if self.smart_top_level():
                    navigation_count = len(self.smart_playlists())
                else:
                    navigation_count = len(self.ordered_library_indices())

                if key == curses.KEY_UP and navigation_count:
                    self.selected = max(0, self.selected - 1)
                elif key == curses.KEY_DOWN and navigation_count:
                    self.selected = min(
                        navigation_count - 1,
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
                    if self.smart_top_level():
                        self.set_status(
                            "Open a smart playlist before searching it.",
                            "Open a Smart Mix first, then follow a scent."
                        )
                    else:
                        self.search_active = True
                        self.search_query = ""
                        self.selected = 0
                        self.set_status(
                            (
                                "Type to search tags and paths. "
                                "Enter keeps filter; Esc clears it."
                            ),
                            (
                                "Sniff tags, albums, artists, genres, and folders. "
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
                    ord("7"),
                ):
                    self.select_library_view(
                        LIBRARY_VIEWS[int(chr(key)) - 1]
                    )
                    library_scroll = 0

            elif self.view == "online":
                if key == curses.KEY_UP and self.youtube_results:
                    self.youtube_selected = max(
                        0,
                        self.youtube_selected - 1,
                    )
                elif key == curses.KEY_DOWN and self.youtube_results:
                    self.youtube_selected = min(
                        len(self.youtube_results) - 1,
                        self.youtube_selected + 1,
                    )
                elif key in (10, 13, curses.KEY_ENTER):
                    self.play_selected_youtube_result()
                elif key in (ord("d"), ord("D")):
                    self.download_selected_youtube_result()
                elif key in (ord("c"), ord("C")):
                    if self.open_selected_youtube_creator():
                        creator_scroll = 0
                elif key == ord("/"):
                    if self.open_youtube_search(stdscr):
                        youtube_scroll = 0
                elif key in (ord("a"), ord("A")):
                    if self.open_youtube_search(stdscr, search_mode="artist"):
                        youtube_scroll = 0
                elif key == 27:
                    self.view = "library"
                    self.set_status(
                        "Returned to local library.",
                        "The cat left the Internet Nest.",
                    )

            elif self.view == "creator":
                item_count = (
                    2
                    if self.creator_level == "menu"
                    else len(self.creator_items)
                )
                if key == curses.KEY_UP and item_count:
                    self.creator_selected = max(
                        0,
                        self.creator_selected - 1,
                    )
                elif key == curses.KEY_DOWN and item_count:
                    self.creator_selected = min(
                        item_count - 1,
                        self.creator_selected + 1,
                    )
                elif key in (10, 13, curses.KEY_ENTER):
                    if self.activate_creator_selection():
                        creator_scroll = 0
                elif key in (ord("d"), ord("D")):
                    self.download_selected_creator_track()
                elif key == 27:
                    if self.go_back_creator():
                        creator_scroll = 0

            elif self.view == "stash":
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


def parse_args(argv=None):
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
    mode.add_argument(
        "--bad-bad-cat",
        action="store_true",
        help="let a mildly malicious cat occasionally interfere with playback"
    )
    mode.add_argument(
        "--very-bad-cat",
        action="store_true",
        help="let a hostile cat actively fight your playback controls"
    )
    mode.add_argument(
        "--dangerous-cat",
        action="store_true",
        help="summon Bad Larry after three explicit confirmations"
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
    parser.add_argument(
        "--no-album-art",
        action="store_true",
        help="disable terminal album-art rendering for this run"
    )
    parser.add_argument(
        "--gapless-mode",
        choices=("no", "weak", "yes"),
        default=None,
        help=(
            "mpv gapless mode: weak preserves quality across differing "
            "formats when needed; yes keeps one output format; no disables it"
        )
    )
    parser.add_argument(
        "--replaygain",
        choices=("no", "track", "album"),
        default=None,
        help="ReplayGain mode for this run"
    )
    parser.add_argument(
        "--replaygain-preamp",
        type=float,
        default=None,
        help="ReplayGain preamp in dB for this run"
    )
    parser.add_argument(
        "--no-lyrics",
        action="store_true",
        help="disable local, embedded, cached, and online lyrics for this run"
    )
    parser.add_argument(
        "--no-online-lyrics",
        action="store_true",
        help="disable automatic LRCLIB lookup while keeping local lyrics enabled"
    )
    parser.add_argument(
        "--no-online-metadata",
        action="store_true",
        help=(
            "disable automatic MusicBrainz metadata enrichment "
            "for incomplete tracks"
        )
    )
    parser.add_argument(
        "--no-visualizer",
        action="store_true",
        help="disable the optional CAVA spectrum visualizer"
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="disable live filesystem watching for the music library"
    )
    youtube_mode = parser.add_mutually_exclusive_group()
    youtube_mode.add_argument(
        "--youtube",
        dest="youtube",
        action="store_true",
        help=(
            "enable Internet Nest (accepted for compatibility; "
            "enabled by default since 0.18.0)"
        ),
    )
    youtube_mode.add_argument(
        "--no-youtube",
        dest="youtube",
        action="store_false",
        help="disable Internet Nest / YouTube search and streaming for this run",
    )
    parser.set_defaults(youtube=True)
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "enable rotating MeowPlayer debug logs and a separate verbose "
            "mpv log under the XDG state directory"
        )
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        default=None,
        help=(
            "write MeowPlayer debug logs to PATH; implies --debug "
            "(mpv uses a sibling .mpv log)"
        )
    )

    return parser.parse_args(argv)


def main():
    args = parse_args()

    try:
        debug_log_path = configure_debug_logging(
            enabled=args.debug,
            log_file=args.log_file,
        )
    except OSError as exc:
        print(
            f"Could not enable MeowPlayer debug logging: {exc}",
            file=sys.stderr,
        )
        return 2

    mpv_log_path = (
        mpv_debug_log_path(debug_log_path)
        if debug_log_path is not None
        else None
    )
    if mpv_log_path is not None:
        try:
            mpv_log_path.parent.mkdir(parents=True, exist_ok=True)
            mpv_log_path.unlink(missing_ok=True)
        except OSError as exc:
            LOGGER.warning("Could not prepare mpv debug log: %s", exc)
            mpv_log_path = None

    LOGGER.info("MeowPlayer %s starting", __version__)
    LOGGER.debug(
        "runtime python=%s platform=%s cwd=%s",
        sys.version.replace("\n", " "),
        sys.platform,
        Path.cwd(),
    )
    LOGGER.debug(
        "launch options music_dir=%r youtube=%s serious=%s maximum_meow=%s "
        "bad_bad=%s very_bad=%s dangerous=%s gapless=%r replaygain=%r",
        args.music_dir,
        args.youtube,
        args.serious_mode,
        args.maximum_meow,
        args.bad_bad_cat,
        args.very_bad_cat,
        args.dangerous_cat,
        args.gapless_mode,
        args.replaygain,
    )
    if debug_log_path is not None:
        LOGGER.info("MeowPlayer debug log: %s", debug_log_path)
        LOGGER.info("mpv debug log: %s", mpv_log_path)

    if args.dangerous_cat and not confirm_dangerous_cat():
        LOGGER.info("Dangerous Cat confirmation cancelled")
        shutdown_debug_logging()
        return

    if args.dangerous_cat:
        cat_chaos_mode = "dangerous"
    elif args.very_bad_cat:
        cat_chaos_mode = "very-bad"
    elif args.bad_bad_cat:
        cat_chaos_mode = "bad-bad"
    else:
        cat_chaos_mode = None

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
    album_art_enabled = (
        bool(config.get("album_art_enabled", True))
        and not args.no_album_art
    )

    configured_gapless = str(
        config.get("gapless_mode", "weak")
    ).lower()
    gapless_mode = (
        args.gapless_mode
        or (
            configured_gapless
            if configured_gapless in {"no", "weak", "yes"}
            else "weak"
        )
    )

    configured_replaygain = str(
        config.get("replaygain_mode", "track")
    ).lower()
    replaygain_mode = (
        args.replaygain
        or (
            configured_replaygain
            if configured_replaygain in {"no", "track", "album"}
            else "track"
        )
    )

    try:
        configured_preamp = float(
            config.get("replaygain_preamp", 0.0)
        )
    except (TypeError, ValueError):
        configured_preamp = 0.0

    replaygain_preamp = (
        args.replaygain_preamp
        if args.replaygain_preamp is not None
        else configured_preamp
    )
    lyrics_enabled = (
        bool(config.get("lyrics_enabled", True))
        and not args.no_lyrics
    )
    lyrics_online_enabled = (
        bool(config.get("lyrics_online_enabled", True))
        and not args.no_online_lyrics
    )
    online_metadata_enabled = (
        bool(config.get("online_metadata_enabled", True))
        and not args.no_online_metadata
    )
    visualizer_enabled = (
        bool(config.get("visualizer_enabled", True))
        and not args.no_visualizer
    )
    filesystem_watch_enabled = (
        bool(config.get("filesystem_watch_enabled", True))
        and not args.no_watch
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
            album_art_enabled=album_art_enabled,
            gapless_mode=gapless_mode,
            replaygain_mode=replaygain_mode,
            replaygain_preamp=replaygain_preamp,
            lyrics_enabled=lyrics_enabled,
            lyrics_online_enabled=lyrics_online_enabled,
            online_metadata_enabled=online_metadata_enabled,
            visualizer_enabled=visualizer_enabled,
            filesystem_watch_enabled=filesystem_watch_enabled,
            cat_chaos_mode=cat_chaos_mode,
            youtube_enabled=args.youtube,
            debug_log_path=debug_log_path,
            mpv_log_path=mpv_log_path,
            app_config=config,
        )
    except FileNotFoundError:
        LOGGER.exception("MPV executable was not found during player startup")
        print(
            "MPV was not found.\n"
            + _platform_install_hint()
        )
        shutdown_debug_logging()
        sys.exit(1)
    except Exception:
        LOGGER.exception("MeowPlayer initialization failed")
        shutdown_debug_logging()
        raise

    if not player.songs and not player.youtube.available:
        message = f"No supported music files found in:\n{music_dir}"
        if args.youtube:
            message += (
                "\n\nYouTube mode was requested, but yt-dlp is unavailable."
            )
        if not args.serious_mode:
            message += (
                "\n\nThe cat searched the entire nest. No tunes. :<"
            )
        print(message)
        player.shutdown()
        shutdown_debug_logging()
        sys.exit(0)

    if not player.songs and player.youtube.available:
        player.set_status(
            "No local tracks found; YouTube search is available with Y.",
            "The local nest is empty, but Y opens the Internet Nest.",
        )

    try:
        curses.wrapper(player.run)
    except Exception:
        LOGGER.exception("Unhandled exception escaped the curses TUI")
        raise
    finally:
        try:
            player.shutdown()
        finally:
            LOGGER.info("MeowPlayer %s exiting", __version__)
            shutdown_debug_logging()


if __name__ == "__main__":
    main()
