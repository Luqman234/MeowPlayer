"""Pure presentation-layer cat state for MeowPlayer.

The Cat Presence engine observes player state and returns mascot/caption data.
It intentionally has no playback controls and performs no I/O so the mascot
can become more expressive without becoming authoritative over audio state.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CatPresenceSnapshot:
    active: bool = False
    paused: bool = False
    volume: int = 70
    shuffle: bool = False
    repeat: bool = False
    stash_count: int = 0
    crossfade_active: bool = False
    online: bool = False
    online_state: str = "idle"
    rating: int = 0
    visualizer_visible: bool = False
    scritches: int = 0


class CatPresence:
    """Turn a read-only playback snapshot into cat presentation."""

    FRAME_SECONDS = 0.45

    _FRAMES = {
        "Waiting": (
            (
                " /\\_/\\",
                r"( -.- )",
                r" > ^ <  zZ",
            ),
            (
                " /\\_/\\",
                r"( -.- )",
                r" > ^ <   zZz",
            ),
        ),
        "Purring": (
            (
                " /\\_/\\",
                r"( ^.^ )",
                r" > ♫ <   ~",
            ),
            (
                " /\\_/\\",
                r"( ^.^ )",
                r" > ♫ <  ∿",
            ),
        ),
        "Loafing": (
            (
                " /\\_/\\",
                r"( -.- )",
                r" >___<  loaf",
            ),
            (
                " /\\_/\\",
                r"( -.- )",
                r" >___<   ...",
            ),
        ),
        "Zoomies": (
            (
                " /\\_/\\     →",
                r"( >.< )  !!",
                r" > ~ <",
            ),
            (
                "      /\\_/\\",
                r"  !! ( >.< )",
                r"     > ~ <  ←",
            ),
        ),
        "Tail-Chasing": (
            (
                " /\\_/\\",
                r"( @.@ )",
                r" > ↻ <   ⟳",
            ),
            (
                " /\\_/\\",
                r"( @.@ )",
                r" ⟲   > ↻ <",
            ),
        ),
        "Guarding Catnip": (
            (
                " /\\_/\\  [CATNIP]",
                r"( o.o )",
                r" > ~ <  mine.",
            ),
            (
                " /\\_/\\  [CATNIP]",
                r"( O.o )",
                r" > ~ <  still mine.",
            ),
        ),
        "Screaming": (
            (
                " /\\_/\\",
                r"( O.O )",
                r" > !!! <  MROW",
            ),
            (
                " /\\_/\\",
                r"( O.O )",
                r" > !!! <  MROOOOW",
            ),
        ),
        "Whispering": (
            (
                " /\\_/\\",
                r"( o.o )",
                r" > . <  pspsps",
            ),
            (
                " /\\_/\\",
                r"( o.o )",
                r" > . <   purr...",
            ),
        ),
        "DJ": (
            (
                " /\\_/\\   [DJ]",
                r"( •.• )🎧",
                r" >🎚<   A ⇆ B",
            ),
            (
                " /\\_/\\   [DJ]",
                r"( •ω• )🎧",
                r" A ⇆ B   >🎚<",
            ),
        ),
        "Hunting": (
            (
                " /\\_/\\   ?",
                r"( o.o )  ...",
                r" > ^ <  sniffing internet",
            ),
            (
                " /\\_/\\   ??",
                r"( O.o )   ...",
                r" > ^ <  chasing packets",
            ),
        ),
        "Headphones": (
            (
                " /\\_/\\",
                r"( ^.^ )🎧",
                r" > ♫ <  online",
            ),
            (
                " /\\_/\\",
                r"( ^o^ )🎧",
                r" > ♫ <  streaming",
            ),
        ),
        "Empty-Pawed": (
            (
                " /\\_/\\   ?",
                r"( ._. )",
                r" > ^ <  no stream",
            ),
            (
                " /\\_/\\   ...",
                r"( ;_; )",
                r" > ^ <  empty paws",
            ),
        ),
        "Dancing": (
            (
                " /\\_/\\  ▁▃▆",
                r"( ^.^ )",
                r"  >♫<  ♪",
            ),
            (
                " ▁▃▆  /\\_/\\",
                r"     ( ^.^ )",
                r" ♪   >♫<",
            ),
        ),
        "Judging": (
            (
                " /\\_/\\",
                r"( -_- )",
                r" > 1★ <  ...",
            ),
            (
                " /\\_/\\",
                r"( ಠ_ಠ )",
                r" > 1★ <  explain.",
            ),
        ),
        "Adoring": (
            (
                " /\\_/\\   ★★★★★",
                r"( ^‿^ )",
                r" > ♥ <",
            ),
            (
                " /\\_/\\   ★★★★★",
                r"( ^.^ )",
                r" > ♥ <  approved.",
            ),
        ),
    }

    _CAPTIONS = {
        "Waiting": "The cat has become an idle daemon with fur.",
        "Purring": "Playback is stable. The cat is taking full credit.",
        "Loafing": "Paused. The cat has compressed itself into loaf format.",
        "Zoomies": "Shuffle enabled. Predictive cat routing has been abandoned.",
        "Tail-Chasing": "Repeat enabled. The cat has discovered recursion.",
        "Guarding Catnip": "The Catnip Stash is under unnecessarily strict security.",
        "Screaming": "The Meow Level has exceeded indoor-cat regulations.",
        "Whispering": "Tiny purr mode. Please approach the waveform quietly.",
        "DJ": "Two decks, four paws, zero formal DJ qualifications.",
        "Hunting": "The Internet Cat is following a suspicious packet trail.",
        "Headphones": "The Internet Cat has put on headphones and ignored local files.",
        "Empty-Pawed": "The Internet Cat came back carrying absolutely nothing.",
        "Dancing": "The spectrum has been classified as prey.",
        "Judging": "One star detected. The cat would like the track to explain itself.",
        "Adoring": "Five stars detected. The cat has declared this legally excellent.",
    }

    @staticmethod
    def mood(snapshot):
        """Return one deterministic presentation state for a snapshot."""
        if snapshot.crossfade_active:
            return "DJ"

        if snapshot.online and snapshot.online_state in {"resolving", "loading"}:
            return "Hunting"
        if snapshot.online and snapshot.online_state == "failed":
            return "Empty-Pawed"
        if snapshot.online:
            return "Headphones"

        if not snapshot.active:
            return "Waiting"
        if snapshot.paused:
            return "Loafing"
        if snapshot.volume >= 90:
            return "Screaming"
        if snapshot.volume <= 10:
            return "Whispering"
        if snapshot.repeat:
            return "Tail-Chasing"
        if snapshot.shuffle:
            return "Zoomies"
        if snapshot.stash_count:
            return "Guarding Catnip"
        if snapshot.visualizer_visible:
            return "Dancing"
        if snapshot.rating == 1:
            return "Judging"
        if snapshot.rating == 5:
            return "Adoring"
        return "Purring"

    @classmethod
    def frame(cls, snapshot, now=0.0, maximum_meow=False):
        mood = cls.mood(snapshot)
        frames = cls._FRAMES[mood]
        phase = int(max(0.0, float(now)) / cls.FRAME_SECONDS) % len(frames)
        frame = frames[phase]

        if not maximum_meow:
            return frame

        # Maximum Meow keeps the same state semantics but turns the garnish up.
        first, second, third = frame
        return (
            f"{first}   ♪",
            f"{second}   ♫",
            f"{third}   ♪",
        )

    @classmethod
    def caption(cls, snapshot):
        mood = cls.mood(snapshot)
        caption = cls._CAPTIONS[mood]
        if snapshot.scritches and mood not in {"DJ", "Hunting"}:
            caption += f" Scritches logged: {snapshot.scritches}."
        return caption
