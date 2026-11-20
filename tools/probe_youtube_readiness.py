#!/usr/bin/env python3
"""Opt-in live probe: replay one extracted URL, without printing URLs/headers.

Private mpv traces are deleted on exit. No media files are saved. The reported
HTTP request time is FFmpeg's trace immediately before sending GET (not IPC ACK).
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from meowplayer import MPVController, build_mpv_command
from youtube_online import YouTubeTrack, network_subprocess_env, parse_stream


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--format", default="bestaudio/best")
    parser.add_argument("--client", help="optional yt-dlp youtube player_client")
    parser.add_argument("--no-config", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="meow-readiness-") as directory:
        log = Path(directory) / "mpv.log"
        def command(*a, **kw):
            return build_mpv_command(*a, **kw) + [
                "--ao=null", "--msg-level=ffmpeg=trace",
                *(["--no-config"] if args.no_config else []),
            ]
        process_started = time.monotonic()
        with mock.patch("meowplayer.build_mpv_command", side_effect=command):
            mpv = MPVController(debug_log_path=log, network_resolver_workaround=True)
        try:
            cmd = ["yt-dlp", "--ignore-config", "--no-playlist", "--no-warnings",
                   "--skip-download", "-f", args.format, "--print",
                   "%(.{url,http_headers,format_id,available_at,protocol})j"]
            if args.client:
                cmd += ["--extractor-args", f"youtube:player_client={args.client}"]
            result = subprocess.run(cmd + [args.url], capture_output=True, text=True,
                                    timeout=40, env=network_subprocess_env())
            if result.returncode:
                print(json.dumps({"error": "extraction_failed", "exit_code": result.returncode}))
                return
            data = json.loads(result.stdout)
            stream = parse_stream(YouTubeTrack("probe", "Probe", "", 0, args.url), result.stdout)
            remaining = max(0, (data.get("available_at") or 0) - time.time())
            print(json.dumps({"format_id": stream.format_id, "protocol": data.get("protocol"),
                              "client": args.client or "default", "no_config": args.no_config,
                              "availability_remaining_ms": round(remaining * 1000)}), flush=True)
            for label in ("immediate", "same_url_delayed"):
                if label == "same_url_delayed":
                    # Diagnostic control only; application never blocks this way.
                    deadline = stream.resolved_at + max(remaining + .25, 5)
                    while time.monotonic() < deadline:
                        time.sleep(max(0, min(.05, deadline - time.monotonic())))
                offset = log.stat().st_size if log.exists() else 0
                sent = time.monotonic()
                response = mpv.load_stream(stream)
                mpv.play()
                deadline = time.monotonic() + 15
                progress = False
                events = {}
                while time.monotonic() < deadline:
                    events = mpv.playback_snapshot()
                    progress = (bool(events.get("file-loaded")) and bool(events.get("playback-restart"))
                                and (mpv.get_property("time-pos") or 0) > 0
                                and not mpv.get_property("idle-active"))
                    if progress or events.get("end-reason") == "error":
                        break
                    time.sleep(.01)
                trace = log.read_bytes()[offset:].decode(errors="replace")
                request = re.search(r"\[\s*([\d.]+)\].*request: GET ", trace)
                print(json.dumps({"attempt": label, "ipc_accepted": bool(response and response.get("error") == "success"),
                                  "stream_age_at_load_ms": round((sent - stream.resolved_at) * 1000),
                                  "stream_age_at_http_get_ms": round((process_started + float(request[1]) - stream.resolved_at) * 1000) if request else None,
                                  "http_403": "403 Forbidden" in trace, "playback_progress": progress,
                                  "end_reason": events.get("end-reason"), "entry_id": events.get("entry-id")}), flush=True)
        finally:
            mpv.quit()


if __name__ == "__main__":
    main()
