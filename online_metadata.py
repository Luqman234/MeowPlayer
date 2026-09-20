import json
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


MUSICBRAINZ_API_ROOT = "https://musicbrainz.org/ws/2"
DEFAULT_USER_AGENT = (
    "MeowPlayer/0.15 "
    "(https://github.com/Luqman234/MeowPlayer)"
)


@dataclass(frozen=True)
class OnlineMetadataResult:
    path: str
    status: str
    query: str
    source_id: str = ""
    score: int = 0
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    genre: str = ""


def missing_metadata_fields(metadata):
    path = Path(metadata.path)
    missing = []

    title = str(getattr(metadata, "title", "") or "").strip()
    artist = str(getattr(metadata, "artist", "") or "").strip()
    album = str(getattr(metadata, "album", "") or "").strip()
    album_artist = str(
        getattr(metadata, "album_artist", "") or ""
    ).strip()
    year = str(getattr(metadata, "year", "") or "").strip()
    genre = str(getattr(metadata, "genre", "") or "").strip()

    if not title or title == path.stem:
        missing.append("title")
    if not artist or artist == "Unknown Artist":
        missing.append("artist")
    if not album or album == "Unknown Album":
        missing.append("album")
    if not album_artist or album_artist == "Unknown Artist":
        missing.append("album_artist")
    if not year:
        missing.append("year")
    if not genre:
        missing.append("genre")

    return tuple(missing)


def needs_online_metadata(metadata):
    return bool(missing_metadata_fields(metadata))


def metadata_lookup_due(state, now_ns=None):
    status = str((state or {}).get("status") or "")
    fetched_at = int((state or {}).get("fetched_at_ns") or 0)
    now_ns = int(now_ns or time.time_ns())

    if not status or fetched_at <= 0:
        return True

    age = max(0, now_ns - fetched_at)
    if status == "found":
        ttl = 30 * 24 * 60 * 60 * 1_000_000_000
    elif status == "not-found":
        ttl = 7 * 24 * 60 * 60 * 1_000_000_000
    else:
        ttl = 15 * 60 * 1_000_000_000

    return age >= ttl


def merge_missing_metadata(metadata, result):
    values = {
        "title": metadata.title,
        "artist": metadata.artist,
        "album": metadata.album,
        "album_artist": metadata.album_artist,
        "year": metadata.year,
        "genre": metadata.genre,
    }
    missing = set(missing_metadata_fields(metadata))

    for field in tuple(values):
        if field not in missing:
            continue
        remote = str(getattr(result, field, "") or "").strip()
        if remote:
            values[field] = remote

    return values


def _strip_track_prefix(stem):
    return re.sub(
        r"^\s*(?:\d{1,3}|[A-D]?\d{1,2})\s*[._)-]+\s*",
        "",
        str(stem),
        count=1,
    ).strip()


def filename_artist_title(path):
    stem = _strip_track_prefix(Path(path).stem)
    parts = [
        part.strip()
        for part in re.split(r"\s+-\s+", stem)
        if part.strip()
    ]

    if len(parts) >= 2:
        return parts[0], " - ".join(parts[1:])
    return "", stem


def _lucene_quote(value):
    text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _artist_credit_text(credits):
    if not isinstance(credits, list):
        return ""

    parts = []
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        name = (
            credit.get("name")
            or (credit.get("artist") or {}).get("name")
            or ""
        )
        if name:
            parts.append(str(name))
        joinphrase = credit.get("joinphrase")
        if joinphrase:
            parts.append(str(joinphrase))
    return "".join(parts).strip()


def _release_title(recording):
    releases = recording.get("releases")
    if not isinstance(releases, list):
        return ""

    def key(item):
        if not isinstance(item, dict):
            return (2, "9999-99-99")
        official = 0 if item.get("status") == "Official" else 1
        date = str(item.get("date") or "9999-99-99")
        return (official, date)

    for release in sorted(releases, key=key):
        title = str(release.get("title") or "").strip()
        if title:
            return title
    return ""


def _top_genre(payload):
    genres = payload.get("genres") if isinstance(payload, dict) else None
    if not isinstance(genres, list):
        return ""

    ranked = sorted(
        (
            item
            for item in genres
            if isinstance(item, dict) and item.get("name")
        ),
        key=lambda item: (
            -int(item.get("count") or 0),
            str(item.get("name")).casefold(),
        ),
    )
    return str(ranked[0]["name"]).strip() if ranked else ""


class MusicBrainzClient:
    def __init__(
        self,
        timeout=6.0,
        minimum_interval=1.05,
        user_agent=DEFAULT_USER_AGENT,
        sleep=time.sleep,
        monotonic=time.monotonic,
    ):
        self.timeout = max(1.0, float(timeout))
        self.minimum_interval = max(1.0, float(minimum_interval))
        self.user_agent = str(user_agent)
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at = None

    def _wait_for_slot(self):
        if self._last_request_at is None:
            return

        elapsed = self._monotonic() - self._last_request_at
        remaining = self.minimum_interval - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _request_json(self, path, params=None):
        self._wait_for_slot()
        query = urllib.parse.urlencode(params or {})
        url = f"{MUSICBRAINZ_API_ROOT}{path}"
        if query:
            url += "?" + query

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                payload = response.read()
            status = "ok"
        except urllib.error.HTTPError as exc:
            if exc.code in {429, 503} or 500 <= exc.code < 600:
                status = "network-error"
            else:
                status = "not-found"
            payload = b""
        except (OSError, urllib.error.URLError, TimeoutError):
            status = "network-error"
            payload = b""
        finally:
            self._last_request_at = self._monotonic()

        if status != "ok":
            return None, status

        try:
            return json.loads(payload.decode("utf-8")), "ok"
        except (UnicodeError, json.JSONDecodeError, TypeError):
            return None, "invalid-response"

    def _queries_for(self, snapshot):
        path = Path(snapshot["path"])
        title = str(snapshot.get("title") or "").strip()
        artist = str(snapshot.get("artist") or "").strip()
        album = str(snapshot.get("album") or "").strip()

        if title == path.stem:
            title = ""

        if artist == "Unknown Artist":
            artist = ""
        if album == "Unknown Album":
            album = ""

        file_artist, file_title = filename_artist_title(path)
        candidates = []

        if title and artist:
            query = (
                f"recording:{_lucene_quote(title)} AND "
                f"artist:{_lucene_quote(artist)}"
            )
            candidates.append((query, title, artist))
        elif title:
            candidates.append(
                (f"recording:{_lucene_quote(title)}", title, "")
            )

        if file_title and (
            file_title.casefold() != title.casefold()
            or file_artist.casefold() != artist.casefold()
        ):
            if file_artist:
                query = (
                    f"recording:{_lucene_quote(file_title)} AND "
                    f"artist:{_lucene_quote(file_artist)}"
                )
                candidates.append((query, file_title, file_artist))
            else:
                candidates.append(
                    (
                        f"recording:{_lucene_quote(file_title)}",
                        file_title,
                        "",
                    )
                )

        seen = set()
        unique = []
        for item in candidates:
            key = item[0].casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return unique

    @staticmethod
    def _candidate_acceptable(recording, duration, has_artist):
        try:
            score = int(recording.get("score") or 0)
        except (TypeError, ValueError):
            score = 0

        threshold = 82 if has_artist else 90
        if score < threshold:
            return False

        try:
            remote_duration = float(recording.get("length") or 0) / 1000.0
        except (TypeError, ValueError):
            remote_duration = 0.0

        if duration > 0 and remote_duration > 0:
            tolerance = max(10.0, duration * 0.08)
            if abs(duration - remote_duration) > tolerance:
                return False

        return True

    def _search(self, snapshot):
        try:
            duration = max(0.0, float(snapshot.get("duration") or 0.0))
        except (TypeError, ValueError):
            duration = 0.0

        saw_network_error = False
        last_query = ""

        for query, _, artist in self._queries_for(snapshot):
            last_query = query
            payload, status = self._request_json(
                "/recording/",
                {
                    "query": query,
                    "fmt": "json",
                    "limit": 5,
                },
            )
            if status == "network-error":
                saw_network_error = True
                continue
            if not isinstance(payload, dict):
                continue

            recordings = payload.get("recordings")
            if not isinstance(recordings, list):
                continue

            for recording in recordings:
                if not isinstance(recording, dict):
                    continue
                if self._candidate_acceptable(
                    recording,
                    duration,
                    bool(artist),
                ):
                    return recording, query, saw_network_error

        return None, last_query, saw_network_error

    def fetch(self, snapshot):
        recording, query, saw_network_error = self._search(snapshot)
        if recording is None:
            return OnlineMetadataResult(
                path=snapshot["path"],
                status=(
                    "network-error"
                    if saw_network_error
                    else "not-found"
                ),
                query=query,
            )

        source_id = str(recording.get("id") or "")
        title = str(recording.get("title") or "").strip()
        artist = _artist_credit_text(recording.get("artist-credit"))
        album = _release_title(recording)
        year = str(recording.get("first-release-date") or "")[:4]
        genre = ""

        missing = set(snapshot.get("missing") or ())
        if source_id and "genre" in missing:
            details, status = self._request_json(
                f"/recording/{source_id}",
                {
                    "inc": "genres+artist-credits+releases",
                    "fmt": "json",
                },
            )
            if isinstance(details, dict):
                genre = _top_genre(details)
                if not artist:
                    artist = _artist_credit_text(
                        details.get("artist-credit")
                    )
                if not album:
                    album = _release_title(details)
            elif status == "network-error":
                # The high-confidence search result is still useful even if
                # the optional genre/details lookup is temporarily unavailable.
                pass

        try:
            score = int(recording.get("score") or 0)
        except (TypeError, ValueError):
            score = 0

        return OnlineMetadataResult(
            path=snapshot["path"],
            status="found",
            query=query,
            source_id=source_id,
            score=score,
            title=title,
            artist=artist,
            album=album,
            album_artist=artist,
            year=year,
            genre=genre,
        )


class OnlineMetadataManager:
    def __init__(self, enabled=True, client=None):
        self.enabled = bool(enabled)
        self.client = client or MusicBrainzClient()
        self._jobs = queue.Queue()
        self._results = queue.Queue()
        self._pending = set()
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def _ensure_worker(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._worker,
            name="meowplayer-metadata",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, metadata):
        if not self.enabled or not needs_online_metadata(metadata):
            return False

        path = str(Path(metadata.path).expanduser().resolve())
        with self._pending_lock:
            if path in self._pending:
                return False
            self._pending.add(path)

        snapshot = {
            "path": path,
            "title": metadata.title,
            "artist": metadata.artist,
            "album": metadata.album,
            "duration": metadata.duration,
            "missing": missing_metadata_fields(metadata),
        }
        self._jobs.put(snapshot)
        self._ensure_worker()
        return True

    def _worker(self):
        while not self._stop.is_set():
            try:
                snapshot = self._jobs.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                result = self.client.fetch(snapshot)
            except Exception:
                result = OnlineMetadataResult(
                    path=snapshot["path"],
                    status="network-error",
                    query="",
                )

            self._results.put(result)
            with self._pending_lock:
                self._pending.discard(snapshot["path"])
            self._jobs.task_done()

    def poll(self, limit=16):
        results = []
        for _ in range(max(1, int(limit))):
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                break
        return results

    def pending_count(self):
        with self._pending_lock:
            return len(self._pending)

    def stop(self):
        self._stop.set()
