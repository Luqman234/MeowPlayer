#!/usr/bin/env python3

import argparse
import curses
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


SUPPORTED_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".opus",
    ".wav", ".m4a", ".aac", ".wma"
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
]

CAT_MASCOT = (
    " /\\_/\\",
    r"( o.o )",
    r" > ^ <",
)

MAXIMUM_MEOW_MASCOT = (
    "  /\\_/\\      ♪",
    r" ( =^.^=)   ♫",
    r'  (")_(")   ♪',
)

TAIL_FRAMES = ("~", "⌁", "∿", "≈")


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

    def load(self, filename):
        self.command("loadfile", str(filename), "replace")

    def toggle_pause(self):
        paused = self.get_property("pause")
        self.set_property("pause", not bool(paused))
        return not bool(paused)

    def seek(self, seconds):
        self.command("seek", seconds, "relative")

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
    def __init__(self, music_dir, serious_mode=False, maximum_meow=False):
        self.music_dir = Path(music_dir).expanduser().resolve()
        self.serious_mode = serious_mode
        self.maximum_meow = maximum_meow

        self.songs = self.find_songs()
        self.song_lookup = {
            song.resolve(): index for index, song in enumerate(self.songs)
        }

        self.selected = 0
        self.stash_selected = 0
        self.current = None
        self.history = []

        self.volume = 70
        self.shuffle = False
        self.repeat = False

        self.view = "library"
        self.catnip_stash = []

        self.search_query = ""
        self.search_active = False

        self.status_message = self.text(
            "Ready. Select a track and press Enter.",
            "The cat is ready. Pick a song and let it purr."
        )
        self.quote = random.choice(CAT_QUOTES)
        self.last_quote_change = time.monotonic()
        self.tail_frame = 0

        self.mpv = MPVController()
        self.mpv.set_property("volume", self.volume)

    def text(self, serious, cat):
        return serious if self.serious_mode else cat

    def set_status(self, serious, cat):
        self.status_message = self.text(serious, cat)

    def find_songs(self):
        songs = []
        for path in self.music_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                songs.append(path)
        return sorted(songs, key=lambda p: p.name.lower())

    def filtered_song_indices(self):
        if not self.search_query:
            return list(range(len(self.songs)))

        query = self.search_query.casefold()
        matches = []

        for index, song in enumerate(self.songs):
            try:
                relative = song.relative_to(self.music_dir)
                haystack = str(relative)
            except ValueError:
                haystack = str(song)

            if query in haystack.casefold():
                matches.append(index)

        return matches

    def selected_library_song(self):
        visible = self.filtered_song_indices()
        if not visible:
            return None

        self.selected = max(0, min(self.selected, len(visible) - 1))
        return visible[self.selected]

    def play(self, index, automatic=False, record_history=True):
        if not self.songs:
            return

        index %= len(self.songs)

        if (
            record_history
            and self.current is not None
            and self.current != index
        ):
            self.history.append(self.current)
            if len(self.history) > 100:
                self.history.pop(0)

        self.current = index
        self.mpv.load(self.songs[index])

        if automatic:
            self.set_status(
                "Playing next track.",
                "The cat found the next meow."
            )
        else:
            self.set_status(
                f"Playing: {self.songs[index].name}",
                "The cat has chosen a song."
            )

    def play_selected_library_song(self):
        index = self.selected_library_song()
        if index is not None:
            self.play(index)

    def add_selected_to_stash(self):
        index = self.selected_library_song()
        if index is None:
            self.set_status(
                "No matching track to add.",
                "The cat found nothing to stash."
            )
            return

        self.catnip_stash.append(index)
        self.stash_selected = len(self.catnip_stash) - 1
        self.set_status(
            f"Added to queue: {self.songs[index].name}",
            f"Stashed the meow: {self.songs[index].name}"
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
                "Playing the next queued track.",
                "The cat pulled the next treat from The Catnip Stash."
            )
        else:
            self.set_status(
                f"Playing queued track: {self.songs[index].name}",
                f"Pulled from The Catnip Stash: {self.songs[index].name}"
            )

        return True

    def next_song(self, automatic=False):
        if not self.songs:
            return

        if self.catnip_stash:
            self.play_stash_position(0, automatic=automatic)
            return

        if self.shuffle:
            if len(self.songs) > 1 and self.current is not None:
                choices = [
                    i for i in range(len(self.songs))
                    if i != self.current
                ]
                index = random.choice(choices)
            else:
                index = random.randrange(len(self.songs))
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

        if self.history:
            index = self.history.pop()
        elif self.current is None:
            index = 0
        else:
            index = (self.current - 1) % len(self.songs)

        self.play(index, record_history=False)
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

        self.set_status(
            f"Removed from queue: {self.songs[index].name}",
            f"Yeeted from The Catnip Stash: {self.songs[index].name}"
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

    def update_volume(self, amount):
        self.volume = max(0, min(100, self.volume + amount))
        self.mpv.set_property("volume", self.volume)

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
            "Scanning your music nest..."
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

        mascot = MAXIMUM_MEOW_MASCOT if self.maximum_meow else CAT_MASCOT
        title = "♫ MEOWPLAYER — terminal purr engine"

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
        if key in (27,):
            self.search_active = False
            self.search_query = ""
            self.selected = 0
            self.set_status("Search cleared.", "Scent trail cleared.")
            return

        if key in (10, 13, curses.KEY_ENTER):
            self.search_active = False
            matches = len(self.filtered_song_indices())
            self.set_status(
                f"Search applied: {matches} match(es).",
                f"Scent locked: {matches} possible meow(s)."
            )
            return

        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.search_query = self.search_query[:-1]
            self.selected = 0
            return

        if 32 <= key <= 126:
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
        visible = self.filtered_song_indices()

        if visible:
            self.selected = max(0, min(self.selected, len(visible) - 1))
        else:
            self.selected = 0

        if self.selected < scroll:
            scroll = self.selected
        if self.selected >= scroll + list_height:
            scroll = self.selected - list_height + 1

        if not visible:
            message = self.text(
                "No tracks match the current search.",
                "No meows match that scent trail."
            )
            try:
                stdscr.addstr(list_start, 2, message[:width - 4], curses.A_DIM)
            except curses.error:
                pass
            return scroll

        for screen_row, visible_position in enumerate(
            range(scroll, min(len(visible), scroll + list_height))
        ):
            song_index = visible[visible_position]
            song = self.songs[song_index]

            if song_index == self.current:
                prefix = "▶  " if self.serious_mode else "🐾 "
            elif visible_position == self.selected and not self.serious_mode:
                prefix = ">^.^< "
            else:
                prefix = "   "

            text = prefix + song.name
            y = list_start + screen_row
            attr = curses.A_NORMAL

            if visible_position == self.selected:
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
            song = self.songs[song_index]
            number = stash_position + 1

            if stash_position == self.stash_selected and not self.serious_mode:
                prefix = f">^.^< {number:02d}. "
            else:
                prefix = f"     {number:02d}. "

            text = prefix + song.name
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

        while True:
            height, width = stdscr.getmaxyx()
            stdscr.erase()

            if height < 16 or width < 46:
                message = self.text(
                    "Terminal too small. Resize to at least 46x16.",
                    "Terminal too small — give this cat at least 46x16."
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
                song = self.songs[self.current]
                paused = self.mpv.get_property("pause")
                icon = "⏸" if paused else "▶"
                label = "Now Playing" if self.serious_mode else "Now Purring"
                now_playing = f"{icon}  {label}: {song.name}"
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
                    f"Catnip: {len(self.catnip_stash)}"
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
                if self.search_active:
                    mode_line = self.text(
                        f"SEARCH > {self.search_query}_   ({matches} match(es))",
                        f"SCENT SEARCH > {self.search_query}_   ({matches} meow(s))"
                    )
                elif self.search_query:
                    mode_line = self.text(
                        f"Library — filter: {self.search_query!r} ({matches} match(es))",
                        f"Music Nest — scent: {self.search_query!r} ({matches} meow(s))"
                    )
                else:
                    mode_line = self.text(
                        f"Library — {len(self.songs)} track(s)",
                        f"Music Nest — {len(self.songs)} meow(s)"
                    )
            else:
                mode_line = self.text(
                    f"Queue — {len(self.catnip_stash)} track(s)",
                    f"THE CATNIP STASH — {len(self.catnip_stash)} treat(s)"
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
                        "↑↓ Select  ENTER Play  / Search  A Add queue  "
                        "Q Queue  SPACE Pause  N/P Track  X Quit"
                    )
                    quote = ""
                else:
                    controls = (
                        "↑↓ Choose  ENTER Purr  / Scent-search  A Stash  "
                        "Q Catnip Stash  SPACE Paws  N/P Meow  X Escape"
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

            if self.current is not None:
                eof = self.mpv.get_property("eof-reached")
                if eof:
                    if self.repeat:
                        self.play(
                            self.current,
                            automatic=True,
                            record_history=False
                        )
                        self.set_status(
                            "Repeating current track.",
                            "Tail-chase engaged: one more purr!"
                        )
                    else:
                        self.next_song(automatic=True)

            key = stdscr.getch()
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
                self.shuffle = not self.shuffle
                self.set_status(
                    f"Shuffle {'enabled' if self.shuffle else 'disabled'}.",
                    f"Pounce Mode {'ENGAGED' if self.shuffle else 'disengaged'}."
                )
                continue

            if key in (ord("r"), ord("R")):
                self.repeat = not self.repeat
                self.set_status(
                    f"Repeat {'enabled' if self.repeat else 'disabled'}.",
                    f"Tail-Chase {'ENGAGED' if self.repeat else 'disengaged'}."
                )
                continue

            if self.view == "library":
                visible = self.filtered_song_indices()

                if key == curses.KEY_UP and visible:
                    self.selected = max(0, self.selected - 1)
                elif key == curses.KEY_DOWN and visible:
                    self.selected = min(
                        len(visible) - 1,
                        self.selected + 1
                    )
                elif key in (10, 13, curses.KEY_ENTER):
                    self.play_selected_library_song()
                elif key in (ord("a"), ord("A")):
                    self.add_selected_to_stash()
                elif key == ord("/"):
                    self.search_active = True
                    self.search_query = ""
                    self.selected = 0
                    self.set_status(
                        "Type to search. Enter keeps filter; Esc clears it.",
                        "Sniff for a song. Enter locks scent; Esc forgets it."
                    )
                elif key == 27 and self.search_query:
                    self.search_query = ""
                    self.selected = 0
                    self.set_status(
                        "Search cleared.",
                        "Scent trail cleared."
                    )

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

        self.mpv.quit()


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "MeowPlayer — a cat-themed terminal music player powered by mpv."
        )
    )
    parser.add_argument(
        "music_dir",
        nargs="?",
        default="~/Music",
        help="music directory to scan recursively (default: ~/Music)"
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

    return parser.parse_args()


def main():
    args = parse_args()
    music_dir = Path(args.music_dir).expanduser()

    if not music_dir.exists():
        print(f"Music directory doesn't exist: {music_dir}")
        sys.exit(1)

    try:
        player = MeowPlayer(
            music_dir,
            serious_mode=args.serious_mode,
            maximum_meow=args.maximum_meow,
        )
    except FileNotFoundError:
        print(
            "MPV was not found.\n"
            "Install it with:\n\n"
            "    sudo pacman -S mpv"
        )
        sys.exit(1)

    if not player.songs:
        message = f"No supported music files found in:\n{music_dir}"
        if not args.serious_mode:
            message += (
                "\n\nThe cat searched the entire nest. No tunes. :<"
            )
        print(message)
        player.mpv.quit()
        sys.exit(0)

    try:
        curses.wrapper(player.run)
    finally:
        player.mpv.quit()


if __name__ == "__main__":
    main()
