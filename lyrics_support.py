import bisect
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
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
class LyricsFetchResult:
    text: str
    status: str
    query: str = ""
    synced: bool = True


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
        "filename_stem": track_path.stem.strip(),
        "audio": audio,
        "tags": tags,
    }


def _cache_key(metadata):
    identity = "\0".join(
        [
            "lrclib-confidence-v1",
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
                "MeowPlayer "
                "(https://github.com/Luqman234/MeowPlayer)"
            ),
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, "not-found"
        if exc.code == 429 or 500 <= exc.code < 600:
            return None, "network-error"
        return None, "http-error"
    except (OSError, urllib.error.URLError, TimeoutError):
        return None, "network-error"

    try:
        return json.loads(payload.decode("utf-8")), "ok"
    except (UnicodeError, json.JSONDecodeError, TypeError):
        return None, "invalid-response"


def _normalized_identity(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(char for char in normalized if char.isalnum())


def _identity_matches(expected, actual):
    expected_key = _normalized_identity(expected)
    actual_key = _normalized_identity(actual)
    if not expected_key or not actual_key:
        return False
    return expected_key == actual_key


_INTERNET_TITLE_NOISE = re.compile(
    r"\s*[\[(](?:official\s+)?(?:music\s+)?"
    r"(?:video|audio|lyric(?:s|\s+video)?|visuali[sz]er|mv|hd|4k)"
    r"[^\])]*[\])]",
    re.IGNORECASE,
)
_INTERNET_FEATURE_SUFFIX = re.compile(
    r"\s+(?:feat\.?|ft\.?|featuring)\s+.+$",
    re.IGNORECASE,
)
_INTERNET_ARTIST_SPLIT = re.compile(
    r"\s*(?:,|&|\bx\b|/|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*",
    re.IGNORECASE,
)


def _internet_title(value):
    text = " ".join(str(value or "").split())
    text = _INTERNET_TITLE_NOISE.sub("", text)
    text = _INTERNET_FEATURE_SUFFIX.sub("", text)
    return " ".join(text.split()).strip(" -–—|")


def _internet_artist(value):
    text = " ".join(str(value or "").split()).strip()
    text = re.sub(r"\s*-\s*Topic$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+Official$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"VEVO$", "", text, flags=re.IGNORECASE)
    return text.strip(" -–—|")


def _internet_artist_parts(value):
    cleaned = _internet_artist(value)
    return {
        _normalized_identity(part)
        for part in _INTERNET_ARTIST_SPLIT.split(cleaned)
        if _normalized_identity(part)
    }


_INTERNET_ALIAS_SPLIT = re.compile(r"\s*(?:/|\||｜)\s*")
_INTERNET_ARTIST_TITLE_SPLIT = re.compile(r"\s+(?:-|–|—)\s+")
_INTERNET_EXTRA_ARTIST_SPLIT = re.compile(
    r"\s*(?:\band\b|\bwith\b|\+|×|・)\s*",
    re.IGNORECASE,
)


def _dedupe_internet_values(values, limit=8):
    result = []
    seen = set()
    for value in values:
        text = " ".join(str(value or "").split()).strip(" -–—|/")
        key = _normalized_identity(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _internet_aliases(value):
    return _dedupe_internet_values(
        _INTERNET_ALIAS_SPLIT.split(str(value or "")),
        limit=6,
    )


def _internet_embedded_artist_title(value):
    parts = [
        part.strip()
        for part in _INTERNET_ARTIST_TITLE_SPLIT.split(
            str(value or ""),
            maxsplit=1,
        )
        if part.strip()
    ]
    if len(parts) != 2:
        return (), ()
    return (
        tuple(_internet_aliases(parts[0])),
        tuple(_internet_aliases(parts[1])),
    )


def _internet_title_variants(value):
    cleaned = _internet_title(value)
    if not cleaned:
        return ()

    values = [cleaned]
    _embedded_artists, embedded_titles = (
        _internet_embedded_artist_title(cleaned)
    )
    values.extend(embedded_titles)

    for candidate in tuple(values):
        values.extend(_internet_aliases(candidate))

    return _dedupe_internet_values(values, limit=8)


def _internet_artist_variants(value):
    cleaned = _internet_artist(value)
    if not cleaned:
        return ()

    values = [cleaned]
    values.extend(_internet_aliases(cleaned))

    for candidate in tuple(values):
        values.extend(_INTERNET_ARTIST_SPLIT.split(candidate))
        values.extend(_INTERNET_EXTRA_ARTIST_SPLIT.split(candidate))

    return _dedupe_internet_values(values, limit=8)


def _internet_search_candidates(title, artist):
    clean_title = _internet_title(title)
    clean_artist = _internet_artist(artist)

    title_variants = list(_internet_title_variants(clean_title))
    artist_variants = list(_internet_artist_variants(clean_artist))

    embedded_artists, embedded_titles = (
        _internet_embedded_artist_title(clean_title)
    )
    for value in embedded_artists:
        for variant in _internet_artist_variants(value):
            if variant not in artist_variants:
                artist_variants.append(variant)
    for value in embedded_titles:
        for variant in _internet_title_variants(value):
            if variant not in title_variants:
                title_variants.append(variant)

    candidates = []

    def add(query, expected_title, expected_artist=""):
        normalized = " ".join(str(query or "").split()).strip()
        if normalized:
            candidates.append(
                (normalized, expected_title, expected_artist)
            )

    if clean_title and clean_artist:
        add(
            f"{clean_artist} {clean_title}",
            clean_title,
            clean_artist,
        )

    preferred_artists = artist_variants[:2]
    for title_variant in title_variants[:6]:
        for artist_variant in preferred_artists:
            add(
                f"{artist_variant} {title_variant}",
                title_variant,
                artist_variant,
            )
        add(title_variant, title_variant, "")

    return tuple(candidates[:12])


def _internet_title_matches(expected, actual):
    expected_key = _normalized_identity(_internet_title(expected))
    actual_key = _normalized_identity(_internet_title(actual))
    if not expected_key or not actual_key:
        return False
    if expected_key == actual_key:
        return True

    shorter, longer = sorted(
        (expected_key, actual_key),
        key=len,
    )
    return (
        len(shorter) >= 8
        and len(shorter) / len(longer) >= 0.65
        and shorter in longer
    )


def _internet_artist_matches(expected, actual):
    if _identity_matches(
        _internet_artist(expected),
        _internet_artist(actual),
    ):
        return True

    expected_parts = _internet_artist_parts(expected)
    actual_parts = _internet_artist_parts(actual)
    return bool(expected_parts and actual_parts and expected_parts & actual_parts)


def _filename_artist_title(stem):
    parts = [
        part.strip()
        for part in re.split(r"\s+-\s+", str(stem or ""))
        if part.strip()
    ]
    if len(parts) >= 2:
        return parts[0], " - ".join(parts[1:])
    return "", str(stem or "").strip()


def _lrclib_candidate_acceptable(
    candidate,
    metadata,
    expected_title="",
    expected_artist="",
):
    if not isinstance(candidate, dict):
        return False

    synced_text = candidate.get("syncedLyrics")
    plain_text = candidate.get("plainLyrics")
    has_synced = isinstance(synced_text, str) and bool(synced_text.strip())
    has_plain = isinstance(plain_text, str) and bool(plain_text.strip())
    if not has_synced and not has_plain:
        return False

    remote_title = str(candidate.get("trackName") or "").strip()
    remote_artist = str(candidate.get("artistName") or "").strip()

    internet_nest = metadata.get("lookup_mode") == "internet-nest"
    title_matches = (
        _internet_title_matches
        if internet_nest
        else _identity_matches
    )
    artist_matches = (
        _internet_artist_matches
        if internet_nest
        else _identity_matches
    )

    if expected_title and remote_title and not title_matches(
        expected_title,
        remote_title,
    ):
        return False

    if expected_artist and remote_artist and not artist_matches(
        expected_artist,
        remote_artist,
    ):
        return False

    try:
        local_duration = max(
            0.0,
            float(metadata.get("duration") or 0.0),
        )
    except (TypeError, ValueError):
        local_duration = 0.0

    try:
        remote_duration = max(
            0.0,
            float(candidate.get("duration") or 0.0),
        )
    except (TypeError, ValueError):
        remote_duration = 0.0

    if local_duration > 0 and remote_duration > 0:
        tolerance = (
            max(45.0, local_duration * 0.20)
            if internet_nest
            else max(10.0, local_duration * 0.08)
        )
        if abs(local_duration - remote_duration) > tolerance:
            return False

    return True


def _lyrics_from_payload(
    payload,
    metadata=None,
    expected_title="",
    expected_artist="",
):
    metadata = metadata or {}

    if isinstance(payload, dict):
        candidates = [payload]
    elif isinstance(payload, list):
        candidates = [
            item for item in payload
            if isinstance(item, dict)
        ]
    else:
        candidates = []

    acceptable = [
        item
        for item in candidates
        if _lrclib_candidate_acceptable(
            item,
            metadata,
            expected_title=expected_title,
            expected_artist=expected_artist,
        )
    ]

    # Prefer a synchronized lyric from any plausible candidate. If LRCLIB
    # only has plain lyrics, return those instead so Songbook can still
    # display the words without pretending they are timed.
    for item in acceptable:
        text = item.get("syncedLyrics")
        if isinstance(text, str) and text.strip():
            return text.strip(), True

    for item in acceptable:
        text = item.get("plainLyrics")
        if isinstance(text, str) and text.strip():
            return text.strip(), False

    return "", False


def _fetch_lrclib_result(metadata, timeout=5.0):
    title = metadata.get("title", "").strip()
    artist = metadata.get("artist", "").strip()
    album = metadata.get("album", "").strip()
    duration = metadata.get("duration", 0.0)

    query = " ".join(part for part in (artist, title) if part).strip()
    if not title:
        return LyricsFetchResult("", "not-found", query)

    saw_network_error = False

    if artist:
        params = {
            "track_name": title,
            "artist_name": artist,
        }
        if album:
            params["album_name"] = album
        if duration > 0:
            params["duration"] = int(round(duration))

        payload, status = _lrclib_request("/api/get", params, timeout)
        saw_network_error = saw_network_error or status == "network-error"
        text, synced = _lyrics_from_payload(
            payload,
            metadata,
            expected_title=title,
            expected_artist=artist,
        )
        if text:
            return LyricsFetchResult(
                text,
                "found",
                query,
                synced=synced,
            )

    filename_stem = metadata.get("filename_stem", "").strip()
    file_artist, file_title = _filename_artist_title(filename_stem)

    if metadata.get("lookup_mode") == "internet-nest":
        search_candidates = (
            (query, title, artist),
            *_internet_search_candidates(title, artist),
            (filename_stem, file_title, file_artist),
            (title, title, ""),
        )
    else:
        search_candidates = (
            (query, title, artist),
            (filename_stem, file_title, file_artist),
            (title, title, ""),
        )

    search_queries = []
    seen_queries = set()
    for candidate, expected_title, expected_artist in search_candidates:
        normalized = " ".join(candidate.split())
        key = normalized.casefold()
        if normalized and key not in seen_queries:
            seen_queries.add(key)
            search_queries.append(
                (normalized, expected_title, expected_artist)
            )

    if not search_queries:
        return LyricsFetchResult("", "not-found", query)

    saw_successful_search = False
    for search_query, expected_title, expected_artist in search_queries:
        payload, status = _lrclib_request(
            "/api/search",
            {"q": search_query},
            timeout,
        )
        saw_network_error = saw_network_error or status == "network-error"
        saw_successful_search = saw_successful_search or status == "ok"
        text, synced = _lyrics_from_payload(
            payload,
            metadata,
            expected_title=expected_title,
            expected_artist=expected_artist,
        )
        if text:
            return LyricsFetchResult(
                text,
                "found",
                search_query,
                synced=synced,
            )

    if saw_network_error and not saw_successful_search:
        return LyricsFetchResult("", "network-error", query)

    return LyricsFetchResult("", "not-found", query)


def _fetch_lrclib(metadata, timeout=5.0):
    return _fetch_lrclib_result(metadata, timeout=timeout).text


class LyricsManager:
    def __init__(
        self,
        enabled=True,
        online_enabled=True,
        cache_dir=None,
        request_timeout=5.0,
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
            self.request_timeout = 5.0
        self._cache = {}
        self._pending = {}
        self._online_status = {}
        self._pending_lock = threading.Lock()

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

    def _persistent_plain_cache_path(self, metadata):
        return self.cache_dir / f"{_cache_key(metadata)}.txt"

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

    def _load_cached_plain(self, metadata):
        path = self._persistent_plain_cache_path(metadata)
        if not path.is_file():
            return None

        return parse_plain_lyrics(
            _decode_text(path),
            source="LRCLIB cache · unsynchronized",
        )

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

    def _save_cached_plain(self, metadata, text):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._persistent_plain_cache_path(metadata)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(text.rstrip() + "\n", encoding="utf-8")
            temporary.replace(path)
            return path
        except OSError:
            return None

    def _start_online_fetch(
        self,
        identity,
        metadata,
        *,
        persistent=True,
        cache_result=True,
        source="LRCLIB · downloaded",
    ):
        if not self.online_enabled:
            return False

        query = " ".join(
            part
            for part in (
                metadata.get("artist", "").strip(),
                metadata.get("title", "").strip(),
            )
            if part
        ).strip()

        with self._pending_lock:
            if identity in self._pending:
                return False
            state = {
                "done": False,
                "text": "",
                "status": "searching",
                "query": query,
                "attempts": 0,
                "synced": True,
                "metadata": metadata,
                "persistent": bool(persistent),
                "cache_result": bool(cache_result),
                "source": source,
            }
            self._pending[identity] = state
            self._online_status[identity] = {
                "status": "searching",
                "query": query,
                "attempts": 0,
            }

        def worker():
            result = None
            for attempt in range(1, 3):
                result = _fetch_lrclib_result(
                    metadata,
                    timeout=self.request_timeout,
                )
                state["attempts"] = attempt
                if result.status != "network-error":
                    break

            if result is None:
                result = LyricsFetchResult("", "network-error", query)

            with self._pending_lock:
                current = self._pending.get(identity)
                if current is state:
                    state["text"] = result.text
                    state["status"] = result.status
                    state["query"] = result.query or query
                    state["synced"] = bool(result.synced)
                    state["done"] = True
                    self._online_status[identity] = {
                        "status": result.status,
                        "query": result.query or query,
                        "attempts": state["attempts"],
                    }

        threading.Thread(
            target=worker,
            name="meowplayer-lyrics",
            daemon=True,
        ).start()
        return True

    def _online_status_for_identity(self, identity):
        with self._pending_lock:
            state = self._pending.get(identity)
            if state is not None and not state.get("done"):
                return {
                    "status": "searching",
                    "query": state.get("query", ""),
                    "attempts": state.get("attempts", 0),
                }
            return dict(
                self._online_status.get(
                    identity,
                    {"status": "idle", "query": "", "attempts": 0},
                )
            )

    def online_status(self, track_path):
        if not self.enabled:
            return {"status": "disabled", "query": "", "attempts": 0}
        if not self.online_enabled:
            return {"status": "offline", "query": "", "attempts": 0}

        identity = self._cache_identity(Path(track_path).expanduser())
        return self._online_status_for_identity(identity)

    def _transient_identity(self, key):
        return ("internet-nest", str(key))

    def _transient_metadata(
        self,
        *,
        title,
        artist="",
        duration=0.0,
        album="",
    ):
        try:
            duration = max(0.0, float(duration or 0.0))
        except (TypeError, ValueError):
            duration = 0.0

        return {
            "title": str(title or "").strip(),
            "artist": str(artist or "").strip(),
            "album": str(album or "").strip(),
            "duration": duration,
            "filename_stem": str(title or "").strip(),
            "audio": None,
            "tags": None,
            "lookup_mode": "internet-nest",
        }

    def load_transient(
        self,
        key,
        *,
        title,
        artist="",
        duration=0.0,
        album="",
    ):
        """Fetch lyrics for remote media without reading or writing disk cache."""
        if not self.enabled or not self.online_enabled:
            return None

        identity = self._transient_identity(key)
        metadata = self._transient_metadata(
            title=title,
            artist=artist,
            duration=duration,
            album=album,
        )
        self._start_online_fetch(
            identity,
            metadata,
            persistent=False,
            cache_result=False,
            source="LRCLIB · Internet Nest",
        )
        return None

    def transient_status(self, key):
        if not self.enabled:
            return {"status": "disabled", "query": "", "attempts": 0}
        if not self.online_enabled:
            return {"status": "offline", "query": "", "attempts": 0}
        return self._online_status_for_identity(
            self._transient_identity(key)
        )

    def retry_transient(
        self,
        key,
        *,
        title,
        artist="",
        duration=0.0,
        album="",
    ):
        if not self.enabled or not self.online_enabled:
            return False

        identity = self._transient_identity(key)
        metadata = self._transient_metadata(
            title=title,
            artist=artist,
            duration=duration,
            album=album,
        )

        with self._pending_lock:
            if identity in self._pending:
                return False
            self._online_status.pop(identity, None)

        return self._start_online_fetch(
            identity,
            metadata,
            persistent=False,
            cache_result=False,
            source="LRCLIB · Internet Nest",
        )

    def retry_online(self, track_path):
        if not self.enabled or not self.online_enabled:
            return False

        track_path = Path(track_path).expanduser()
        identity = self._cache_identity(track_path)
        metadata = _track_lookup_metadata(track_path)

        with self._pending_lock:
            if identity in self._pending:
                return False
            self._online_status.pop(identity, None)

        return self._start_online_fetch(identity, metadata)

    def _poll_identity(self, identity):
        with self._pending_lock:
            state = self._pending.get(identity)
            if state is None or not state.get("done"):
                return None
            self._pending.pop(identity, None)

        lyric_text = state.get("text", "")
        if not lyric_text:
            return None

        source = str(state.get("source") or "LRCLIB · downloaded")
        persistent = bool(state.get("persistent", True))
        cache_result = bool(state.get("cache_result", True))

        if state.get("synced", True):
            document = parse_lrc(
                lyric_text,
                source=source,
            )
            if document is None or not document.synced:
                return None
            if persistent:
                self._save_cached_lrc(state["metadata"], lyric_text)
        else:
            document = parse_plain_lyrics(
                lyric_text,
                source=f"{source} · unsynchronized",
            )
            if document is None:
                return None
            if persistent:
                self._save_cached_plain(state["metadata"], lyric_text)

            # Never replace user-provided or embedded plain lyrics with a
            # plain online copy. A synchronized LRCLIB result may still
            # upgrade those local lyrics on a later lookup.
            if cache_result:
                existing = self._cache.get(identity)
                if (
                    existing is not None
                    and not existing.synced
                    and not existing.source.startswith("LRCLIB")
                ):
                    with self._pending_lock:
                        self._online_status[identity] = {
                            "status": "found",
                            "query": state.get("query", ""),
                            "attempts": state.get("attempts", 1),
                        }
                    return None

        if cache_result:
            self._cache[identity] = document
        with self._pending_lock:
            self._online_status[identity] = {
                "status": "found",
                "query": state.get("query", ""),
                "attempts": state.get("attempts", 1),
            }
        return document

    def poll(self, track_path):
        if not self.enabled or not self.online_enabled:
            return None

        track_path = Path(track_path).expanduser()
        identity = self._cache_identity(track_path)
        return self._poll_identity(identity)

    def poll_transient(self, key):
        if not self.enabled or not self.online_enabled:
            return None
        return self._poll_identity(self._transient_identity(key))

    def load(self, track_path):
        if not self.enabled:
            return None

        track_path = Path(track_path).expanduser()
        identity = self._cache_identity(track_path)
        if identity in self._cache:
            cached = self._cache[identity]
            if cached is not None:
                return cached

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

        # 4. Ask LRCLIB in the background. A synchronized result may
        # upgrade plain local lyrics later; an unsynchronized result is only
        # used when there is no better local lyric document.
        self._start_online_fetch(identity, metadata)

        # 5. Plain sidecar / embedded lyrics remain useful while fetching.
        text_path = track_path.with_suffix(".txt")
        if text_path.is_file():
            document = parse_plain_lyrics(
                _decode_text(text_path),
                source=f"Sidecar · {text_path.name}",
            )
            if document is not None:
                self._cache[identity] = document
                return document

        if embedded_plain is not None:
            self._cache[identity] = embedded_plain
            return embedded_plain

        # 6. A previously downloaded plain LRCLIB lyric is instant/offline
        # while a fresh online lookup, when enabled, can still upgrade it.
        document = self._load_cached_plain(metadata)
        if document is not None:
            self._cache[identity] = document
            return document

        return None
