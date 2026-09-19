import os
import shutil
import sqlite3
import time
from pathlib import Path


SCHEMA_VERSION = 2


def _xdg_cache_home():
    value = os.environ.get("XDG_CACHE_HOME")
    if value:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
    return Path.home() / ".cache"


def _xdg_data_home():
    value = os.environ.get("XDG_DATA_HOME")
    if value:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
    return Path.home() / ".local" / "share"


def _legacy_catalog_path():
    return _xdg_cache_home() / "meowplayer" / "library.sqlite3"


def catalog_path():
    return _xdg_data_home() / "meowplayer" / "library.sqlite3"


class LibraryCatalog:
    """Persistent library database and metadata cache for MeowPlayer."""

    def __init__(self, music_dir, path=None):
        self.music_dir = Path(music_dir).expanduser().resolve()
        self.path = Path(path).expanduser() if path else catalog_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if path is None:
            self._migrate_legacy_cache()

        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row

        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self._ensure_schema()

    def _migrate_legacy_cache(self):
        legacy = _legacy_catalog_path()
        if self.path.exists() or not legacy.exists():
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(self.path))

        for suffix in ("-wal", "-shm"):
            legacy_sidecar = Path(str(legacy) + suffix)
            if legacy_sidecar.exists():
                shutil.move(
                    str(legacy_sidecar),
                    str(Path(str(self.path) + suffix)),
                )

    def _ensure_schema(self):
        version = self.connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        if version not in (0, 1, SCHEMA_VERSION):
            raise RuntimeError(
                f"Unsupported Cat Catalog schema version {version}; "
                f"expected <= {SCHEMA_VERSION}."
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
                last_scanned_ns INTEGER NOT NULL,
                favorite INTEGER NOT NULL DEFAULT 0,
                play_count INTEGER NOT NULL DEFAULT 0,
                last_played_ns INTEGER,
                added_at_ns INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(tracks)"
            ).fetchall()
        }
        migrations = (
            (
                "favorite",
                "ALTER TABLE tracks ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "play_count",
                "ALTER TABLE tracks ADD COLUMN play_count INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "last_played_ns",
                "ALTER TABLE tracks ADD COLUMN last_played_ns INTEGER",
            ),
            (
                "added_at_ns",
                "ALTER TABLE tracks ADD COLUMN added_at_ns INTEGER NOT NULL DEFAULT 0",
            ),
        )
        for name, statement in migrations:
            if name not in columns:
                self.connection.execute(statement)

        # Existing v1 rows get a sensible migration timestamp. New rows receive
        # their actual insertion timestamp in put().
        self.connection.execute(
            """
            UPDATE tracks
            SET added_at_ns = ?
            WHERE added_at_ns = 0
            """,
            (time.time_ns(),),
        )

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS listening_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                root TEXT NOT NULL,
                played_at_ns INTEGER NOT NULL
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
            """
            CREATE INDEX IF NOT EXISTS idx_tracks_root_favorite
            ON tracks(root, favorite)
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_history_root_played
            ON listening_history(root, played_at_ns DESC)
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
                last_scanned_ns,
                added_at_ns
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                time.time_ns(),
            ),
        )

    def invalidate_root(self):
        cursor = self.connection.execute(
            """
            UPDATE tracks
            SET size = -1, mtime_ns = -1
            WHERE root = ?
            """,
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

    def favorite_paths(self):
        rows = self.connection.execute(
            """
            SELECT path
            FROM tracks
            WHERE root = ? AND favorite = 1
            """,
            (str(self.music_dir),),
        ).fetchall()
        return {row["path"] for row in rows}

    def is_favorite(self, path):
        row = self.connection.execute(
            """
            SELECT favorite
            FROM tracks
            WHERE path = ? AND root = ?
            """,
            (str(Path(path).resolve()), str(self.music_dir)),
        ).fetchone()
        return bool(row["favorite"]) if row is not None else False

    def toggle_favorite(self, path):
        resolved = str(Path(path).resolve())
        row = self.connection.execute(
            """
            SELECT favorite
            FROM tracks
            WHERE path = ? AND root = ?
            """,
            (resolved, str(self.music_dir)),
        ).fetchone()
        if row is None:
            return False

        favorite = not bool(row["favorite"])
        self.connection.execute(
            """
            UPDATE tracks
            SET favorite = ?
            WHERE path = ? AND root = ?
            """,
            (int(favorite), resolved, str(self.music_dir)),
        )
        self.connection.commit()
        return favorite

    def record_play(self, path, played_at_ns=None):
        resolved = str(Path(path).resolve())
        played_at_ns = int(played_at_ns or time.time_ns())

        cursor = self.connection.execute(
            """
            UPDATE tracks
            SET play_count = play_count + 1,
                last_played_ns = ?
            WHERE path = ? AND root = ?
            """,
            (played_at_ns, resolved, str(self.music_dir)),
        )
        if cursor.rowcount <= 0:
            return False

        self.connection.execute(
            """
            INSERT INTO listening_history(path, root, played_at_ns)
            VALUES (?, ?, ?)
            """,
            (resolved, str(self.music_dir), played_at_ns),
        )
        self.connection.commit()
        return True

    def play_stats(self):
        rows = self.connection.execute(
            """
            SELECT path, favorite, play_count, last_played_ns, added_at_ns
            FROM tracks
            WHERE root = ?
            """,
            (str(self.music_dir),),
        ).fetchall()
        return {
            row["path"]: {
                "favorite": bool(row["favorite"]),
                "play_count": int(row["play_count"]),
                "last_played_ns": row["last_played_ns"],
                "added_at_ns": int(row["added_at_ns"]),
            }
            for row in rows
        }

    def recent_history(self, limit=100):
        rows = self.connection.execute(
            """
            SELECT path, played_at_ns
            FROM listening_history
            WHERE root = ?
            ORDER BY played_at_ns DESC
            LIMIT ?
            """,
            (str(self.music_dir), int(limit)),
        ).fetchall()
        return [
            {
                "path": row["path"],
                "played_at_ns": int(row["played_at_ns"]),
            }
            for row in rows
        ]

    def clear_root(self):
        """Compatibility helper: remove only cached track rows for this root."""
        cursor = self.connection.execute(
            "DELETE FROM tracks WHERE root = ?",
            (str(self.music_dir),),
        )
        return max(0, int(cursor.rowcount))

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
