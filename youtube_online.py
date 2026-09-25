import json
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field


LOGGER = logging.getLogger("meowplayer.youtube")


class YouTubeUnavailable(RuntimeError):
    pass


class YouTubeSearchError(RuntimeError):
    pass


class YouTubeResolveError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedYouTubeStream:
    video_id: str
    stream_url: str
    headers: dict
    resolved_at: float
    protocol: str = ""


@dataclass
class _ResolveTask:
    event: threading.Event = field(default_factory=threading.Event)
    result: ResolvedYouTubeStream | None = None
    error: Exception | None = None
    started_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class YouTubeTrack:
    video_id: str
    title: str
    artist: str
    duration: float
    url: str
    thumbnail_url: str = ""

    @property
    def artist_title(self):
        return f"{self.title} — {self.artist}"

    @property
    def duration_label(self):
        seconds = max(0, int(round(self.duration or 0.0)))
        if seconds <= 0:
            return "--:--"
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def queue_label(self):
        return f"{self.artist_title} · YouTube · {self.duration_label}"


class YouTubeCatalog:
    """Experimental keyless YouTube search through an external yt-dlp binary.

    Search metadata is intentionally ephemeral. MeowPlayer does not merge these
    results into the local Cat Catalog or pretend that remote media is a local
    file.
    """

    def __init__(
        self,
        enabled=False,
        executable=None,
        timeout=20.0,
        default_limit=12,
        stream_cache_ttl=300.0,
    ):
        self.enabled = bool(enabled)
        self.executable = executable or shutil.which("yt-dlp")
        self.timeout = max(1.0, float(timeout))
        self.default_limit = max(1, min(50, int(default_limit)))
        self.stream_cache_ttl = max(30.0, float(stream_cache_ttl))
        self._resolve_lock = threading.Lock()
        self._resolve_tasks = {}
        self._query_tasks = {}
        self._stream_cache = {}
        self._closed = False
        LOGGER.debug(
            "YouTubeCatalog enabled=%s executable=%s timeout=%s default_limit=%s",
            self.enabled,
            self.executable,
            self.timeout,
            self.default_limit,
        )

    @property
    def available(self):
        return self.enabled and bool(self.executable)

    @property
    def unavailable_reason(self):
        if not self.enabled:
            return "YouTube playback is disabled for this run."
        if not self.executable:
            return "yt-dlp was not found on PATH."
        return ""

    def search(self, query, limit=None):
        if not self.enabled:
            raise YouTubeUnavailable(
                "YouTube playback is disabled. Start MeowPlayer with --youtube."
            )
        if not self.executable:
            raise YouTubeUnavailable(
                "yt-dlp was not found. Install yt-dlp and restart MeowPlayer."
            )

        query = str(query or "").strip()
        if not query:
            return []

        limit = self.default_limit if limit is None else int(limit)
        limit = max(1, min(50, limit))
        target = f"ytsearch{limit}:{query}"

        command = [
            self.executable,
            "--flat-playlist",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            target,
        ]

        LOGGER.info(
            "yt-dlp search start query=%r limit=%s executable=%s",
            query,
            limit,
            self.executable,
        )

        # Resolve the likely first result in parallel with the flat catalog
        # lookup so the expensive extraction overlaps search latency.
        query_task = self.prefetch_first_query_result(query)

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            LOGGER.warning(
                "yt-dlp search timed out query=%r timeout=%s",
                query,
                self.timeout,
            )
            raise YouTubeSearchError(
                f"YouTube search timed out after {self.timeout:.0f}s."
            ) from exc
        except OSError as exc:
            LOGGER.exception("Could not launch yt-dlp executable=%s", self.executable)
            raise YouTubeSearchError(
                f"Could not launch yt-dlp: {exc}"
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            LOGGER.warning(
                "yt-dlp search failed query=%r returncode=%s stderr_tail=%r",
                query,
                completed.returncode,
                detail[-500:],
            )
            if len(detail) > 240:
                detail = detail[-240:]
            raise YouTubeSearchError(
                "yt-dlp search failed"
                + (f": {detail}" if detail else ".")
            )

        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            LOGGER.warning(
                "yt-dlp returned invalid JSON query=%r stdout_tail=%r",
                query,
                (completed.stdout or "")[-500:],
            )
            raise YouTubeSearchError(
                "yt-dlp returned invalid search metadata."
            ) from exc

        tracks = self._tracks_from_payload(payload, limit=limit)

        if tracks and query_task is not None:
            with self._resolve_lock:
                self._resolve_tasks.setdefault(
                    tracks[0].video_id,
                    query_task,
                )

        # Keep the first few visible results warm. Result 0 is normally
        # already resolving from the parallel query task.
        self.prefetch_tracks(tracks[:3])

        LOGGER.info(
            "yt-dlp search complete query=%r results=%s first_ready=%s",
            query,
            len(tracks),
            bool(tracks and self.get_cached_stream(tracks[0])),
        )
        return tracks

    def close(self):
        with self._resolve_lock:
            self._closed = True

    def _cache_get_locked(self, video_id, now):
        cached = self._stream_cache.get(video_id)
        if cached is None:
            return None

        if now - cached.resolved_at > self.stream_cache_ttl:
            self._stream_cache.pop(video_id, None)
            return None

        return cached

    def get_cached_stream(self, track_or_id):
        video_id = (
            track_or_id.video_id
            if hasattr(track_or_id, "video_id")
            else str(track_or_id)
        )
        now = time.monotonic()
        with self._resolve_lock:
            return self._cache_get_locked(video_id, now)

    def resolver_state(self, track_or_id):
        video_id = (
            track_or_id.video_id
            if hasattr(track_or_id, "video_id")
            else str(track_or_id)
        )
        now = time.monotonic()

        with self._resolve_lock:
            if self._cache_get_locked(video_id, now) is not None:
                return "ready"

            task = self._resolve_tasks.get(video_id)
            if task is None:
                return "idle"
            if not task.event.is_set():
                return "resolving"
            if task.error is not None:
                return "failed"
            if task.result is None or task.result.video_id != video_id:
                return "mismatch"
            return "ready"

    def prefetch_first_query_result(self, query):
        if not self.available or self._closed:
            return None

        key = str(query or "").strip().casefold()
        if not key:
            return None

        with self._resolve_lock:
            existing = self._query_tasks.get(key)
            if existing is not None:
                return existing

            task = _ResolveTask()
            self._query_tasks[key] = task

        self._start_resolver_thread(
            task,
            target=f"ytsearch1:{query}",
            expected_video_id=None,
            label=f"query:{query}",
        )
        return task

    def prefetch_track(self, track):
        if not self.available or self._closed or track is None:
            return None

        now = time.monotonic()
        with self._resolve_lock:
            cached = self._cache_get_locked(track.video_id, now)
            if cached is not None:
                return None

            existing = self._resolve_tasks.get(track.video_id)
            if existing is not None:
                if (
                    not existing.event.is_set()
                    or (
                        existing.result is not None
                        and existing.result.video_id == track.video_id
                    )
                ):
                    return existing

                self._resolve_tasks.pop(track.video_id, None)

            task = _ResolveTask()
            self._resolve_tasks[track.video_id] = task

        self._start_resolver_thread(
            task,
            target=track.url,
            expected_video_id=track.video_id,
            label=track.video_id,
        )
        return task

    def prefetch_tracks(self, tracks):
        for track in tracks:
            self.prefetch_track(track)

    def wait_for_stream(self, track, timeout=0.0):
        cached = self.get_cached_stream(track)
        if cached is not None:
            return cached

        task = self.prefetch_track(track)
        if task is None:
            return self.get_cached_stream(track)

        wait_seconds = max(0.0, float(timeout))
        if wait_seconds:
            task.event.wait(wait_seconds)

        cached = self.get_cached_stream(track)
        if cached is not None:
            return cached

        if (
            task.event.is_set()
            and task.result is not None
            and task.result.video_id != track.video_id
        ):
            self.prefetch_track(track)

        return None

    def resolve_error(self, track):
        with self._resolve_lock:
            task = self._resolve_tasks.get(track.video_id)
            if task is None or not task.event.is_set():
                return None
            return task.error

    def _start_resolver_thread(
        self,
        task,
        *,
        target,
        expected_video_id,
        label,
    ):
        thread = threading.Thread(
            target=self._resolve_worker,
            args=(task, target, expected_video_id, label),
            name=f"youtube-resolve-{label}"[:80],
            daemon=True,
        )
        thread.start()

    def _resolve_worker(
        self,
        task,
        target,
        expected_video_id,
        label,
    ):
        started = time.monotonic()
        try:
            result = self._resolve_target(
                target,
                expected_video_id=expected_video_id,
            )
            task.result = result

            with self._resolve_lock:
                if not self._closed:
                    self._stream_cache[result.video_id] = result

            LOGGER.info(
                "yt-dlp direct stream ready label=%r video_id=%s elapsed=%.2fs "
                "protocol=%s",
                label,
                result.video_id,
                time.monotonic() - started,
                result.protocol or "unknown",
            )
        except Exception as exc:
            task.error = exc
            LOGGER.warning(
                "yt-dlp direct stream resolve failed label=%r elapsed=%.2fs "
                "error=%s",
                label,
                time.monotonic() - started,
                exc,
            )
        finally:
            task.event.set()

    def _resolve_target(self, target, expected_video_id=None):
        if not self.executable:
            raise YouTubeUnavailable(
                "yt-dlp was not found. Install yt-dlp and restart MeowPlayer."
            )

        output_template = (
            '{"id":%(id)j,"url":%(url)j,'
            '"http_headers":%(http_headers)j,'
            '"protocol":%(protocol)j}'
        )
        command = [
            self.executable,
            "--no-warnings",
            "--no-progress",
            "--skip-download",
            "--no-playlist",
            "--no-check-formats",
            "--format",
            (
                "bestaudio[protocol=https]/"
                "bestaudio[protocol=http]/"
                "bestaudio/best"
            ),
            "--print",
            output_template,
            target,
        ]

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise YouTubeResolveError(
                f"direct stream resolution timed out after {self.timeout:.0f}s"
            ) from exc
        except OSError as exc:
            raise YouTubeResolveError(
                f"could not launch yt-dlp: {exc}"
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            if len(detail) > 300:
                detail = detail[-300:]
            raise YouTubeResolveError(
                "yt-dlp direct stream resolution failed"
                + (f": {detail}" if detail else ".")
            )

        lines = [
            line.strip()
            for line in (completed.stdout or "").splitlines()
            if line.strip()
        ]
        if not lines:
            raise YouTubeResolveError(
                "yt-dlp returned no direct stream metadata."
            )

        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise YouTubeResolveError(
                "yt-dlp returned invalid direct stream metadata."
            ) from exc

        video_id = str(payload.get("id") or "").strip()
        stream_url = str(payload.get("url") or "").strip()
        headers = payload.get("http_headers") or {}
        protocol = str(payload.get("protocol") or "").strip()

        if not video_id or not stream_url.startswith(("https://", "http://")):
            raise YouTubeResolveError(
                "yt-dlp did not provide a playable direct stream URL."
            )

        if expected_video_id and video_id != expected_video_id:
            raise YouTubeResolveError(
                f"yt-dlp resolved unexpected video id {video_id!r}"
            )

        if not isinstance(headers, dict):
            headers = {}

        return ResolvedYouTubeStream(
            video_id=video_id,
            stream_url=stream_url,
            headers={
                str(key): str(value)
                for key, value in headers.items()
                if value is not None
            },
            resolved_at=time.monotonic(),
            protocol=protocol,
        )

    @classmethod
    def _tracks_from_payload(cls, payload, limit=12):
        if not isinstance(payload, dict):
            return []

        entries = payload.get("entries") or []
        tracks = []
        seen = set()

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            video_id = str(entry.get("id") or "").strip()
            if not video_id or video_id in seen:
                continue

            title = str(entry.get("title") or "").strip()
            if not title:
                continue

            artist = cls._artist_from_entry(entry)
            duration = cls._duration_from_entry(entry)
            url = cls._watch_url(entry, video_id)
            thumbnail = cls._thumbnail_from_entry(entry)

            tracks.append(
                YouTubeTrack(
                    video_id=video_id,
                    title=title,
                    artist=artist,
                    duration=duration,
                    url=url,
                    thumbnail_url=thumbnail,
                )
            )
            seen.add(video_id)

            if len(tracks) >= limit:
                break

        return tracks

    @staticmethod
    def _artist_from_entry(entry):
        for key in (
            "artist",
            "artists",
            "creator",
            "uploader",
            "channel",
            "channel_name",
        ):
            value = entry.get(key)
            if isinstance(value, (list, tuple)):
                value = ", ".join(
                    str(item).strip()
                    for item in value
                    if str(item).strip()
                )
            value = str(value or "").strip()
            if value:
                return value
        return "Unknown YouTube Artist"

    @staticmethod
    def _duration_from_entry(entry):
        try:
            return max(0.0, float(entry.get("duration") or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _watch_url(entry, video_id):
        for key in ("webpage_url", "original_url"):
            value = str(entry.get(key) or "").strip()
            if value.startswith(("https://", "http://")):
                return value

        raw_url = str(entry.get("url") or "").strip()
        if raw_url.startswith(("https://", "http://")):
            return raw_url

        return f"https://www.youtube.com/watch?v={video_id}"

    @staticmethod
    def _thumbnail_from_entry(entry):
        direct = str(entry.get("thumbnail") or "").strip()
        if direct:
            return direct

        thumbnails = entry.get("thumbnails") or []
        if isinstance(thumbnails, list):
            for item in reversed(thumbnails):
                if not isinstance(item, dict):
                    continue
                value = str(item.get("url") or "").strip()
                if value:
                    return value

        return ""
