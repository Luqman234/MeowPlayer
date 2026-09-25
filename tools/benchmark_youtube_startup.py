#!/usr/bin/env python3
"""Opt-in live benchmark; never modifies the library or saves media."""
import argparse
import json
import math
from pathlib import Path
import queue
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from meowplayer import MPVController, MeowPlayer
from youtube_online import YouTubeCatalog, YouTubeSearchSession, YouTubeStreamResolver, YouTubeTrack


def summary(values):
    values = sorted(values)
    return {"median_ms": statistics.median(values),
            "p95_ms": values[max(0, math.ceil(len(values) * .95) - 1)],
            "samples_ms": values} if values else None


def player_for(mpv, resolver):
    player = MeowPlayer.__new__(MeowPlayer)
    player.mpv = mpv
    player.stream_resolver = resolver
    player.online_current = None
    player.online_load_state = "idle"
    player.online_load_started_at = 0
    player.sync_mpris = lambda **kw: None
    player.set_status = lambda *args: None
    return player


def measure_play(player, track, timeout):
    player.online_current = None
    started = time.monotonic()  # before the same entry point the TUI uses
    player.play_online(track)
    while time.monotonic() - started < timeout:
        player.refresh_online_playback_state()
        if player.online_load_state == "streaming":
            return (player._online_playback_started_at - started) * 1000
        if player.online_load_state == "failed":
            raise RuntimeError("Playback failed")
        time.sleep(.01)
    raise TimeoutError("Playback did not start")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--query")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--candidates", action="store_true", help="also compare full JSON and -g extraction")
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    if not args.url and not args.query:
        parser.error("supply URL or --query")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.runs < 1:
        parser.error("--runs must be positive")
    catalog = YouTubeCatalog(enabled=True, timeout=args.timeout)
    report = {"runs": args.runs, "playback_evidence": "file-loaded + playback-restart + nonzero time-pos",
              "audio_output": "mpv default (not an acoustic measurement)", "errors": []}
    if args.query:
        start = time.monotonic()
        session = YouTubeSearchSession(catalog, args.query)
        tracks = []
        try:
            while True:
                kind, value = session.results.get(timeout=args.timeout + 2)
                if kind == "track":
                    if not tracks:
                        report["search_first_result_ms"] = (time.monotonic() - start) * 1000
                    tracks.append(value)
                elif kind == "error":
                    raise RuntimeError(value)
                else:
                    break
            report["search_complete_ms"] = (time.monotonic() - start) * 1000
        finally:
            session.close()
        if not tracks:
            raise RuntimeError("No search results")
        track = tracks[0]
    else:
        track = YouTubeTrack("benchmark", "Benchmark", "YouTube", 0, args.url)
    if args.candidates:
        for label, flags in [("full_json", ["--dump-single-json"]), ("get_url", ["-g"]),
                             ("selected_json", ["--print", "%(.{url,http_headers,format_id})j"])]:
            samples = []
            for _ in range(args.runs):
                start = time.monotonic()
                try:
                    result = subprocess.run([catalog.executable, "--ignore-config", "--no-playlist",
                                             "--no-warnings", "-f", "bestaudio/best", *flags, track.url],
                                            capture_output=True, timeout=args.timeout)
                    if result.returncode:
                        raise RuntimeError("extractor failed")
                    samples.append((time.monotonic() - start) * 1000)
                except Exception as exc:
                    report["errors"].append(f"{label}: {type(exc).__name__}")
            report[label] = summary(samples)
    resolver = YouTubeStreamResolver(catalog.executable, timeout=args.timeout)
    mpv = MPVController()
    player = player_for(mpv, resolver)
    samples = {"cold_enter_to_playback": [], "warm_enter_to_playback": [], "resolve": [], "cache_lookup": [], "mpv_direct_open": []}
    try:
        for _ in range(args.runs):
            resolver.invalidate(track)
            try:
                samples["cold_enter_to_playback"].append(measure_play(player, track, args.timeout * 3))
                resolver.invalidate(track)
                start = time.monotonic()
                resolver.resolve(track)
                samples["resolve"].append((time.monotonic() - start) * 1000)
                start = time.monotonic()
                resolver.resolve(track)
                samples["cache_lookup"].append((time.monotonic() - start) * 1000)
                samples["warm_enter_to_playback"].append(measure_play(player, track, args.timeout * 3))
                samples["mpv_direct_open"].append((player._online_playback_started_at - player._online_load_sent) * 1000)
                if player._online_path != "cache":
                    report["errors"].append("warm sample required retry/fallback")
            except Exception as exc:
                report["errors"].append(type(exc).__name__)
        report.update({key: summary(value) for key, value in samples.items()})
        report["ipc"] = mpv.ipc_stats()
    finally:
        resolver.close()
        mpv.quit()
    print(json.dumps(report, indent=2) if args.json else "\n".join(f"{key}: {value}" for key, value in report.items()))
    return bool(report["errors"])


if __name__ == "__main__":
    sys.exit(main())
