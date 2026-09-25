from dataclasses import dataclass


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    cat_label: str
    kind: str
    default: object
    choices: tuple = ()
    step: float = 1.0
    minimum: float | None = None
    maximum: float | None = None
    live: bool = True
    description: str = ""


SETTINGS_SPECS = (
    SettingSpec(
        "restore_session",
        "Restore session",
        "Remember yesterday's nap",
        "bool",
        True,
        live=False,
        description="Restore the last queue, track, position, and playback state.",
    ),
    SettingSpec(
        "mpris_enabled",
        "MPRIS / media keys",
        "Desktop cat privileges",
        "bool",
        True,
        live=False,
        description="Expose MeowPlayer to playerctl and desktop media keys.",
    ),
    SettingSpec(
        "album_art_enabled",
        "Album art",
        "Terminal rectangle pictures",
        "bool",
        True,
        description="Render album artwork when the terminal supports it.",
    ),
    SettingSpec(
        "gapless_mode",
        "Gapless playback",
        "No awkward silence between zoomies",
        "choice",
        "weak",
        choices=("no", "weak", "yes"),
        description="mpv gapless-audio mode: no, weak, or yes.",
    ),
    SettingSpec(
        "replaygain_mode",
        "ReplayGain",
        "Volume diplomacy",
        "choice",
        "track",
        choices=("no", "track", "album"),
        description="ReplayGain policy for tracks that contain gain metadata.",
    ),
    SettingSpec(
        "replaygain_preamp",
        "ReplayGain preamp",
        "Extra loudness seasoning",
        "float",
        0.0,
        step=0.5,
        minimum=-20.0,
        maximum=20.0,
        description="Additional ReplayGain preamp in dB.",
    ),
    SettingSpec(
        "lyrics_enabled",
        "Lyrics",
        "Songbook",
        "bool",
        True,
        description="Enable sidecar, embedded, cached, and online lyrics.",
    ),
    SettingSpec(
        "lyrics_online_enabled",
        "Online lyrics",
        "Internet lyric cats",
        "bool",
        True,
        description="Allow automatic online lyric lookup.",
    ),
    SettingSpec(
        "online_metadata_enabled",
        "MusicBrainz metadata",
        "Metadata detective cat",
        "bool",
        True,
        description="Fill missing local metadata from MusicBrainz.",
    ),
    SettingSpec(
        "visualizer_enabled",
        "CAVA visualizer",
        "Wiggly fence",
        "bool",
        True,
        description="Enable the optional CAVA spectrum visualizer.",
    ),
    SettingSpec(
        "filesystem_watch_enabled",
        "Filesystem watching",
        "Hear files move through walls",
        "bool",
        True,
        description="Watch the library for add/delete/move/retag events.",
    ),
)


def setting_spec(key):
    for spec in SETTINGS_SPECS:
        if spec.key == key:
            return spec
    raise KeyError(key)


def normalize_setting_value(spec, value):
    if spec.kind == "bool":
        return bool(value)

    if spec.kind == "choice":
        text = str(value).lower()
        return text if text in spec.choices else spec.default

    if spec.kind == "float":
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float(spec.default)
        if spec.minimum is not None:
            number = max(float(spec.minimum), number)
        if spec.maximum is not None:
            number = min(float(spec.maximum), number)
        return round(number, 2)

    return value


def adjust_setting_value(spec, value, direction=1):
    value = normalize_setting_value(spec, value)

    if spec.kind == "bool":
        return not value

    if spec.kind == "choice":
        index = spec.choices.index(value)
        return spec.choices[(index + (1 if direction >= 0 else -1)) % len(spec.choices)]

    if spec.kind == "float":
        return normalize_setting_value(
            spec,
            float(value) + (spec.step * (1 if direction >= 0 else -1)),
        )

    return value


def format_setting_value(spec, value):
    value = normalize_setting_value(spec, value)

    if spec.kind == "bool":
        return "ON" if value else "OFF"
    if spec.kind == "float":
        return f"{float(value):+.1f} dB"
    return str(value)
