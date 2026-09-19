import os
import sqlite3
import time
from pathlib import Path


SCHEMA_VERSION = 1


def _xdg_cache_home():
    value = os.environ.get("XDG_CACHE_HOME")
    if value:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
    return Path.home() / ".cache"


def catalog_path():
    return _xdg_cache_home() / "meowplayer" / "library.sqlite3"


class LibraryCatalog:
    """Persistent metadata cache for MeowPlayer music libraries."""

    def __init__(self, music_dir, path=None):
        self.music_dir = Path(music_dir).expanduser().resolve()
        self.path = Path(path).expanduser() if path else catalog_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row

        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self._ensure_schema()

    def _ensure_schema(self):
        version = self.connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError(
                f"Unsupported Cat Catalog schema version {version}; "
                f"expected {SCHEMA_VERSION}."
            )

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                path TEXT PRIMARY KEY,
                root TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT NOT NULL,
                album_artist TEXT NOT NULL,
                track_number INTEGER NOT NULL,
                track_text TEXT NOT NULL,
                year TEXT NOT NULL,
                folder TEXT NOT NULL,
                filename TEXT NOT NULL,
                tagged INTEGER NOT NULL,
                last_scanned_ns INTEGER NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tracks_root
            ON tracks(root)
            """
        )
        self.connection.execute(
            f"PRAGMA user_version = {SCHEMA_VERSION}"
        )
        self.connection.commit()

    def get(self, path, stat_result):
        resolved = str(Path(path).resolve())
        row = self.connection.execute(
            """
            SELECT
                title,
                artist,
                album,
                album_artist,
                track_number,
                track_text,
                year,
                folder,
                filename,
                tagged
            FROM tracks
            WHERE path = ?
              AND root = ?
              AND size = ?
              AND mtime_ns = ?
            """,
            (
                resolved,
                str(self.music_dir),
                int(stat_result.st_size),
                int(stat_result.st_mtime_ns),
            ),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    def put(self, path, stat_result, metadata):
        resolved = str(Path(path).resolve())

        self.connection.execute(
            """
            INSERT INTO tracks (
                path,
                root,
                size,
                mtime_ns,
                title,
                artist,
                album,
                album_artist,
                track_number,
                track_text,
                year,
                folder,
                filename,
                tagged,
                last_scanned_ns
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                root = excluded.root,
                size = excluded.size,
                mtime_ns = excluded.mtime_ns,
                title = excluded.title,
                artist = excluded.artist,
                album = excluded.album,
                album_artist = excluded.album_artist,
                track_number = excluded.track_number,
                track_text = excluded.track_text,
                year = excluded.year,
                folder = excluded.folder,
                filename = excluded.filename,
                tagged = excluded.tagged,
                last_scanned_ns = excluded.last_scanned_ns
            """,
            (
                resolved,
                str(self.music_dir),
                int(stat_result.st_size),
                int(stat_result.st_mtime_ns),
                metadata.title,
                metadata.artist,
                metadata.album,
                metadata.album_artist,
                int(metadata.track_number),
                metadata.track_text,
                metadata.year,
                metadata.folder,
                metadata.filename,
                int(bool(metadata.tagged)),
                time.time_ns(),
            ),
        )

    def clear_root(self):
        cursor = self.connection.execute(
            "DELETE FROM tracks WHERE root = ?",
            (str(self.music_dir),),
        )
        return max(0, int(cursor.rowcount))

    def prune(self, existing_paths):
        existing = {
            str(Path(path).resolve())
            for path in existing_paths
        }

        cached = self.connection.execute(
            "SELECT path FROM tracks WHERE root = ?",
            (str(self.music_dir),),
        ).fetchall()

        stale = [
            (row["path"],)
            for row in cached
            if row["path"] not in existing
        ]

        if stale:
            self.connection.executemany(
                "DELETE FROM tracks WHERE path = ?",
                stale,
            )

        return len(stale)

    def commit(self):
        self.connection.commit()

    def count(self):
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM tracks WHERE root = ?",
            (str(self.music_dir),),
        ).fetchone()
        return int(row["count"])

    def close(self):
        self.connection.close()
