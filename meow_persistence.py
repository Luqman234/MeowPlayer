import json
import os
from pathlib import Path


APP_NAME = "meowplayer"

DEFAULT_CONFIG = {
    "music_dir": None,
    "restore_session": True,
    "mpris_enabled": True,
}

DEFAULT_STATE = {
    "volume": 70,
    "shuffle": False,
    "repeat": False,
    "library_view": "songs",
    "current_track": None,
    "position": 0.0,
    "catnip_stash": [],
}


def _xdg_base(env_name, fallback):
    value = os.environ.get(env_name)
    if value:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
    return Path.home() / fallback


def config_path():
    return _xdg_base("XDG_CONFIG_HOME", ".config") / APP_NAME / "config.json"


def state_path():
    return _xdg_base("XDG_STATE_HOME", ".local/state") / APP_NAME / "state.json"


def _load_json(path, defaults):
    data = dict(defaults)

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return data

    if isinstance(loaded, dict):
        for key in defaults:
            if key in loaded:
                data[key] = loaded[key]

    return data


def _save_json(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return True
    except OSError:
        return False


def load_config():
    return _load_json(config_path(), DEFAULT_CONFIG)


def save_config(config):
    payload = dict(DEFAULT_CONFIG)
    payload.update({
        key: config.get(key, DEFAULT_CONFIG[key])
        for key in DEFAULT_CONFIG
    })
    return _save_json(config_path(), payload)


def load_state():
    return _load_json(state_path(), DEFAULT_STATE)


def save_state(state):
    payload = dict(DEFAULT_STATE)
    payload.update({
        key: state.get(key, DEFAULT_STATE[key])
        for key in DEFAULT_STATE
    })
    return _save_json(state_path(), payload)
