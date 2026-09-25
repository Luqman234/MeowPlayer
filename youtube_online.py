import json
import logging
import os
import platform
import queue
import selectors
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


LOGGER = logging.getLogger("meowplayer.youtube")


GLIBC_RESOLVER_WORKAROUND = "single-request-reopen"


def network_subprocess_env(*, resolver_workaround=True, **extra):
    """Return an inherited subprocess environment with a scoped glibc DNS workaround.

    Some home-router DNS proxies mishandle glibc's paired A/AAAA resolver traffic:
    one reply arrives quickly while the other is dropped, leaving getaddrinfo() to
    wait roughly five seconds before retrying.  single-request-reopen tells glibc
    to issue the lookups separately with a reopened socket.

    Keep this process-local.  Preserve any user-provided RES_OPTIONS rather than
    replacing global DNS configuration or forcing a public resolver.
    """
    env = os.environ.copy()
    libc_name, _ = platform.libc_ver()
    if resolver_workaround and libc_name.lower() == "glibc":
        options = env.get("RES_OPTIONS", "").split()
        if GLIBC_RESOLVER_WORKAROUND not in options:
            options.append(GLIBC_RESOLVER_WORKAROUND)
        env["RES_OPTIONS"] = " ".join(options)
    env.update({key: str(value) for key, value in extra.items()})
    return env


class YouTubeUnavailable(RuntimeError):
    pass


class YouTubeSearchError(RuntimeError):
    pass


class YouTubeDownloadError(RuntimeError):
    pass


class YouTubeBrowseError(RuntimeError):
    pass


YOUTUBE_SEARCH_MODES = {"all", "artist"}


def normalize_youtube_search(query, search_mode="all"):
    """Normalize user input and return (query, mode).

    The ordinary search prompt also accepts an artist:Name prefix so artist
    search is reachable without a second modal. The dedicated Artist Search UI
    simply supplies search_mode="artist" directly.
    """
    query = str(query or "").strip()
    mode = str(search_mode or "all").strip().lower()
    if mode not in YOUTUBE_SEARCH_MODES:
        mode = "all"

    if mode == "all" and query.casefold().startswith("artist:"):
        artist = query.split(":", 1)[1].strip()
        if artist:
            query = artist
            mode = "artist"

    return query, mode


def youtube_search_target(query, limit=None, search_mode="all"):
    """Build the yt-dlp ytsearch target for a general or artist-first search.

    limit=None requests every result exposed by yt-dlp's YouTube search
    extractor. Explicit numeric limits remain supported for callers that want
    bounded searches.
    """
    query, mode = normalize_youtube_search(query, search_mode)
    if mode == "artist":
        # Keep this as a normal YouTube search rather than brittle uploader-only
        # filtering: official tracks are often uploaded by labels/VEVO channels.
        # Quoting the artist name plus "music" biases discovery toward that artist
        # while preserving useful official/label uploads.
        artist = " ".join(query.replace('"', " ").split())
        query = f'"{artist}" music'
    if limit is None:
        return f"ytsearchall:{query}"
    limit = max(1, min(50, int(limit)))
    return f"ytsearch{limit}:{query}"

@dataclass(frozen=True)
class YouTubeTrack:
    video_id: str
    title: str
    artist: str
    duration: float
    url: str
    thumbnail_url: str = ""
    channel_id: str = ""
    channel_url: str = ""

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


@dataclass(frozen=True)
class YouTubePlaylist:
    playlist_id: str
    title: str
    channel: str
    url: str
    item_count: int = 0

    @property
    def count_label(self):
        if self.item_count <= 0:
            return "playlist"
        noun = "track" if self.item_count == 1 else "tracks"
        return f"{self.item_count} {noun}"


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
        default_limit=None,
    ):
        self.enabled = bool(enabled)
        self.executable = executable or shutil.which("yt-dlp")
        self.timeout = max(1.0, float(timeout))
        self.default_limit = (
            None
            if default_limit is None
            else max(1, min(50, int(default_limit)))
        )
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

    def search(self, query, limit=None, search_mode="all"):
        if not self.enabled:
            raise YouTubeUnavailable(
                "YouTube playback is disabled. Start MeowPlayer with --youtube."
            )
        if not self.executable:
            raise YouTubeUnavailable(
                "yt-dlp was not found. Install yt-dlp and restart MeowPlayer."
            )

        query, search_mode = normalize_youtube_search(query, search_mode)
        if not query:
            return []

        # Compatibility helper for non-TUI callers. The UI consumes the session
        # queue directly, so it can navigate and prefetch before search finishes.
        session = YouTubeSearchSession(
            self,
            query,
            limit=limit,
            search_mode=search_mode,
        )
        tracks = []
        try:
            while True:
                kind, value = session.results.get(timeout=self.timeout + 2)
                if kind == "track":
                    tracks.append(value)
                elif kind == "error":
                    raise YouTubeSearchError(value)
                else:
                    return tracks
        finally:
            session.close()

    @classmethod
    def _tracks_from_payload(cls, payload, limit=None):
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
            channel_id, channel_url = cls._channel_from_entry(entry)

            tracks.append(
                YouTubeTrack(
                    video_id=video_id,
                    title=title,
                    artist=artist,
                    duration=duration,
                    url=url,
                    thumbnail_url=thumbnail,
                    channel_id=channel_id,
                    channel_url=channel_url,
                )
            )
            seen.add(video_id)

            if limit is not None and len(tracks) >= max(1, int(limit)):
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

    @staticmethod
    def _channel_from_entry(entry):
        channel_id = ""
        for key in ("channel_id", "uploader_id"):
            value = str(entry.get(key) or "").strip()
            if value:
                channel_id = value
                break

        channel_url = ""
        for key in ("channel_url", "uploader_url"):
            value = str(entry.get(key) or "").strip()
            if value.startswith(("https://", "http://")):
                channel_url = value
                break

        if not channel_url and channel_id:
            channel_url = f"https://www.youtube.com/channel/{channel_id}"

        return channel_id, channel_url

    @staticmethod
    def _playlist_from_entry(entry):
        if not isinstance(entry, dict):
            return None
        playlist_id = str(entry.get("id") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not playlist_id or not title:
            return None

        url = ""
        for key in ("webpage_url", "original_url", "url"):
            value = str(entry.get(key) or "").strip()
            if value.startswith(("https://", "http://")):
                url = value
                break
        if not url:
            url = f"https://www.youtube.com/playlist?list={playlist_id}"

        channel = YouTubeCatalog._artist_from_entry(entry)
        try:
            item_count = max(
                0,
                int(
                    entry.get("playlist_count")
                    or entry.get("n_entries")
                    or 0
                ),
            )
        except (TypeError, ValueError):
            item_count = 0

        return YouTubePlaylist(
            playlist_id=playlist_id,
            title=title,
            channel=channel,
            url=url,
            item_count=item_count,
        )


# Stream URLs and headers are deliberately held only in memory.
class StreamResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedStream:
    video_id: str
    url: str
    headers: dict[str, str]
    format_id: str | None
    resolved_at: float
    expires_at: float

    def valid(self, now=None):
        return (time.monotonic() if now is None else now) < self.expires_at


def resolver_command(executable, track):
    return [executable, "--ignore-config", "--no-playlist", "--no-warnings",
            "--skip-download", "-f", "bestaudio/best", "--print",
            "%(.{url,http_headers,format_id})j", track.url]


def parse_stream(track, output, ttl=180.0):
    try:
        data = json.loads(output)
        url = data["url"]
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError("invalid stream URL")
        headers = data.get("http_headers") or {}
        if not isinstance(headers, dict):
            raise ValueError("invalid headers")
        # Preserve extractor-supplied authentication/UA headers per file only.
        headers = {str(k): str(v) for k, v in headers.items()}
        if any("\r" in k + v or "\n" in k + v for k, v in headers.items()):
            raise ValueError("invalid header newline")
        now = time.monotonic()
        expiry = parse_qs(parsed.query).get("expire", [None])[0]
        lifetime = float(ttl)
        if expiry is not None:
            lifetime = min(lifetime, float(expiry) - time.time() - 30.0)
        if lifetime <= 0:
            raise ValueError("expired stream URL")
        return ResolvedStream(track.video_id, url, headers,
                              data.get("format_id"), now, now + lifetime)
    except (ValueError, TypeError, KeyError) as exc:
        raise StreamResolutionError("Invalid or expired stream metadata") from exc


@dataclass
class _ResolveJob:
    track: YouTubeTrack
    future: Future
    due: float
    cancel: threading.Event
    prefetch: bool


class YouTubeStreamResolver:
    """One worker, one replaceable queued selection, bounded ephemeral LRU.

    Callbacks never touch curses or player state. Enter shares the exact Future
    used by prefetch. A foreground request supersedes unrelated background work.
    """

    def __init__(self, executable, timeout=20.0, ttl=180.0, capacity=16):
        self.executable = executable
        self.timeout = timeout
        self.ttl = ttl
        self.capacity = capacity
        self._condition = threading.Condition()
        self._cache = OrderedDict()
        self._jobs = {}
        self._next = None
        self._active = None
        self._closed = False
        self._thread = threading.Thread(target=self._work, name="yt-resolver", daemon=True)
        self._thread.start()

    def cached(self, track):
        with self._condition:
            key = ("youtube", track.video_id)
            stream = self._cache.get(key)
            if stream and stream.valid():
                self._cache.move_to_end(key)
                return stream
            self._cache.pop(key, None)
            return None

    def invalidate(self, track):
        with self._condition:
            self._cache.pop(("youtube", track.video_id), None)

    def request(self, track, *, prefetch=False, debounce=0.0):
        with self._condition:
            future = Future()
            if self._closed:
                future.cancel()
                return future
            # Returning to a cached/active selection must also discard a stale
            # queued background selection. Never displace an Enter request.
            if (self._next and self._next.prefetch
                    and self._next.track.video_id != track.video_id):
                self._next.future.cancel()
                self._jobs.pop(self._next.track.video_id, None)
                self._next = None
            cached = self.cached(track)
            if cached:
                future.set_result(cached)
                return future
            existing = self._jobs.get(track.video_id)
            if existing:
                if not prefetch:
                    existing.due = 0.0
                    existing.prefetch = False
                    if self._active and self._active is not existing:
                        self._active.cancel.set()
                    self._condition.notify_all()
                return existing.future
            if prefetch and self._next and not self._next.prefetch:
                future.cancel()
                return future
            if self._next:
                self._next.future.cancel()
                self._jobs.pop(self._next.track.video_id, None)
            job = _ResolveJob(track, future, time.monotonic() + debounce,
                              threading.Event(), prefetch)
            self._next = job
            self._jobs[track.video_id] = job
            if not prefetch and self._active:
                self._active.cancel.set()
            self._condition.notify_all()
            return future

    def resolve(self, track):
        return self.request(track).result(timeout=self.timeout + 2)

    def _extract(self, track, cancel):
        if not self.executable:
            raise StreamResolutionError("yt-dlp is unavailable")
        started = time.monotonic()
        LOGGER.debug("YT_LATENCY resolver_process_started=%.6f video_id=%s", started, track.video_id)
        try:
            process = subprocess.Popen(
                resolver_command(self.executable, track),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                env=network_subprocess_env(),
            )
        except OSError as exc:
            raise StreamResolutionError("Could not launch yt-dlp") from exc
        try:
            while True:
                if cancel.is_set():
                    raise CancelledError()
                if time.monotonic() - started >= self.timeout:
                    raise StreamResolutionError("Stream resolution timed out")
                try:
                    output, _ = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise StreamResolutionError("yt-dlp stream resolution failed")
            result = parse_stream(track, output, self.ttl)
            LOGGER.debug("YT_LATENCY direct_stream_url_ready=%.6f resolve_ms=%.3f video_id=%s",
                         time.monotonic(), (time.monotonic() - started) * 1000, track.video_id)
            return result
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()
            LOGGER.debug("YT_LATENCY resolver_process_finished=%.6f video_id=%s",
                         time.monotonic(), track.video_id)

    def _work(self):
        while True:
            with self._condition:
                while not self._closed:
                    if self._next:
                        delay = self._next.due - time.monotonic()
                        if delay <= 0:
                            break
                        self._condition.wait(delay)
                    else:
                        self._condition.wait()
                if self._closed:
                    return
                job = self._next
                self._next = None
                self._active = job
                if not job.future.set_running_or_notify_cancel():
                    self._jobs.pop(job.track.video_id, None)
                    self._active = None
                    continue
            track, future = job.track, job.future
            cancel, prefetch = job.cancel, job.prefetch
            started = time.monotonic()
            LOGGER.debug("YT_PREFETCH begin video_id=%s prefetch=%s prefetch_start=%.6f",
                         track.video_id, prefetch, started)
            try:
                stream = self._extract(track, cancel)
            except Exception as exc:
                LOGGER.debug("YT_PREFETCH failed video_id=%s error=%s", track.video_id, type(exc).__name__)
                with self._condition:
                    self._jobs.pop(track.video_id, None)
                    self._active = None
                    future.set_exception(exc)
            else:
                with self._condition:
                    self._cache[("youtube", track.video_id)] = stream
                    while len(self._cache) > self.capacity:
                        self._cache.popitem(last=False)
                    self._jobs.pop(track.video_id, None)
                    self._active = None
                    future.set_result(stream)
                LOGGER.debug("YT_PREFETCH complete video_id=%s elapsed_ms=%.3f",
                             track.video_id, (time.monotonic() - started) * 1000)

    def close(self):
        with self._condition:
            self._closed = True
            if self._next:
                self._next.future.cancel()
            if self._active:
                self._active.cancel.set()
            self._condition.notify_all()
        self._thread.join(timeout=2.0)


class YouTubeSearchSession:
    """Line-oriented search delivery. No curses calls from this worker."""

    def __init__(self, catalog, query, limit=None, search_mode="all"):
        self.results = queue.SimpleQueue()
        self.cancel = threading.Event()
        self.query, self.search_mode = normalize_youtube_search(query, search_mode)
        self.thread = threading.Thread(
            target=self._run,
            args=(catalog, self.query, limit, self.search_mode),
            name="yt-search",
            daemon=True,
        )
        self.thread.start()

    def _run(self, catalog, query, limit, search_mode):
        started = time.monotonic()
        process = None
        LOGGER.debug(
            "YT_LATENCY search_start=%.6f search_mode=%s",
            started,
            search_mode,
        )
        try:
            if not catalog.available:
                raise YouTubeUnavailable(catalog.unavailable_reason)
            if limit is None:
                limit = catalog.default_limit
            elif limit is not None:
                limit = max(1, min(50, int(limit)))
            command = [catalog.executable, "--ignore-config", "--flat-playlist",
                       "--skip-download", "--no-warnings", "--lazy-playlist",
                       "--print", "%(.{id,title,artist,artists,creator,uploader,channel,channel_id,channel_url,uploader_id,uploader_url,duration,webpage_url})j",
                       youtube_search_target(query, limit, search_mode)]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=network_subprocess_env(PYTHONUNBUFFERED="1"),
            )
            seen = set()
            buffer = b""
            last_progress = started
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while not self.cancel.is_set():
                    if not selector.select(timeout=0.1):
                        if process.poll() is not None:
                            break
                        if time.monotonic() - last_progress >= catalog.timeout:
                            raise YouTubeSearchError(
                                "YouTube search stalled"
                            )
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    last_progress = time.monotonic()
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        data = json.loads(line)
                        tracks = catalog._tracks_from_payload({"entries": [data]})
                        for track in tracks:
                            if track.video_id in seen:
                                continue
                            if not seen:
                                LOGGER.debug("YT_LATENCY first_search_result=%.6f search_first_result_ms=%.3f",
                                             time.monotonic(), (time.monotonic() - started) * 1000)
                            seen.add(track.video_id)
                            self.results.put(("track", track))
            if not self.cancel.is_set() and process.wait(timeout=1) != 0:
                raise YouTubeSearchError("yt-dlp search failed")
            self.results.put(("done", None))
        except Exception:
            # Never expose extractor output: it can include signed URLs/cookies.
            self.results.put(("error", "YouTube search failed or timed out."))
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate()
            LOGGER.debug("YT_LATENCY search_complete=%.6f search_total_ms=%.3f",
                         time.monotonic(), (time.monotonic() - started) * 1000)

    def close(self):
        self.cancel.set()
        self.thread.join(timeout=2.0)


def youtube_download_command(
    executable,
    track,
    destination,
    *,
    ffmpeg_executable=None,
):
    """Build a safe argv-only yt-dlp command for adopting one online track."""
    destination = Path(destination).expanduser()
    output_template = destination / "%(title)s [%(id)s].%(ext)s"
    command = [
        str(executable),
        "--ignore-config",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--no-overwrites",
        "-f",
        "bestaudio/best",
        "--extract-audio",
        "--audio-format",
        "opus",
        "--audio-quality",
        "0",
        "--embed-metadata",
    ]
    if ffmpeg_executable:
        command.extend(
            ["--ffmpeg-location", str(ffmpeg_executable)]
        )
    command.extend(
        [
            "--output",
            str(output_template),
            "--print",
            "after_move:filepath",
            track.url,
        ]
    )
    return command


class YouTubeDownloadSession:
    """Download one selected Internet Nest track without blocking curses."""

    def __init__(
        self,
        executable,
        track,
        destination,
        *,
        ffmpeg_executable=None,
    ):
        self.results = queue.SimpleQueue()
        self.cancel = threading.Event()
        self.track = track
        self.destination = Path(destination).expanduser()
        self.executable = executable
        self.ffmpeg_executable = (
            ffmpeg_executable
            if ffmpeg_executable is not None
            else shutil.which("ffmpeg")
        )
        self._process = None
        self.thread = threading.Thread(
            target=self._run,
            name="yt-download",
            daemon=True,
        )
        self.thread.start()

    def _run(self):
        process = None
        try:
            if not self.executable:
                raise YouTubeDownloadError(
                    "yt-dlp was not found on PATH."
                )
            if not self.ffmpeg_executable:
                raise YouTubeDownloadError(
                    "ffmpeg is required to save Internet Nest audio as Opus."
                )

            self.destination.mkdir(parents=True, exist_ok=True)
            command = youtube_download_command(
                self.executable,
                self.track,
                self.destination,
                ffmpeg_executable=self.ffmpeg_executable,
            )
            LOGGER.info(
                "Starting Internet Nest download video_id=%s destination=%s",
                self.track.video_id,
                self.destination,
            )
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                env=network_subprocess_env(PYTHONUNBUFFERED="1"),
            )
            self._process = process

            while process.poll() is None:
                if self.cancel.wait(0.1):
                    process.kill()
                    process.communicate()
                    return

            stdout, _ = process.communicate()
            if self.cancel.is_set():
                return
            if process.returncode != 0:
                raise YouTubeDownloadError(
                    "yt-dlp could not download this track."
                )

            paths = [
                line.strip()
                for line in str(stdout or "").splitlines()
                if line.strip()
            ]
            if not paths:
                raise YouTubeDownloadError(
                    "yt-dlp finished without reporting a downloaded file."
                )

            downloaded = Path(paths[-1]).expanduser()
            if not downloaded.is_absolute():
                downloaded = self.destination / downloaded
            downloaded = downloaded.resolve()

            try:
                downloaded.relative_to(self.destination.resolve())
            except ValueError as exc:
                raise YouTubeDownloadError(
                    "yt-dlp reported a file outside the music library."
                ) from exc

            if not downloaded.is_file():
                raise YouTubeDownloadError(
                    "Downloaded audio file could not be found."
                )

            LOGGER.info(
                "Internet Nest download complete video_id=%s path=%s",
                self.track.video_id,
                downloaded,
            )
            self.results.put(("done", downloaded))
        except YouTubeDownloadError as exc:
            LOGGER.warning(
                "Internet Nest download failed video_id=%s reason=%s",
                getattr(self.track, "video_id", ""),
                exc,
            )
            self.results.put(("error", str(exc)))
        except Exception:
            LOGGER.exception(
                "Unexpected Internet Nest download failure video_id=%s",
                getattr(self.track, "video_id", ""),
            )
            self.results.put(
                ("error", "Internet Nest download failed unexpectedly.")
            )
        finally:
            self._process = None
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()

    def close(self):
        self.cancel.set()
        process = self._process
        if process is not None and process.poll() is None:
            process.kill()
        self.thread.join(timeout=2.0)


def youtube_creator_root_url(channel_url):
    """Normalize a YouTube channel URL back to its channel root."""
    raw = str(channel_url or "").strip().rstrip("/")
    if not raw.startswith(("https://", "http://")):
        return ""

    for suffix in (
        "/videos",
        "/playlists",
        "/releases",
        "/featured",
        "/streams",
        "/shorts",
    ):
        if raw.endswith(suffix):
            raw = raw[:-len(suffix)]
            break
    return raw


def youtube_creator_section_url(channel_url, section):
    """Return a creator channel subsection URL suitable for yt-dlp."""
    if section not in {"videos", "playlists", "releases"}:
        raise ValueError(f"Unsupported creator section: {section}")

    root = youtube_creator_root_url(channel_url)
    if not root:
        return ""
    return f"{root}/{section}"


def youtube_creator_browse_targets(channel_url, mode):
    """Return ordered yt-dlp targets with fallbacks for uneven channel layouts."""
    root = youtube_creator_root_url(channel_url)
    if not root:
        return ()

    if mode == "uploads":
        candidates = (
            youtube_creator_section_url(root, "videos"),
            root,
        )
    elif mode == "playlists":
        candidates = (
            youtube_creator_section_url(root, "playlists"),
            youtube_creator_section_url(root, "releases"),
        )
    elif mode == "playlist":
        candidates = (str(channel_url or "").strip(),)
    else:
        raise ValueError(f"Unsupported YouTube browse mode: {mode}")

    ordered = []
    seen = set()
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return tuple(ordered)


class YouTubeBrowseSession:
    """Stream creator uploads, creator playlists, or playlist tracks."""

    MODES = {"uploads", "playlists", "playlist"}

    def __init__(
        self,
        catalog,
        source_url,
        mode,
        *,
        timeout=None,
    ):
        if mode not in self.MODES:
            raise ValueError(f"Unsupported YouTube browse mode: {mode}")
        self.results = queue.SimpleQueue()
        self.cancel = threading.Event()
        self.catalog = catalog
        self.source_url = str(source_url or "").strip()
        self.mode = mode
        self.timeout = (
            catalog.timeout
            if timeout is None
            else max(1.0, float(timeout))
        )
        self.thread = threading.Thread(
            target=self._run,
            name=f"yt-browse-{mode}",
            daemon=True,
        )
        self.thread.start()

    def _targets(self):
        return youtube_creator_browse_targets(
            self.source_url,
            self.mode,
        )

    def _run(self):
        process = None
        try:
            if not self.catalog.available:
                raise YouTubeBrowseError(
                    self.catalog.unavailable_reason
                )

            targets = self._targets()
            if not targets:
                raise YouTubeBrowseError(
                    "This result does not expose a browsable YouTube channel."
                )

            fields = (
                "%(.{id,title,artist,artists,creator,uploader,channel,"
                "channel_id,channel_url,uploader_id,uploader_url,duration,"
                "playlist_count,n_entries,webpage_url,original_url,url})j"
            )
            seen = set()
            succeeded = False

            for attempt, target in enumerate(targets, start=1):
                if self.cancel.is_set():
                    return

                process = None
                buffer = b""
                before_count = len(seen)
                last_progress = time.monotonic()
                try:
                    command = [
                        self.catalog.executable,
                        "--ignore-config",
                        "--flat-playlist",
                        "--skip-download",
                        "--no-warnings",
                        "--lazy-playlist",
                        "--print",
                        fields,
                        target,
                    ]
                    LOGGER.info(
                        "YouTube browse requested mode=%s source=%s attempt=%s/%s",
                        self.mode,
                        target,
                        attempt,
                        len(targets),
                    )
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        env=network_subprocess_env(PYTHONUNBUFFERED="1"),
                    )

                    with selectors.DefaultSelector() as selector:
                        selector.register(
                            process.stdout,
                            selectors.EVENT_READ,
                        )
                        while not self.cancel.is_set():
                            if not selector.select(timeout=0.1):
                                if process.poll() is not None:
                                    break
                                if (
                                    time.monotonic() - last_progress
                                    >= self.timeout
                                ):
                                    raise YouTubeBrowseError(
                                        "YouTube channel browsing stalled."
                                    )
                                continue

                            chunk = os.read(
                                process.stdout.fileno(),
                                65536,
                            )
                            if not chunk:
                                break
                            last_progress = time.monotonic()
                            buffer += chunk

                            while b"\n" in buffer:
                                line, buffer = buffer.split(b"\n", 1)
                                data = json.loads(line)

                                if self.mode == "playlists":
                                    item = self.catalog._playlist_from_entry(
                                        data
                                    )
                                    if (
                                        item is None
                                        or item.playlist_id in seen
                                    ):
                                        continue
                                    seen.add(item.playlist_id)
                                    self.results.put(("playlist", item))
                                    continue

                                tracks = self.catalog._tracks_from_payload(
                                    {"entries": [data]}
                                )
                                for track in tracks:
                                    if track.video_id in seen:
                                        continue
                                    seen.add(track.video_id)
                                    self.results.put(("track", track))

                    if self.cancel.is_set():
                        return

                    returncode = process.wait(timeout=1)
                    if returncode == 0:
                        produced_items = len(seen) > before_count
                        if produced_items or attempt == len(targets):
                            succeeded = True
                            break
                        LOGGER.info(
                            "YouTube browse target was empty mode=%s source=%s; "
                            "trying fallback",
                            self.mode,
                            target,
                        )
                        continue

                    LOGGER.info(
                        "YouTube browse target failed mode=%s source=%s "
                        "returncode=%s; trying fallback if available",
                        self.mode,
                        target,
                        returncode,
                    )
                except YouTubeBrowseError as exc:
                    LOGGER.info(
                        "YouTube browse target unavailable mode=%s source=%s "
                        "reason=%s; trying fallback if available",
                        self.mode,
                        target,
                        exc,
                    )
                finally:
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.communicate()
                    process = None

            if not succeeded:
                raise YouTubeBrowseError(
                    "yt-dlp could not browse this YouTube channel."
                )

            if not self.cancel.is_set():
                self.results.put(("done", None))
        except YouTubeBrowseError as exc:
            self.results.put(("error", str(exc)))
        except Exception:
            LOGGER.exception(
                "Unexpected YouTube browse failure mode=%s",
                self.mode,
            )
            self.results.put(
                ("error", "YouTube channel browsing failed unexpectedly.")
            )
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def close(self):
        self.cancel.set()
        self.thread.join(timeout=2.0)
