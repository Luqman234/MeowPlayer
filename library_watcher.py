import threading
import time
from pathlib import Path

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    FileSystemEventHandler = object
    Observer = None


class _MusicEventHandler(FileSystemEventHandler):
    def __init__(self, watcher):
        super().__init__()
        self.watcher = watcher

    def on_any_event(self, event):
        event_type = getattr(event, "event_type", "")
        if event_type in {"opened", "closed", "closed_no_write"}:
            return

        paths = []
        src = getattr(event, "src_path", None)
        dest = getattr(event, "dest_path", None)

        if src:
            paths.append(src)
        if dest:
            paths.append(dest)

        self.watcher.record_event(
            paths,
            event_type=event_type or "changed",
            is_directory=bool(getattr(event, "is_directory", False)),
        )


class LibraryWatcher:
    """Debounced watchdog observer that never mutates player state itself."""

    def __init__(
        self,
        root,
        extensions,
        enabled=True,
        debounce_seconds=0.75,
    ):
        self.root = Path(root).expanduser().resolve()
        self.extensions = {
            str(extension).casefold()
            for extension in extensions
        }
        self.enabled = bool(enabled)
        self.debounce_seconds = max(0.05, float(debounce_seconds))
        self.available = bool(self.enabled and Observer is not None)
        self.running = False
        self.error = None

        self._observer = None
        self._lock = threading.Lock()
        self._pending_paths = set()
        self._event_types = set()
        self._last_event = None

    def _is_relevant(self, path, is_directory=False):
        if is_directory:
            return True

        try:
            suffix = Path(path).suffix.casefold()
        except TypeError:
            return False

        return suffix in self.extensions

    def record_event(
        self,
        paths,
        event_type="changed",
        is_directory=False,
        now=None,
    ):
        relevant = []

        for raw_path in paths:
            if not raw_path:
                continue
            if not self._is_relevant(raw_path, is_directory=is_directory):
                continue
            try:
                relevant.append(str(Path(raw_path).expanduser().resolve()))
            except (OSError, RuntimeError):
                relevant.append(str(raw_path))

        if not relevant and not is_directory:
            return False

        timestamp = time.monotonic() if now is None else float(now)

        with self._lock:
            if relevant:
                self._pending_paths.update(relevant)
            elif is_directory:
                self._pending_paths.add(str(self.root))
            self._event_types.add(str(event_type or "changed"))
            self._last_event = timestamp

        return True

    def start(self):
        if not self.available:
            return False
        if self.running:
            return True

        try:
            observer = Observer()
            observer.schedule(
                _MusicEventHandler(self),
                str(self.root),
                recursive=True,
            )
            observer.start()
        except Exception as exc:
            self.error = str(exc)
            self.available = False
            self.running = False
            return False

        self._observer = observer
        self.running = True
        return True

    def poll(self, now=None):
        timestamp = time.monotonic() if now is None else float(now)

        with self._lock:
            if self._last_event is None:
                return None

            if timestamp - self._last_event < self.debounce_seconds:
                return None

            result = {
                "paths": tuple(sorted(self._pending_paths)),
                "event_types": tuple(sorted(self._event_types)),
            }

            self._pending_paths.clear()
            self._event_types.clear()
            self._last_event = None

        return result

    def stop(self):
        observer = self._observer
        self._observer = None
        self.running = False

        if observer is None:
            return

        try:
            observer.stop()
            observer.join(timeout=1.0)
        except Exception:
            pass
