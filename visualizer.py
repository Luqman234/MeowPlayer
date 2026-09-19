import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


_LEVELS = "▁▂▃▄▅▆▇█"


class AudioVisualizer:
    """Optional CAVA-backed spectrum reader for the MeowPlayer TUI."""

    def __init__(self, enabled=True, bars=48):
        self.enabled = bool(enabled)
        self.bars = max(8, min(128, int(bars)))
        self.available = bool(self.enabled and shutil.which("cava"))
        self.visible = bool(self.available)
        self.process = None
        self.config_path = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest = []

        if self.visible:
            self.start()

    def _config(self):
        return f"""[general]
bars = {self.bars}
framerate = 30
autosens = 1
sensitivity = 100
sleep_timer = 0

[input]
source = auto

[output]
method = raw
channels = mono
mono_option = average
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 1000
bar_delimiter = 59
frame_delimiter = 10
"""

    def start(self):
        if not self.enabled or not self.available:
            return False
        if self.process is not None and self.process.poll() is None:
            return True

        self._stop.clear()

        config = tempfile.NamedTemporaryFile(
            prefix="meowplayer-cava-",
            suffix=".conf",
            mode="w",
            encoding="utf-8",
            delete=False,
        )
        config.write(self._config())
        config.flush()
        config.close()
        self.config_path = Path(config.name)

        try:
            self.process = subprocess.Popen(
                ["cava", "-p", str(self.config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except (OSError, FileNotFoundError):
            self.process = None
            self.available = False
            self.visible = False
            self._cleanup_config()
            return False

        self._thread = threading.Thread(
            target=self._reader,
            name="meowplayer-cava",
            daemon=True,
        )
        self._thread.start()
        return True

    def _reader(self):
        process = self.process
        if process is None or process.stdout is None:
            return

        while not self._stop.is_set():
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue

            values = []
            for token in line.strip().split(";"):
                if not token:
                    continue
                try:
                    values.append(max(0, min(1000, int(token))))
                except ValueError:
                    continue

            if values:
                with self._lock:
                    self._latest = values

    def _cleanup_config(self):
        if self.config_path is None:
            return
        try:
            self.config_path.unlink()
        except OSError:
            pass
        self.config_path = None

    def stop(self):
        self._stop.set()
        process = self.process
        self.process = None

        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=0.3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        self._cleanup_config()

    def toggle(self):
        if not self.available:
            self.visible = False
            return False

        self.visible = not self.visible
        if self.visible:
            self.start()
        else:
            self.stop()
        return self.visible

    def values(self):
        with self._lock:
            return list(self._latest)

    def render(self, width):
        if not self.visible:
            return ""

        values = self.values()
        if not values:
            return ""

        width = max(1, int(width))
        if len(values) > width:
            reduced = []
            for position in range(width):
                start = int(position * len(values) / width)
                end = max(
                    start + 1,
                    int((position + 1) * len(values) / width),
                )
                chunk = values[start:end]
                reduced.append(sum(chunk) / len(chunk))
            values = reduced

        return "".join(
            _LEVELS[
                min(
                    len(_LEVELS) - 1,
                    int(round(value / 1000 * (len(_LEVELS) - 1))),
                )
            ]
            for value in values
        )
