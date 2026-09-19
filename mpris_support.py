import asyncio
import os
import threading
from copy import deepcopy


MPRIS_AVAILABLE = False

try:
    from dbus_next import PropertyAccess, RequestNameReply, Variant
    from dbus_next.aio import MessageBus
    from dbus_next.service import ServiceInterface, dbus_property, method, signal

    MPRIS_AVAILABLE = True
except ImportError:
    PropertyAccess = None
    RequestNameReply = None
    Variant = None
    MessageBus = None
    ServiceInterface = object


OBJECT_PATH = "/org/mpris/MediaPlayer2"
BUS_NAME = "org.mpris.MediaPlayer2.meowplayer"


def _metadata_variants(metadata):
    metadata = metadata or {}

    result = {
        "mpris:trackid": Variant(
            "o",
            metadata.get(
                "track_id",
                "/org/mpris/MediaPlayer2/TrackList/NoTrack",
            ),
        )
    }

    title = metadata.get("title")
    artist = metadata.get("artist")
    album = metadata.get("album")
    album_artist = metadata.get("album_artist")
    genre = metadata.get("genre")
    url = metadata.get("url")
    length = int(metadata.get("length_us") or 0)

    if title:
        result["xesam:title"] = Variant("s", title)
    if artist:
        result["xesam:artist"] = Variant("as", [artist])
    if album:
        result["xesam:album"] = Variant("s", album)
    if album_artist:
        result["xesam:albumArtist"] = Variant("as", [album_artist])
    if genre:
        result["xesam:genre"] = Variant("as", [genre])
    if url:
        result["xesam:url"] = Variant("s", url)
    if length > 0:
        result["mpris:length"] = Variant("x", length)

    return result


if MPRIS_AVAILABLE:
    class MediaPlayer2Interface(ServiceInterface):
        def __init__(self, bridge):
            super().__init__("org.mpris.MediaPlayer2")
            self.bridge = bridge

        @method(name="Raise")
        def raise_player(self):
            return

        @method(name="Quit")
        def quit_player(self):
            self.bridge.enqueue("quit")

        @dbus_property(
            access=PropertyAccess.READ,
            name="CanQuit",
        )
        def can_quit(self) -> "b":
            return True

        @dbus_property(
            access=PropertyAccess.READ,
            name="CanRaise",
        )
        def can_raise(self) -> "b":
            return False

        @dbus_property(
            access=PropertyAccess.READ,
            name="HasTrackList",
        )
        def has_track_list(self) -> "b":
            return False

        @dbus_property(
            access=PropertyAccess.READ,
            name="Identity",
        )
        def identity(self) -> "s":
            return "MeowPlayer"

        @dbus_property(
            access=PropertyAccess.READ,
            name="DesktopEntry",
        )
        def desktop_entry(self) -> "s":
            return ""

        @dbus_property(
            access=PropertyAccess.READ,
            name="SupportedUriSchemes",
        )
        def supported_uri_schemes(self) -> "as":
            return []

        @dbus_property(
            access=PropertyAccess.READ,
            name="SupportedMimeTypes",
        )
        def supported_mime_types(self) -> "as":
            return [
                "audio/mpeg",
                "audio/flac",
                "audio/ogg",
                "audio/opus",
                "audio/wav",
                "audio/mp4",
                "audio/aac",
                "audio/x-ms-wma",
            ]


    class PlayerInterface(ServiceInterface):
        def __init__(self, bridge):
            super().__init__("org.mpris.MediaPlayer2.Player")
            self.bridge = bridge

        @method(name="Next")
        def next_track(self):
            self.bridge.enqueue("next")

        @method(name="Previous")
        def previous_track(self):
            self.bridge.enqueue("previous")

        @method(name="Pause")
        def pause(self):
            self.bridge.enqueue("pause")

        @method(name="PlayPause")
        def play_pause(self):
            self.bridge.enqueue("play_pause")

        @method(name="Stop")
        def stop(self):
            self.bridge.enqueue("stop")

        @method(name="Play")
        def play(self):
            self.bridge.enqueue("play")

        @method(name="Seek")
        def seek(self, offset: "x"):
            self.bridge.enqueue("seek", float(offset) / 1_000_000.0)

        @method(name="SetPosition")
        def set_position(self, track_id: "o", position: "x"):
            snapshot = self.bridge.snapshot()
            metadata = snapshot.get("metadata") or {}
            if track_id != metadata.get("track_id"):
                return
            self.bridge.enqueue(
                "set_position",
                max(0.0, float(position) / 1_000_000.0),
            )

        @method(name="OpenUri")
        def open_uri(self, uri: "s"):
            # MeowPlayer intentionally controls files through its indexed
            # Music Nest instead of accepting arbitrary remote URIs.
            return

        @signal(name="Seeked")
        def seeked(self, position: "x") -> "x":
            return position

        @dbus_property(
            access=PropertyAccess.READ,
            name="PlaybackStatus",
        )
        def playback_status(self) -> "s":
            return self.bridge.snapshot().get(
                "playback_status",
                "Stopped",
            )

        @dbus_property(name="LoopStatus")
        def loop_status(self) -> "s":
            return self.bridge.snapshot().get("loop_status", "None")

        @loop_status.setter
        def loop_status(self, value: "s"):
            self.bridge.enqueue("set_repeat", value == "Track")

        @dbus_property(name="Rate")
        def rate(self) -> "d":
            return 1.0

        @rate.setter
        def rate(self, value: "d"):
            if value == 0.0:
                self.bridge.enqueue("pause")

        @dbus_property(name="Shuffle")
        def shuffle(self) -> "b":
            return bool(self.bridge.snapshot().get("shuffle", False))

        @shuffle.setter
        def shuffle(self, value: "b"):
            self.bridge.enqueue("set_shuffle", bool(value))

        @dbus_property(
            access=PropertyAccess.READ,
            name="Metadata",
        )
        def metadata(self) -> "a{sv}":
            return _metadata_variants(
                self.bridge.snapshot().get("metadata")
            )

        @dbus_property(name="Volume")
        def volume(self) -> "d":
            return float(self.bridge.snapshot().get("volume", 0.7))

        @volume.setter
        def volume(self, value: "d"):
            self.bridge.enqueue(
                "set_volume",
                max(0.0, float(value)),
            )

        @dbus_property(
            access=PropertyAccess.READ,
            name="Position",
        )
        def position(self) -> "x":
            return int(
                self.bridge.snapshot().get("position_us", 0)
            )

        @dbus_property(
            access=PropertyAccess.READ,
            name="MinimumRate",
        )
        def minimum_rate(self) -> "d":
            return 1.0

        @dbus_property(
            access=PropertyAccess.READ,
            name="MaximumRate",
        )
        def maximum_rate(self) -> "d":
            return 1.0

        @dbus_property(
            access=PropertyAccess.READ,
            name="CanGoNext",
        )
        def can_go_next(self) -> "b":
            return bool(self.bridge.snapshot().get("has_tracks", False))

        @dbus_property(
            access=PropertyAccess.READ,
            name="CanGoPrevious",
        )
        def can_go_previous(self) -> "b":
            return bool(self.bridge.snapshot().get("has_tracks", False))

        @dbus_property(
            access=PropertyAccess.READ,
            name="CanPlay",
        )
        def can_play(self) -> "b":
            return bool(self.bridge.snapshot().get("has_tracks", False))

        @dbus_property(
            access=PropertyAccess.READ,
            name="CanPause",
        )
        def can_pause(self) -> "b":
            return bool(self.bridge.snapshot().get("has_track", False))

        @dbus_property(
            access=PropertyAccess.READ,
            name="CanSeek",
        )
        def can_seek(self) -> "b":
            return bool(self.bridge.snapshot().get("has_track", False))

        @dbus_property(
            access=PropertyAccess.READ,
            name="CanControl",
        )
        def can_control(self) -> "b":
            return True


class MPRISBridge:
    def __init__(self, command_queue):
        self.command_queue = command_queue
        self._snapshot = {
            "playback_status": "Stopped",
            "loop_status": "None",
            "shuffle": False,
            "volume": 0.7,
            "position_us": 0,
            "metadata": None,
            "has_track": False,
            "has_tracks": False,
        }
        self._snapshot_lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._bus = None
        self._player_interface = None
        self._started = False
        self._error = None
        self._ready = threading.Event()

    @property
    def available(self):
        return MPRIS_AVAILABLE

    @property
    def started(self):
        return self._started

    @property
    def error(self):
        return self._error

    def enqueue(self, action, *args):
        self.command_queue.put((action, args))

    def snapshot(self):
        with self._snapshot_lock:
            return deepcopy(self._snapshot)

    def start(self, timeout=1.5):
        if not MPRIS_AVAILABLE:
            self._error = "python-dbus-next is not installed"
            return False

        self._ready.clear()
        self._error = None

        self._thread = threading.Thread(
            target=self._thread_main,
            name="MeowPlayer-MPRIS",
            daemon=True,
        )
        self._thread.start()

        # Do not claim MPRIS is active until the service has actually
        # connected to the user bus and acquired its well-known name.
        self._ready.wait(timeout)
        if not self._ready.is_set():
            self._error = "timed out while registering on the D-Bus session bus"
            return False

        return self._started

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            self._started = False
            self._ready.set()

    async def _serve(self):
        self._loop = asyncio.get_running_loop()
        self._bus = await MessageBus().connect()

        root_interface = MediaPlayer2Interface(self)
        self._player_interface = PlayerInterface(self)

        self._bus.export(OBJECT_PATH, root_interface)
        self._bus.export(OBJECT_PATH, self._player_interface)

        reply = await self._bus.request_name(BUS_NAME)

        if reply not in (
            RequestNameReply.PRIMARY_OWNER,
            RequestNameReply.ALREADY_OWNER,
        ):
            self._error = (
                f"could not own {BUS_NAME}: "
                f"{getattr(reply, 'name', str(reply))}"
            )
            self._started = False
            self._ready.set()
            self._bus.disconnect()
            return

        self._started = True
        self._ready.set()

        await self._bus.wait_for_disconnect()
        self._started = False

    def update(self, snapshot):
        changed = {}

        with self._snapshot_lock:
            old = self._snapshot
            new = dict(old)
            new.update(snapshot)

            for key in (
                "playback_status",
                "loop_status",
                "shuffle",
                "volume",
                "metadata",
                "has_track",
                "has_tracks",
            ):
                if old.get(key) != new.get(key):
                    changed[key] = new.get(key)

            self._snapshot = new

        if not changed or not self._loop or not self._player_interface:
            return

        def emit_changes():
            properties = {}

            mapping = {
                "playback_status": "PlaybackStatus",
                "loop_status": "LoopStatus",
                "shuffle": "Shuffle",
                "volume": "Volume",
            }

            for key, property_name in mapping.items():
                if key in changed:
                    properties[property_name] = changed[key]

            if "metadata" in changed:
                properties["Metadata"] = _metadata_variants(
                    changed["metadata"]
                )

            if properties:
                self._player_interface.emit_properties_changed(
                    properties
                )

        self._loop.call_soon_threadsafe(emit_changes)

    def notify_seeked(self, position_us):
        if not self._loop or not self._player_interface:
            return

        self._loop.call_soon_threadsafe(
            self._player_interface.seeked,
            int(position_us),
        )

    def stop(self):
        if self._loop and self._bus:
            self._loop.call_soon_threadsafe(self._bus.disconnect)
