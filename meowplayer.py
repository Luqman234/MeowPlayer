#!/usr/bin/env python3

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

        # Give MPV time to create the IPC socket
        for _ in range(50):
            if os.path.exists(self.socket_path):
                break
            time.sleep(0.02)

    def command(self, *args):
        if not os.path.exists(self.socket_path):
            return None

        request = {
            "command": list(args)
        }

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.2)
            sock.connect(self.socket_path)

            sock.sendall(
                (json.dumps(request) + "\n").encode("utf-8")
            )

            data = b""

            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)

                if not chunk:
                    break

                data += chunk

            sock.close()

            if data:
                return json.loads(data.decode("utf-8"))

        except (
            OSError,
            json.JSONDecodeError,
            socket.timeout
        ):
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
    def __init__(self, music_dir):
        self.music_dir = Path(music_dir).expanduser().resolve()

        self.songs = self.find_songs()

        self.selected = 0
        self.current = None

        self.volume = 70

        self.shuffle = False
        self.repeat = False

        self.mpv = MPVController()

        self.mpv.set_property("volume", self.volume)

    def find_songs(self):
        songs = []

        for path in self.music_dir.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in SUPPORTED_EXTENSIONS
            ):
                songs.append(path)

        return sorted(
            songs,
            key=lambda p: p.name.lower()
        )

    def play(self, index):
        if not self.songs:
            return

        index %= len(self.songs)

        self.current = index
        self.selected = index

        self.mpv.load(self.songs[index])

    def next_song(self):
        if not self.songs:
            return

        if self.shuffle:
            index = random.randrange(len(self.songs))
        elif self.current is None:
            index = 0
        else:
            index = (self.current + 1) % len(self.songs)

        self.play(index)

    def previous_song(self):
        if not self.songs:
            return

        if self.current is None:
            index = 0
        else:
            index = (self.current - 1) % len(self.songs)

        self.play(index)

    def update_volume(self, amount):
        self.volume = max(
            0,
            min(100, self.volume + amount)
        )

        self.mpv.set_property(
            "volume",
            self.volume
        )

    def format_time(self, seconds):
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

        if duration > 0:
            progress = min(
                1,
                position / duration
            )
        else:
            progress = 0

        filled = int(
            bar_width * progress
        )

        bar = (
            "━" * filled
            + "●"
            + "─" * max(
                0,
                bar_width - filled - 1
            )
        )

        return (
            f"{self.format_time(position)} "
            f"{bar} "
            f"{self.format_time(duration)}"
        )

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

            curses.init_pair(
                1,
                curses.COLOR_CYAN,
                -1
            )

            curses.init_pair(
                2,
                curses.COLOR_GREEN,
                -1
            )

            curses.init_pair(
                3,
                curses.COLOR_YELLOW,
                -1
            )

        scroll = 0

        while True:
            height, width = stdscr.getmaxyx()

            stdscr.erase()

            #
            # Header
            #

            title = " ♫ MEOWPLAYER "

            try:
                stdscr.addstr(
                    0,
                    0,
                    title,
                    curses.A_BOLD
                    | curses.color_pair(1)
                )
            except curses.error:
                pass

            #
            # Currently playing
            #

            if self.current is not None:

                song = self.songs[self.current]

                status = self.mpv.get_property("pause")

                icon = "⏸" if status else "▶"

                now_playing = (
                    f"{icon}  {song.name}"
                )

            else:

                now_playing = (
                    "No song playing"
                )

            try:
                stdscr.addstr(
                    2,
                    2,
                    now_playing[: width - 4],
                    curses.A_BOLD
                    | curses.color_pair(2)
                )

                stdscr.addstr(
                    4,
                    2,
                    self.progress_bar(width - 4)[
                        : width - 4
                    ]
                )

            except curses.error:
                pass

            #
            # Information
            #

            info = (
                f"Volume: {self.volume}%"
                f"   Shuffle: "
                f"{'ON' if self.shuffle else 'OFF'}"
                f"   Repeat: "
                f"{'ON' if self.repeat else 'OFF'}"
            )

            try:
                stdscr.addstr(
                    6,
                    2,
                    info[: width - 4],
                    curses.color_pair(3)
                )
            except curses.error:
                pass

            #
            # Song list
            #

            list_start = 8
            list_height = height - 11

            if self.selected < scroll:
                scroll = self.selected

            if self.selected >= scroll + list_height:
                scroll = (
                    self.selected
                    - list_height
                    + 1
                )

            for screen_row, song_index in enumerate(
                range(
                    scroll,
                    min(
                        len(self.songs),
                        scroll + list_height
                    )
                )
            ):

                song = self.songs[song_index]

                prefix = "   "

                if song_index == self.current:
                    prefix = "♫  "

                text = prefix + song.name

                y = list_start + screen_row

                attr = curses.A_NORMAL

                if song_index == self.selected:
                    attr |= curses.A_REVERSE

                if song_index == self.current:
                    attr |= curses.color_pair(2)

                try:
                    stdscr.addstr(
                        y,
                        2,
                        text[: width - 4],
                        attr
                    )
                except curses.error:
                    pass

            #
            # Footer
            #

            controls = (
                "↑↓ Select   ENTER Play   SPACE Pause   "
                "←→ Seek   N Next   P Prev   "
                "+/- Volume   S Shuffle   R Repeat   Q Quit"
            )

            try:
                stdscr.addstr(
                    height - 2,
                    1,
                    controls[: width - 2],
                    curses.A_DIM
                )
            except curses.error:
                pass

            stdscr.refresh()

            #
            # Detect automatic song ending
            #

            if self.current is not None:

                eof = self.mpv.get_property(
                    "eof-reached"
                )

                if eof:
                    if self.repeat:
                        self.play(self.current)
                    else:
                        self.next_song()

            #
            # Keyboard controls
            #

            key = stdscr.getch()

            if key == -1:
                continue

            if key in (
                ord("q"),
                ord("Q")
            ):
                break

            elif key == curses.KEY_UP:

                if self.songs:
                    self.selected = max(
                        0,
                        self.selected - 1
                    )

            elif key == curses.KEY_DOWN:

                if self.songs:
                    self.selected = min(
                        len(self.songs) - 1,
                        self.selected + 1
                    )

            elif key in (
                10,
                13,
                curses.KEY_ENTER
            ):
                self.play(self.selected)

            elif key == ord(" "):
                self.mpv.toggle_pause()

            elif key == curses.KEY_RIGHT:
                self.mpv.seek(5)

            elif key == curses.KEY_LEFT:
                self.mpv.seek(-5)

            elif key in (
                ord("n"),
                ord("N")
            ):
                self.next_song()

            elif key in (
                ord("p"),
                ord("P")
            ):
                self.previous_song()

            elif key in (
                ord("+"),
                ord("=")
            ):
                self.update_volume(5)

            elif key == ord("-"):
                self.update_volume(-5)

            elif key in (
                ord("s"),
                ord("S")
            ):
                self.shuffle = not self.shuffle

            elif key in (
                ord("r"),
                ord("R")
            ):
                self.repeat = not self.repeat

        self.mpv.quit()


def main():
    if len(sys.argv) >= 2:
        music_dir = sys.argv[1]
    else:
        music_dir = "~/Music"

    music_dir = Path(
        music_dir
    ).expanduser()

    if not music_dir.exists():
        print(
            f"Music directory doesn't exist: "
            f"{music_dir}"
        )

        sys.exit(1)

    try:
        player = MeowPlayer(music_dir)

    except FileNotFoundError:
        print(
            "MPV was not found.\n"
            "Install it with:\n\n"
            "    sudo pacman -S mpv"
        )

        sys.exit(1)

    if not player.songs:
        print(
            f"No supported music files found in:\n"
            f"{music_dir}"
        )

        sys.exit(0)

    try:
        curses.wrapper(
            player.run
        )

    finally:
        player.mpv.quit()


if __name__ == "__main__":
    main()
