import base64
import hashlib
import io
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

try:
    from mutagen.flac import Picture
except ImportError:
    Picture = None


COVER_FILENAMES = (
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "cover.webp",
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "folder.webp",
    "front.jpg",
    "front.jpeg",
    "front.png",
    "front.webp",
    "album.jpg",
    "album.jpeg",
    "album.png",
    "album.webp",
)


def _xdg_cache_home():
    value = os.environ.get("XDG_CACHE_HOME")
    if value:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
    return Path.home() / ".cache"


def _cache_dir():
    return _xdg_cache_home() / "meowplayer" / "album-art"


def _is_kitty_terminal():
    term = os.environ.get("TERM", "")
    return bool(
        os.environ.get("KITTY_WINDOW_ID")
        or term == "xterm-kitty"
        or term.endswith("-kitty")
    )


def _mime_extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "webp"
    return "img"


class AlbumArtManager:
    """Resolve/caches album artwork and render it via Kitty graphics."""

    IMAGE_ID = 904210

    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self.supported = bool(
            self.enabled
            and Image is not None
            and MutagenFile is not None
            and _is_kitty_terminal()
            and not os.environ.get("TMUX")
            and sys.stdout.isatty()
        )
        self.cache_dir = _cache_dir()
        self._resolved = {}
        self._transmitted = None

    def _cache_key(self, path, suffix):
        try:
            stat_result = path.stat()
            fingerprint = (
                f"{path.resolve()}:{stat_result.st_size}:"
                f"{stat_result.st_mtime_ns}:{suffix}"
            )
        except OSError:
            fingerprint = f"{path}:{suffix}"

        return hashlib.sha256(
            fingerprint.encode("utf-8", errors="surrogateescape")
        ).hexdigest()

    def _png_from_image(self, image, key):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        output = self.cache_dir / f"{key}.png"
        if output.exists():
            return output

        image = image.convert("RGBA")
        image.thumbnail((1024, 1024))
        temporary = output.with_suffix(".tmp.png")
        image.save(temporary, format="PNG", optimize=True)
        temporary.replace(output)
        return output

    def _png_from_bytes(self, data, key):
        if not data or Image is None:
            return None

        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return self._png_from_image(image, key)
        except Exception:
            return None

    def _embedded_bytes(self, track_path):
        if MutagenFile is None:
            return None

        try:
            audio = MutagenFile(track_path)
        except Exception:
            return None

        if audio is None:
            return None

        pictures = getattr(audio, "pictures", None)
        if pictures:
            data = getattr(pictures[0], "data", None)
            if data:
                return bytes(data)

        tags = getattr(audio, "tags", None)
        if tags is None:
            return None

        getall = getattr(tags, "getall", None)
        if callable(getall):
            try:
                apic = getall("APIC")
            except Exception:
                apic = []
            if apic:
                data = getattr(apic[0], "data", None)
                if data:
                    return bytes(data)

        try:
            covers = tags.get("covr")
        except Exception:
            covers = None
        if covers:
            try:
                return bytes(covers[0])
            except Exception:
                pass

        try:
            picture_values = tags.get("metadata_block_picture")
        except Exception:
            picture_values = None

        if picture_values and Picture is not None:
            if not isinstance(picture_values, (list, tuple)):
                picture_values = [picture_values]

            for value in picture_values:
                try:
                    raw = base64.b64decode(str(value))
                    picture = Picture(raw)
                    if picture.data:
                        return bytes(picture.data)
                except Exception:
                    continue

        return None

    def _folder_cover(self, track_path):
        try:
            files = {
                child.name.casefold(): child
                for child in track_path.parent.iterdir()
                if child.is_file()
            }
        except OSError:
            return None

        for name in COVER_FILENAMES:
            cover = files.get(name.casefold())
            if cover is not None:
                return cover

        return None

    def cover_for(self, track_path):
        track_path = Path(track_path).expanduser()

        try:
            cache_identity = (
                str(track_path.resolve()),
                track_path.stat().st_mtime_ns,
            )
        except OSError:
            return None

        if cache_identity in self._resolved:
            return self._resolved[cache_identity]

        embedded_key = self._cache_key(track_path, "embedded-cover")
        embedded_output = self.cache_dir / f"{embedded_key}.png"

        if embedded_output.exists():
            self._resolved[cache_identity] = embedded_output
            return embedded_output

        data = self._embedded_bytes(track_path)
        if data:
            output = self._png_from_bytes(data, embedded_key)
            if output is not None:
                self._resolved[cache_identity] = output
                return output

        folder_cover = self._folder_cover(track_path)
        if folder_cover is not None:
            key = self._cache_key(folder_cover, "folder-cover")
            output = self.cache_dir / f"{key}.png"

            if not output.exists():
                try:
                    with Image.open(folder_cover) as image:
                        image.load()
                        output = self._png_from_image(image, key)
                except Exception:
                    output = None

            if output is not None and output.exists():
                self._resolved[cache_identity] = output
                return output

        self._resolved[cache_identity] = None
        return None

    def _write(self, value):
        try:
            os.write(sys.stdout.fileno(), value.encode("ascii"))
        except (OSError, ValueError):
            pass

    def clear(self, free_data=True):
        if not self.supported:
            return

        delete_mode = "I" if free_data else "i"
        self._write(
            f"\x1b_Ga=d,d={delete_mode},i={self.IMAGE_ID},q=2\x1b\\"
        )
        if free_data:
            self._transmitted = None

    def _transmit(self, image_path):
        encoded = base64.standard_b64encode(
            os.fsencode(str(image_path.resolve()))
        ).decode("ascii")

        self.clear(free_data=True)
        self._write(
            "\x1b_G"
            f"a=t,t=f,f=100,i={self.IMAGE_ID},q=2,N=1;"
            f"{encoded}"
            "\x1b\\"
        )
        self._transmitted = str(image_path.resolve())

    def render(self, image_path, row, column, columns, rows):
        if not self.supported or image_path is None:
            self.clear(free_data=False)
            return

        image_path = Path(image_path)
        identity = str(image_path.resolve())
        if identity != self._transmitted:
            self._transmit(image_path)

        row = max(0, int(row))
        column = max(0, int(column))
        columns = max(1, int(columns))
        rows = max(1, int(rows))

        self._write(
            "\x1b7"
            f"\x1b[{row + 1};{column + 1}H"
            "\x1b_G"
            f"a=p,i={self.IMAGE_ID},q=2,c={columns},r={rows},C=1;"
            "\x1b\\"
            "\x1b8"
        )
