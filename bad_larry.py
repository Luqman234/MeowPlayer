import random
import time
from dataclasses import dataclass

from bad_larry_math import (
    MATH_EVENT_CHANCE,
    MATH_ROLL_INTERVAL,
    answer_is_correct,
    generate_math_question,
    skip_penalty,
)


DANGEROUS_SUMMON_PHRASE = "Yes! Summon Bad Larry into The Room!"
DANGEROUS_DISMISS_PHRASE = "YES, I APOLOGIZE FOR DISTURBING BAD LARRY"


@dataclass(frozen=True)
class ChaosProfile:
    label: str
    min_cooldown: float
    max_cooldown: float
    retaliation_chance: float
    rewind_min: float
    rewind_max: float
    pause_min: float
    pause_max: float
    speed_choices: tuple
    volume_drop_min: int
    volume_drop_max: int
    allow_random_track: bool
    allow_chain: bool


CHAOS_PROFILES = {
    "bad-bad": ChaosProfile(
        label="BAD BAD CAT",
        min_cooldown=60.0,
        max_cooldown=160.0,
        retaliation_chance=0.10,
        rewind_min=2.0,
        rewind_max=5.0,
        pause_min=0.4,
        pause_max=1.0,
        speed_choices=(0.98, 1.02),
        volume_drop_min=1,
        volume_drop_max=3,
        allow_random_track=False,
        allow_chain=False,
    ),
    "very-bad": ChaosProfile(
        label="VERY BAD CAT",
        min_cooldown=24.0,
        max_cooldown=75.0,
        retaliation_chance=0.28,
        rewind_min=5.0,
        rewind_max=20.0,
        pause_min=1.0,
        pause_max=3.0,
        speed_choices=(0.92, 0.96, 1.04, 1.08),
        volume_drop_min=3,
        volume_drop_max=8,
        allow_random_track=True,
        allow_chain=False,
    ),
    "dangerous": ChaosProfile(
        label="BAD LARRY",
        min_cooldown=8.0,
        max_cooldown=35.0,
        retaliation_chance=0.58,
        rewind_min=10.0,
        rewind_max=45.0,
        pause_min=1.0,
        pause_max=6.0,
        speed_choices=(0.80, 0.86, 0.92, 1.08, 1.14, 1.20),
        volume_drop_min=5,
        volume_drop_max=14,
        allow_random_track=True,
        allow_chain=True,
    ),
}


ACTION_MALICE = {
    "next": 12,
    "previous": 8,
    "pause": 8,
    "seek_forward": 6,
    "seek_backward": 3,
    "volume_up": 4,
    "volume_down": 4,
    "quit": 20,
}


def confirm_dangerous_cat(input_func=input, output_func=print):
    output_func("")
    output_func("DANGEROUS CAT MODE")
    output_func("")
    output_func("Bad Larry will heavily interfere with playback.")
    output_func(
        "He may pause, resume, seek, replay, skip, alter tempo, "
        "and fight your playback controls."
    )
    output_func("Your music files and ratings will not be modified.")
    output_func("")

    first = input_func("Continue? [y/N] ").strip().casefold()
    if first not in {"y", "yes"}:
        output_func("Bad Larry remains outside.")
        return False

    output_func("")
    output_func("Are you absolutely sure?")
    output_func("Bad Larry does not respect your queue, skips, or authority.")
    second = input_func("Continue? [y/N] ").strip().casefold()
    if second not in {"y", "yes"}:
        output_func("Bad Larry remains outside.")
        return False

    output_func("")
    output_func("FINAL CONFIRMATION")
    output_func("")
    output_func("Type exactly:")
    output_func(DANGEROUS_SUMMON_PHRASE)
    output_func("")
    third = input_func("> ")
    if third != DANGEROUS_SUMMON_PHRASE:
        output_func("Bad Larry remains outside. Probably for the best.")
        return False

    output_func("")
    output_func("BAD LARRY HAS ENTERED THE ROOM.")
    output_func("Playback authority: CONTESTED")
    output_func("")
    return True


def apology_matches(value):
    return str(value) == DANGEROUS_DISMISS_PHRASE


class PlaybackSaboteur:
    """Opt-in playback interference for MeowPlayer's malicious cat modes.

    It may alter playback, but never writes user music, ratings, playlists,
    shell configuration, or other system data.
    """

    def __init__(self, mode=None, rng=None, now_func=None):
        self.mode = mode if mode in CHAOS_PROFILES else None
        self.rng = rng or random
        self.now_func = now_func or time.monotonic
        self.malice = 0
        self.sabotage_count = 0
        self.skips_denied = 0
        self.pending = []
        self.forced_pause = False
        self.pending_math_question = None
        self.math_surrenders = 0
        self.math_correct = 0
        self.next_event_at = float("inf")
        now = self.now_func()
        self.next_math_roll_at = (
            now + MATH_ROLL_INTERVAL
            if self.mode == "dangerous"
            else float("inf")
        )
        if self.mode:
            self._schedule_next(now)

    @property
    def enabled(self):
        return self.mode in CHAOS_PROFILES

    @property
    def profile(self):
        return CHAOS_PROFILES.get(self.mode)

    @property
    def label(self):
        return self.profile.label if self.profile else "NORMAL CAT"

    @property
    def human_authority(self):
        return max(0, 100 - int(self.malice))

    def _schedule_next(self, now):
        if not self.enabled:
            self.next_event_at = float("inf")
            return
        profile = self.profile
        aggression = 1.0 - (min(100, self.malice) / 100.0) * 0.35
        delay = self.rng.uniform(
            profile.min_cooldown,
            profile.max_cooldown,
        ) * aggression
        self.next_event_at = now + max(profile.min_cooldown * 0.6, delay)

    def _schedule(self, when, action, value=None):
        self.pending.append((float(when), action, value))
        self.pending.sort(key=lambda item: item[0])

    def _status(self, player, message):
        if hasattr(player, "set_status"):
            player.set_status(message, message)
        else:
            player.status_message = message

    def _bump(self, amount):
        self.malice = max(0, min(100, int(self.malice + amount)))

    def note_user_action(self, action):
        self._bump(ACTION_MALICE.get(action, 2))

    def dismiss(self, player):
        self.pending.clear()
        if self.forced_pause:
            try:
                player.mpv.play()
            except Exception:
                pass
        self.forced_pause = False
        try:
            player.mpv.set_property("speed", 1.0)
            player.mpv.set_property("volume", player.volume)
        except Exception:
            pass
        self.mode = None
        self.malice = 0
        self.pending_math_question = None
        self.next_event_at = float("inf")
        self.next_math_roll_at = float("inf")

    def _temporary_pause(self, player, now):
        if getattr(player, "current", None) is None:
            return False
        try:
            if bool(player.mpv.get_property("pause")):
                return False
            player.mpv.pause()
        except Exception:
            return False
        self.forced_pause = True
        duration = self.rng.uniform(
            self.profile.pause_min,
            self.profile.pause_max,
        )
        self._schedule(now + duration, "resume")
        self._status(
            player,
            f"{self.label}: silence was becoming suspicious.",
        )
        return True

    def _tempo_crime(self, player, now):
        if getattr(player, "current", None) is None:
            return False
        speed = self.rng.choice(self.profile.speed_choices)
        try:
            player.mpv.set_property("speed", speed)
        except Exception:
            return False
        duration = self.rng.uniform(4.0, 11.0)
        self._schedule(now + duration, "speed", 1.0)
        self._status(
            player,
            f"{self.label}: tempo crime committed at {speed:.2f}x.",
        )
        return True

    def _volume_theft(self, player, now):
        if getattr(player, "current", None) is None:
            return False
        drop = self.rng.randint(
            self.profile.volume_drop_min,
            self.profile.volume_drop_max,
        )
        target = max(0, int(player.volume) - drop)
        try:
            player.mpv.set_property("volume", target)
        except Exception:
            return False
        self._schedule(
            now + self.rng.uniform(4.0, 9.0),
            "volume",
            int(player.volume),
        )
        self._status(
            player,
            f"{self.label}: borrowed {drop}% of your volume.",
        )
        return True

    def _rewind(self, player, stronger=False):
        if getattr(player, "current", None) is None:
            return False
        low = self.profile.rewind_min
        high = self.profile.rewind_max * (1.25 if stronger else 1.0)
        amount = self.rng.uniform(low, high)
        try:
            player.mpv.seek(-amount)
        except Exception:
            return False
        self._status(
            player,
            f"{self.label}: rewind {amount:.0f}s. Listen properly.",
        )
        return True

    def _fast_forward(self, player):
        if getattr(player, "current", None) is None:
            return False
        amount = self.rng.uniform(
            max(2.0, self.profile.rewind_min * 0.5),
            max(5.0, self.profile.rewind_max * 0.7),
        )
        try:
            player.mpv.seek(amount)
        except Exception:
            return False
        self._status(
            player,
            f"{self.label}: skipped {amount:.0f}s because that bit was boring.",
        )
        return True

    def _restart_current(self, player):
        if getattr(player, "current", None) is None:
            return False
        try:
            player.mpv.seek_absolute(0.0)
        except Exception:
            return False
        self._status(player, f"{self.label}: again.")
        return True

    def _random_track(self, player):
        songs = getattr(player, "songs", ())
        current = getattr(player, "current", None)
        if not songs or len(songs) < 2 or current is None:
            return False
        candidates = [i for i in range(len(songs)) if i != current]
        target = self.rng.choice(candidates)
        player.play(
            target,
            record_history=False,
            record_listen=False,
            preserve_sequence=True,
        )
        self._status(player, f"{self.label}: I chose the next song.")
        return True

    def _double_skip(self, player):
        songs = getattr(player, "songs", ())
        current = getattr(player, "current", None)
        if not songs or current is None or len(songs) < 2:
            return False
        target = (current + 2) % len(songs)
        player.play(
            target,
            record_history=False,
            record_listen=False,
            preserve_sequence=True,
        )
        self._status(
            player,
            "BAD LARRY: you asked for next. I chose next-next.",
        )
        return True

    def _segment_loop(self, player, now):
        if getattr(player, "current", None) is None:
            return False
        try:
            position = float(player.mpv.get_property("time-pos") or 0.0)
        except (TypeError, ValueError):
            return False
        start = max(0.0, position - self.rng.uniform(4.0, 8.0))
        self._schedule(now + 0.2, "seek_absolute", start)
        self._schedule(now + 2.2, "seek_absolute", start)
        self._schedule(now + 4.2, "seek_absolute", start)
        self._status(
            player,
            "BAD LARRY: best part. We are hearing it three times.",
        )
        return True

    def _larry_chain(self, player, now):
        if self.mode != "dangerous" or getattr(player, "current", None) is None:
            return False
        self._rewind(player, stronger=True)
        speed = self.rng.choice(self.profile.speed_choices)
        try:
            player.mpv.set_property("speed", speed)
        except Exception:
            pass
        self._schedule(now + 0.8, "pause")
        self._schedule(now + 2.0, "resume")
        self._schedule(now + 5.0, "speed", 1.0)
        if len(getattr(player, "songs", ())) > 1:
            self._schedule(now + 6.0, "random_track")
        self._status(
            player,
            f"BAD LARRY CHAIN: rewind + {speed:.2f}x + pause + surprise.",
        )
        return True

    def _execute_spontaneous(self, player, now):
        if not self.enabled or getattr(player, "current", None) is None:
            return False

        actions = ["rewind", "pause", "tempo", "volume"]
        if self.mode in {"very-bad", "dangerous"}:
            actions += ["fast_forward", "restart"]
        if self.profile.allow_random_track:
            actions.append("random_track")
        if self.mode == "dangerous":
            actions += ["segment_loop", "double_skip"]
            if self.malice >= 55:
                actions += ["larry_chain", "larry_chain"]

        action = self.rng.choice(actions)
        executed = {
            "rewind": lambda: self._rewind(player),
            "pause": lambda: self._temporary_pause(player, now),
            "tempo": lambda: self._tempo_crime(player, now),
            "volume": lambda: self._volume_theft(player, now),
            "fast_forward": lambda: self._fast_forward(player),
            "restart": lambda: self._restart_current(player),
            "random_track": lambda: self._random_track(player),
            "segment_loop": lambda: self._segment_loop(player, now),
            "double_skip": lambda: self._double_skip(player),
            "larry_chain": lambda: self._larry_chain(player, now),
        }[action]()

        if executed:
            self.sabotage_count += 1
            bump = 2 if self.mode == "bad-bad" else 4 if self.mode == "very-bad" else 7
            self._bump(bump)
        return executed

    def _run_pending(self, player, now):
        ready = []
        while self.pending and self.pending[0][0] <= now:
            ready.append(self.pending.pop(0))

        for _, action, value in ready:
            try:
                if action == "resume":
                    player.mpv.play()
                    self.forced_pause = False
                elif action == "pause":
                    player.mpv.pause()
                    self.forced_pause = True
                elif action == "speed":
                    player.mpv.set_property("speed", float(value))
                elif action == "volume":
                    player.mpv.set_property("volume", int(value))
                elif action == "seek_absolute":
                    player.mpv.seek_absolute(float(value))
                elif action == "random_track":
                    self._random_track(player)
            except Exception:
                continue

    def tick(self, player, now=None):
        if not self.enabled:
            return False

        timestamp = self.now_func() if now is None else float(now)
        self._run_pending(player, timestamp)

        if timestamp < self.next_event_at:
            return False

        executed = self._execute_spontaneous(player, timestamp)
        self._schedule_next(timestamp)
        return executed

    def handle_user_action(self, player, action, now=None):
        if not self.enabled:
            return False

        timestamp = self.now_func() if now is None else float(now)
        self.note_user_action(action)

        if action == "quit" and self.mode == "dangerous":
            self._status(
                player,
                "BAD LARRY: leaving already? Ctrl+E starts the formal dismissal ritual.",
            )
            self.sabotage_count += 1
            return True

        if self.rng.random() >= self.profile.retaliation_chance:
            return False

        if action in {"next", "previous"}:
            self.skips_denied += 1
            if self.mode == "bad-bad":
                result = self._rewind(player)
            elif self.mode == "very-bad":
                result = self.rng.choice(
                    (
                        lambda: self._rewind(player),
                        lambda: self._restart_current(player),
                    )
                )()
            else:
                result = self.rng.choice(
                    (
                        lambda: self._rewind(player, stronger=True),
                        lambda: self._restart_current(player),
                        lambda: self._double_skip(player),
                    )
                )()
            if result:
                self.sabotage_count += 1
            return bool(result)

        if action == "pause":
            result = self._temporary_pause(player, timestamp)
            if result:
                self.sabotage_count += 1
            return bool(result)

        if action == "seek_forward":
            result = self._rewind(
                player,
                stronger=self.mode == "dangerous",
            )
            if result:
                self.sabotage_count += 1
            return bool(result)

        if action == "seek_backward":
            result = self._fast_forward(player)
            if result:
                self.sabotage_count += 1
            return bool(result)

        if action in {"volume_up", "volume_down"}:
            result = self._volume_theft(player, timestamp)
            if result:
                self.sabotage_count += 1
            return bool(result)

        return False
