import json
import logging
import shutil
import subprocess
from dataclasses import dataclass


LOGGER = logging.getLogger("meowplayer.youtube")


class YouTubeUnavailable(RuntimeError):
    pass


class YouTubeSearchError(RuntimeError):
    pass


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
    ):
        self.enabled = bool(enabled)
        self.executable = executable or shutil.which("yt-dlp")
        self.timeout = max(1.0, float(timeout))
        self.default_limit = max(1, min(50, int(default_limit)))
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
        LOGGER.info(
            "yt-dlp search complete query=%r results=%s",
            query,
            len(tracks),
        )
        return tracks

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
