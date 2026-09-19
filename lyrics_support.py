import bisect
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
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


def _lyrics_cache_dir():
    root = os.environ.get("XDG_CACHE_HOME")
    if root:
        base = Path(root).expanduser()
        if not base.is_absolute():
            base = Path.home() / ".cache"
    else:
        base = Path.home() / ".cache"
    return base / "meowplayer" / "lyrics"


def _metadata_text(tags, *names):
    if not tags:
        return ""

    for name in names:
        try:
            value = tags.get(name)
        except (AttributeError, TypeError):
            value = None
        text = _string_value(value)
        if text:
            return text.splitlines()[0].strip()
    return ""


def _track_lookup_metadata(track_path):
    title = track_path.stem
    artist = ""
    album = ""
    duration = 0.0
    audio = None
    tags = None

    if MutagenFile is not None:
        try:
            audio = MutagenFile(track_path)
            tags = getattr(audio, "tags", None) if audio is not None else None
        except Exception:
            audio = None
            tags = None

    if tags is not None:
        title = _metadata_text(
            tags, "title", "TIT2", "\xa9nam", "TITLE"
        ) or title
        artist = _metadata_text(
            tags, "artist", "TPE1", "\xa9ART", "ARTIST"
        )
        album = _metadata_text(
            tags, "album", "TALB", "\xa9alb", "ALBUM"
        )

    try:
        duration = float(getattr(getattr(audio, "info", None), "length", 0.0) or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    return {
        "title": title.strip(),
        "artist": artist.strip(),
        "album": album.strip(),
        "duration": max(0.0, duration),
        "audio": audio,
        "tags": tags,
    }


def _cache_key(metadata):
    identity = "\0".join(
        [
            metadata.get("artist", "").casefold(),
            metadata.get("title", "").casefold(),
            metadata.get("album", "").casefold(),
            str(int(round(metadata.get("duration", 0.0)))),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _lrclib_request(path, params, timeout):
    query = urllib.parse.urlencode(
        {
            key: value
            for key, value in params.items()
            if value not in (None, "")
        }
    )
    url = f"https://lrclib.net{path}"
    if query:
        url += "?" + query

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "MeowPlayer/0.13 "
                "(https://github.com/Luqman234/MeowPlayer)"
            ),
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, TypeError):
        return None


def _synced_lyrics_from_payload(payload):
    if isinstance(payload, dict):
        text = payload.get("syncedLyrics")
        return text.strip() if isinstance(text, str) and text.strip() else ""

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            text = item.get("syncedLyrics")
            if isinstance(text, str) and text.strip():
                return text.strip()

    return ""


def _fetch_lrclib(metadata, timeout=3.0):
    title = metadata.get("title", "").strip()
    artist = metadata.get("artist", "").strip()
    album = metadata.get("album", "").strip()
    duration = metadata.get("duration", 0.0)

    if not title:
        return ""

    if artist:
        params = {
            "track_name": title,
            "artist_name": artist,
        }
        if album:
            params["album_name"] = album
        if duration > 0:
            params["duration"] = int(round(duration))

        payload = _lrclib_request("/api/get", params, timeout)
        synced = _synced_lyrics_from_payload(payload)
        if synced:
            return synced

    query = " ".join(part for part in (artist, title) if part).strip()
    if not query:
        return ""

    payload = _lrclib_request(
        "/api/search",
        {"q": query},
        timeout,
    )
    return _synced_lyrics_from_payload(payload)


class LyricsManager:
    def __init__(
        self,
        enabled=True,
        online_enabled=True,
        cache_dir=None,
        request_timeout=3.0,
    ):
        self.enabled = bool(enabled)
        self.online_enabled = bool(online_enabled)
        self.cache_dir = (
            Path(cache_dir).expanduser()
            if cache_dir is not None
            else _lyrics_cache_dir()
        )
        try:
            self.request_timeout = max(0.25, float(request_timeout))
        except (TypeError, ValueError):
            self.request_timeout = 3.0
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

    def _persistent_cache_path(self, metadata):
        return self.cache_dir / f"{_cache_key(metadata)}.lrc"

    def _load_cached_lrc(self, metadata):
        path = self._persistent_cache_path(metadata)
        if not path.is_file():
            return None

        document = parse_lrc(
            _decode_text(path),
            source="LRCLIB cache",
        )
        if document is not None and document.synced:
            return document
        return None

    def _save_cached_lrc(self, metadata, text):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._persistent_cache_path(metadata)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(text.rstrip() + "\n", encoding="utf-8")
            temporary.replace(path)
            return path
        except OSError:
            return None

    def load(self, track_path):
        if not self.enabled:
            return None

        track_path = Path(track_path).expanduser()
        identity = self._cache_identity(track_path)
        if identity in self._cache:
            return self._cache[identity]

        # 1. User-provided synchronized sidecar always wins.
        lrc_path = track_path.with_suffix(".lrc")
        if lrc_path.is_file():
            document = parse_lrc(
                _decode_text(lrc_path),
                source=f"Sidecar · {lrc_path.name}",
            )
            if document is not None:
                self._cache[identity] = document
                return document

        metadata = _track_lookup_metadata(track_path)
        tags = metadata.get("tags")

        # 2. A previously downloaded synchronized lyric is instant/offline.
        document = self._load_cached_lrc(metadata)
        if document is not None:
            self._cache[identity] = document
            return document

        # 3. Embedded synchronized lyrics are local and avoid a network request.
        embedded_plain = None
        if tags is not None:
            embedded_synced = _embedded_synced(tags)
            if embedded_synced is not None:
                self._cache[identity] = embedded_synced
                return embedded_synced
            embedded_plain = _embedded_plain(tags)

        # 4. Fetch synchronized lyrics automatically, then persist the LRC.
        if self.online_enabled:
            synced_text = _fetch_lrclib(
                metadata,
                timeout=self.request_timeout,
            )
            if synced_text:
                document = parse_lrc(
                    synced_text,
                    source="LRCLIB · downloaded",
                )
                if document is not None and document.synced:
                    self._save_cached_lrc(metadata, synced_text)
                    self._cache[identity] = document
                    return document

        # 5. Plain sidecar / embedded lyrics remain useful fallbacks.
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
