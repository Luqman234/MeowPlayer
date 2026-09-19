import bisect
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None


_TIMESTAMP_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_METADATA_RE = re.compile(r"^\[(ar|ti|al|by|re|ve|length):", re.IGNORECASE)
_OFFSET_RE = re.compile(r"^\[offset:([+-]?\d+)\]$", re.IGNORECASE)


@dataclass(frozen=True)
class LyricLine:
    time: float | None
    text: str


@dataclass(frozen=True)
class LyricsDocument:
    lines: tuple
    synced: bool
    source: str

    def current_index(self, position):
        if not self.lines:
            return None

        if not self.synced:
            return 0

        times = [
            line.time if line.time is not None else float("inf")
            for line in self.lines
        ]
        index = bisect.bisect_right(times, max(0.0, float(position))) - 1
        if index < 0:
            return None
        return min(index, len(self.lines) - 1)

    def current_line(self, position):
        index = self.current_index(position)
        if index is None:
            return ""
        return self.lines[index].text


def _decode_text(path):
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (OSError, UnicodeError):
            continue
    return None


def parse_lrc(text, source="LRC"):
    if not text:
        return None

    offset_seconds = 0.0
    timed = []
    plain = []

    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue

        offset_match = _OFFSET_RE.match(line)
        if offset_match:
            try:
                offset_seconds = int(offset_match.group(1)) / 1000.0
            except ValueError:
                offset_seconds = 0.0
            continue

        if _METADATA_RE.match(line):
            continue

        timestamps = list(_TIMESTAMP_RE.finditer(line))
        lyric = _TIMESTAMP_RE.sub("", line).strip()

        if timestamps:
            if not lyric:
                lyric = "♪"
            for match in timestamps:
                try:
                    minute = int(match.group(1))
                    second = float(match.group(2))
                except ValueError:
                    continue
                timed.append(
                    LyricLine(
                        max(0.0, minute * 60.0 + second + offset_seconds),
                        lyric,
                    )
                )
        elif lyric and not line.startswith("["):
            plain.append(LyricLine(None, lyric))

    if timed:
        timed.sort(key=lambda item: item.time)
        return LyricsDocument(tuple(timed), True, source)

    if plain:
        return LyricsDocument(tuple(plain), False, source)

    return None


def parse_plain_lyrics(text, source="Embedded lyrics"):
    if not text:
        return None

    lines = tuple(
        LyricLine(None, line.strip())
        for line in str(text).splitlines()
        if line.strip()
    )
    if not lines:
        return None
    return LyricsDocument(lines, False, source)


def _string_value(value):
    if value is None:
        return ""

    if isinstance(value, (list, tuple)):
        parts = [_string_value(item) for item in value]
        return "\n".join(part for part in parts if part)

    text = getattr(value, "text", None)
    if text is not None and text is not value:
        return _string_value(text)

    try:
        return str(value).strip()
    except Exception:
        return ""


def _embedded_synced(tags):
    getall = getattr(tags, "getall", None)
    if callable(getall):
        try:
            frames = getall("SYLT")
        except Exception:
            frames = []

        timed = []
        for frame in frames:
            values = getattr(frame, "text", None) or []
            for value in values:
                if not isinstance(value, (list, tuple)) or len(value) < 2:
                    continue

                text, timestamp = value[0], value[1]
                try:
                    seconds = float(timestamp) / 1000.0
                except (TypeError, ValueError):
                    continue

                lyric = str(text).strip()
                if lyric:
                    timed.append(LyricLine(max(0.0, seconds), lyric))

        if timed:
            timed.sort(key=lambda item: item.time)
            return LyricsDocument(
                tuple(timed),
                True,
                "Embedded synchronized lyrics",
            )

    if hasattr(tags, "items"):
        for key, value in tags.items():
            normalized = str(key).casefold().replace("_", "")
            if normalized in {
                "syncedlyrics",
                "synchronizedlyrics",
                "lyrics-synced",
            }:
                document = parse_lrc(
                    _string_value(value),
                    source="Embedded synchronized lyrics",
                )
                if document is not None:
                    return document

    return None


def _embedded_plain(tags):
    getall = getattr(tags, "getall", None)
    if callable(getall):
        try:
            frames = getall("USLT")
        except Exception:
            frames = []

        for frame in frames:
            document = parse_plain_lyrics(
                getattr(frame, "text", ""),
                source="Embedded lyrics",
            )
            if document is not None:
                return document

    if not hasattr(tags, "items"):
        return None

    preferred = (
        "©lyr",
        "lyrics",
        "unsyncedlyrics",
        "unsynchronizedlyrics",
        "lyric",
    )

    items = list(tags.items())
    for wanted in preferred:
        for key, value in items:
            normalized = str(key).casefold().replace("_", "")
            if normalized == wanted.casefold().replace("_", ""):
                document = parse_plain_lyrics(
                    _string_value(value),
                    source="Embedded lyrics",
                )
                if document is not None:
                    return document

    return None


class LyricsManager:
    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self._cache = {}

    def _cache_identity(self, path):
        path = Path(path).expanduser()

        def mtime(candidate):
            try:
                return int(candidate.stat().st_mtime_ns)
            except OSError:
                return 0

        return (
            str(path.resolve()),
            mtime(path),
            mtime(path.with_suffix(".lrc")),
            mtime(path.with_suffix(".txt")),
        )

    def load(self, track_path):
        if not self.enabled:
            return None

        track_path = Path(track_path).expanduser()
        identity = self._cache_identity(track_path)
        if identity in self._cache:
            return self._cache[identity]

        lrc_path = track_path.with_suffix(".lrc")
        if lrc_path.is_file():
            text = _decode_text(lrc_path)
            document = parse_lrc(
                text,
                source=f"Sidecar · {lrc_path.name}",
            )
            if document is not None:
                self._cache[identity] = document
                return document

        embedded_synced = None
        embedded_plain = None

        if MutagenFile is not None:
            try:
                audio = MutagenFile(track_path)
                tags = getattr(audio, "tags", None) if audio is not None else None
            except Exception:
                tags = None

            if tags is not None:
                embedded_synced = _embedded_synced(tags)
                if embedded_synced is not None:
                    self._cache[identity] = embedded_synced
                    return embedded_synced
                embedded_plain = _embedded_plain(tags)

        text_path = track_path.with_suffix(".txt")
        if text_path.is_file():
            document = parse_plain_lyrics(
                _decode_text(text_path),
                source=f"Sidecar · {text_path.name}",
            )
            if document is not None:
                self._cache[identity] = document
                return document

        self._cache[identity] = embedded_plain
        return embedded_plain
