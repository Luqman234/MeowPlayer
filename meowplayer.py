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
        self.selected = 0
        self.current = None
        self.volume = 70
        self.shuffle = False
        self.repeat = False

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

    def play(self, index, automatic=False):
        if not self.songs:
            return

        index %= len(self.songs)
        self.current = index
        self.selected = index
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

    def next_song(self, automatic=False):
        if not self.songs:
            return

        if self.shuffle:
            if len(self.songs) > 1 and self.current is not None:
                choices = [i for i in range(len(self.songs)) if i != self.current]
                index = random.choice(choices)
            else:
                index = random.randrange(len(self.songs))
        elif self.current is None:
            index = 0
        else:
            index = (self.current + 1) % len(self.songs)

        self.play(index, automatic=automatic)
        if not automatic:
            self.set_status("Skipped to next track.", "Skipped to the next meow.")

    def previous_song(self):
        if not self.songs:
            return

        if self.current is None:
            index = 0
        else:
            index = (self.current - 1) % len(self.songs)

        self.play(index)
        self.set_status("Returned to previous track.", "Back to the previous purr.")

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
        lines = list(mascot) + ["", "Welcome to MeowPlayer", "Scanning your music nest..."]

        start_y = max(0, (height - len(lines)) // 2)
        for offset, line in enumerate(lines):
            x = max(0, (width - len(line)) // 2)
            try:
                stdscr.addstr(start_y + offset, x, line[:max(0, width - x - 1)])
            except curses.error:
                pass

        stdscr.refresh()
        time.sleep(1.2 if self.maximum_meow else 0.8)

    def draw_header(self, stdscr, width):
        if self.serious_mode:
            try:
                stdscr.addstr(0, 0, " ♫ MEOWPLAYER ", curses.A_BOLD | curses.color_pair(1))
            except curses.error:
                pass
            return 2

        mascot = MAXIMUM_MEOW_MASCOT if self.maximum_meow else CAT_MASCOT
        title = "♫ MEOWPLAYER — terminal purr engine"
        for row, cat_line in enumerate(mascot):
            try:
                if row == 0:
                    header = f"{cat_line}   {title}"
                    stdscr.addstr(row, 0, header[:width - 1], curses.A_BOLD | curses.color_pair(1))
                else:
                    stdscr.addstr(row, 0, cat_line[:width - 1], curses.color_pair(1))
            except curses.error:
                pass
        return len(mascot) + 1

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
        scroll = 0

        while True:
            height, width = stdscr.getmaxyx()
            stdscr.erase()

            if height < 13 or width < 38:
                message = "Terminal too small — give this cat a little more room."
                if self.serious_mode:
                    message = "Terminal too small. Resize to at least 38x13."
                try:
                    stdscr.addstr(0, 0, message[:max(1, width - 1)])
                except curses.error:
                    pass
                stdscr.refresh()
                key = stdscr.getch()
                if key in (ord("q"), ord("Q")):
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
                now_playing = self.text("No song playing", "No song meowing right now")

            progress_y = content_start + 2
            info_y = content_start + 4
            status_y = content_start + 5
            list_start = content_start + 7

            try:
                stdscr.addstr(
                    content_start,
                    2,
                    now_playing[:width - 4],
                    curses.A_BOLD | curses.color_pair(2)
                )
                stdscr.addstr(progress_y, 2, self.progress_bar(width - 4)[:width - 4])
            except curses.error:
                pass

            if self.serious_mode:
                info = (
                    f"Volume: {self.volume}%   "
                    f"Shuffle: {'ON' if self.shuffle else 'OFF'}   "
                    f"Repeat: {'ON' if self.repeat else 'OFF'}"
                )
            else:
                info = (
                    f"Meow Level: {self.volume}%   "
                    f"Pounce Mode: {'ON' if self.shuffle else 'OFF'}   "
                    f"Tail-Chase: {'ON' if self.repeat else 'OFF'}"
                )

            try:
                stdscr.addstr(info_y, 2, info[:width - 4], curses.color_pair(3))
                stdscr.addstr(
                    status_y,
                    2,
                    self.status_message[:width - 4],
                    curses.color_pair(4) if not self.serious_mode else curses.A_DIM
                )
            except curses.error:
                pass

            footer_lines = 2 if self.serious_mode else 3
            list_height = max(1, height - list_start - footer_lines - 1)

            if self.selected < scroll:
                scroll = self.selected
            if self.selected >= scroll + list_height:
                scroll = self.selected - list_height + 1

            for screen_row, song_index in enumerate(
                range(scroll, min(len(self.songs), scroll + list_height))
            ):
                song = self.songs[song_index]
                if song_index == self.current:
                    prefix = "▶  " if self.serious_mode else "🐾 "
                elif song_index == self.selected and not self.serious_mode:
                    prefix = ">^.^< "
                else:
                    prefix = "   "

                text = prefix + song.name
                y = list_start + screen_row
                attr = curses.A_NORMAL

                if song_index == self.selected:
                    attr |= curses.A_REVERSE
                if song_index == self.current:
                    attr |= curses.color_pair(2)

                try:
                    stdscr.addstr(y, 2, text[:width - 4], attr)
                except curses.error:
                    pass

            if not self.serious_mode and time.monotonic() - self.last_quote_change > 20:
                self.quote = random.choice(CAT_QUOTES)
                self.last_quote_change = time.monotonic()

            if self.serious_mode:
                controls = (
                    "↑↓ Select  ENTER Play  SPACE Pause  ←→ Seek  "
                    "N Next  P Prev  +/- Volume  S Shuffle  R Repeat  Q Quit"
                )
                quote = ""
            else:
                controls = (
                    "↑↓ Choose  ENTER Play  SPACE Paws  ←→ Scritch seek  "
                    "N Next meow  P Previous purr  +/- Meow level  S Pounce  R Tail-chase  Q Escape"
                )
                quote = f"🐱 {self.quote}"
                if self.maximum_meow:
                    quote = f"🐱 MAXIMUM MEOW: {self.quote} 🐾♫🐾"

            try:
                if quote:
                    stdscr.addstr(height - 3, 1, quote[:width - 2], curses.A_DIM)
                stdscr.addstr(height - 2, 1, controls[:width - 2], curses.A_DIM)
            except curses.error:
                pass

            stdscr.refresh()

            if self.current is not None:
                eof = self.mpv.get_property("eof-reached")
                if eof:
                    if self.repeat:
                        self.play(self.current, automatic=True)
                        self.set_status("Repeating current track.", "Tail-chase engaged: one more purr!")
                    else:
                        self.next_song(automatic=True)

            key = stdscr.getch()
            if key == -1:
                continue

            if key in (ord("q"), ord("Q")):
                self.set_status("Quitting.", "Escaping before the cat notices...")
                break
            elif key == curses.KEY_UP and self.songs:
                self.selected = max(0, self.selected - 1)
            elif key == curses.KEY_DOWN and self.songs:
                self.selected = min(len(self.songs) - 1, self.selected + 1)
            elif key in (10, 13, curses.KEY_ENTER):
                self.play(self.selected)
            elif key == ord(" "):
                paused = self.mpv.toggle_pause()
                if paused:
                    self.set_status("Paused.", "Pawsed. The cat is loafing.")
                else:
                    self.set_status("Resumed.", "Purr resumed. The loaf has awakened.")
            elif key == curses.KEY_RIGHT:
                self.mpv.seek(5)
                self.set_status("Seeked forward 5 seconds.", "Scritched 5 seconds into the future.")
            elif key == curses.KEY_LEFT:
                self.mpv.seek(-5)
                self.set_status("Seeked backward 5 seconds.", "Backtracked 5 seconds on tiny paws.")
            elif key in (ord("n"), ord("N")):
                self.next_song()
            elif key in (ord("p"), ord("P")):
                self.previous_song()
            elif key in (ord("+"), ord("=")):
                self.update_volume(5)
            elif key == ord("-"):
                self.update_volume(-5)
            elif key in (ord("s"), ord("S")):
                self.shuffle = not self.shuffle
                self.set_status(
                    f"Shuffle {'enabled' if self.shuffle else 'disabled'}.",
                    f"Pounce Mode {'ENGAGED' if self.shuffle else 'disengaged'}."
                )
            elif key in (ord("r"), ord("R")):
                self.repeat = not self.repeat
                self.set_status(
                    f"Repeat {'enabled' if self.repeat else 'disabled'}.",
                    f"Tail-Chase {'ENGAGED' if self.repeat else 'disengaged'}."
                )

        self.mpv.quit()


def parse_args():
    parser = argparse.ArgumentParser(
        description="MeowPlayer — a cat-themed terminal music player powered by mpv."
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
            message += "\n\nThe cat searched the entire nest. No tunes. :<"
        print(message)
        player.mpv.quit()
        sys.exit(0)

    try:
        curses.wrapper(player.run)
    finally:
        player.mpv.quit()


if __name__ == "__main__":
    main()
