# Internet Nest startup investigation

## Immediate playback HTTP 403: availability metadata (2026-10-30)

The immediate-playback failure was reproduced on `dhYOPzcsbGM` with Python
3.14.8, yt-dlp 2026.10.26, mpv 0.41.0, FFmpeg runtime 9.0.2, and Deno 2.9.8.
The selected YouTube format includes an **`available_at` Unix timestamp**.
MeowPlayer's selected-field metadata extraction discarded it. Consequently,
mpv requested the media before the extractor's availability deadline. Waiting
in the results screen let the same prefetched URL become usable. Immediate
invalidation and re-extraction could obtain another URL with a new future
deadline, repeating the failure.

This is supported by source inspection and live media requests, rather than
IPC acknowledgements alone. In the installed yt-dlp, `YoutubeIE` computes a
per-client availability timestamp from pre-content ad duration/skip metadata
and attaches it to non-live formats; its downloader honors that timestamp
before the first download. MeowPlayer uses `--skip-download`, so that downloader
wait never ran. See the upstream [YouTube extractor](https://github.com/yt-dlp/yt-dlp/blob/2026.10.26/yt_dlp/extractor/youtube/_video.py)
and [download readiness handling](https://github.com/yt-dlp/yt-dlp/blob/2026.10.26/yt_dlp/downloader/common.py).

The search worker delivers results incrementally. `process_youtube()` requests
prefetch for the selected result with a 150 ms debounce. Enter's
`play_online()` shares that same Future and removes the debounce, or consumes
the cache if extraction is complete. Online playlists request the next stream
20 seconds before the current track ends. Readiness therefore belongs to the
extracted stream, independently of whether search, selection or a playlist
initiated resolution.

Live controls, extracting once and replaying the **identical URL and headers**:

| mpv configuration / format | Remaining availability at extraction | First media GET after resolution | Immediate result | Same URL delayed GET | Delayed result |
| --- | ---: | ---: | --- | ---: | --- |
| User configuration / 251 Opus | 4,339 ms | ~61 ms | HTTP 403, end-file(error), no progress | ~5,266 ms | Playback progress |
| `--no-config` / 251 Opus | 4,296 ms | ~49 ms | HTTP 403, end-file(error), no progress | ~5,093 ms | Playback progress |
| `--no-config` / 140 AAC | 3,920 ms | ~64 ms | HTTP 403, end-file(error), no progress | ~5,089 ms | Playback progress |

GET timings come from FFmpeg's trace immediately before sending the HTTP
request, relative to stream resolution; process-start timestamp alignment is
approximate. These are media requests, not loadfile submission times. Success
requires file-loaded, playback-restart, advancing time-pos and non-idle state.
Native playlist entry IDs distinguish attempts. The failures are genuine
HTTP errors, independent of user mpv configuration in these controls.

This demonstrates a timing constraint for these samples, not a universal
YouTube delay. Both tested audio formats were affected under the default
extractor clients; other clients, accounts, live formats, regions and networks
were not exhaustively compared. `available_at` can already be in the past or
absent. The precise YouTube server-side enforcement is outside MeowPlayer's
control, and HTTP 403 can have other causes.

### Playback and recovery behavior

`resolver_command()` now retains `available_at`; `parse_stream()` converts it
once to a monotonic `ResolvedStream.ready_at` deadline. The existing 180-second
maximum cache TTL and signed expiry minus 30 seconds still apply. Invalid,
non-finite or unavailable-until-after-expiry metadata is rejected.

`_finish_online_resolve()` retains the stream and calls `_start_online_stream()`.
If the deadline is in the future, playback enters `waiting`. The normal TUI
refresh loop checks the deadline; it starts no media request before then and
does not sleep or block user input. A ready fresh/cached stream loads immediately.
Prefetching consumes the readiness interval before Enter when there is enough
lead time, without keeping the resolver worker busy while waiting.

Recovery is bounded per user selection:

1. Before loading, recheck expiry and readiness.
2. On an early open failure with no file-loaded event or playback progress,
   retry the same still-valid stream once after a one-second asynchronous
   backoff, also respecting its availability deadline. mpv's generic
   `loading failed` (or missing detail) qualifies; decoder/audio-output errors
   and startup timeouts skip this step. This is a transient-open retry, not a
   claim that every open error is HTTP 403 or that one second is a readiness rule.
3. When reuse fails or expiry prevents it, invalidate and resolve fresh once.
   The fresh stream's own availability deadline also applies.
4. Use the existing mpv watch-URL fallback once, then report failure. There are
   at most three direct loads plus one fallback, and two resolver extractions.

Actual position and playback events still determine success. A failure after
observed progress does not restart the track from zero. Normal EOF keeps the
existing playlist advancement behavior. Pausing while waiting is preserved
when the stream loads; a deliberately paused startup does not trigger the
startup timeout.

Pending state belongs to the selected provider/video. Track changes, local
playback, Stop and shutdown revoke it. There are no timer callbacks that can
restart an obsolete selection. mpv start/end ownership still uses native
playlist entry IDs across same-URL reloads and playlist transitions. An owned
end-file event now also clears the controller's pending-load flag and retains
mpv's error category for recovery decisions.

### Current performance and validation

Three patched application-entry-point runs on the reported video, normal mpv
audio output, product-default process-local DNS environment:

| Measurement | Median | Range |
| --- | ---: | ---: |
| Cold Enter to advancing playback | 7,557 ms | 6,970–8,028 ms |
| Ready prefetched Enter to advancing playback | **230 ms** | **214–232 ms** |
| Metadata extraction | 3,008 ms | 2,912–3,138 ms |
| Prefetch readiness lead time after extraction | 3,812 ms | 3,751–4,665 ms |

All three cold and three ready-prefetched runs succeeded. No fixed delay is
added to ready streams or local files. Cold streams wait only the remaining
extractor-declared availability interval; network/extraction latency remains
external. These small samples are not latency or reliability guarantees.

The benchmark now uses the application's mpv resolver environment and reports
prefetch readiness lead time separately, before timing a *ready* cache hit.
An initial patched run of the old benchmark also succeeded in all six starts,
but measured a just-resolved cache entry as warm and omitted mpv's DNS
workaround: medians were 12,358 ms cold / 9,682 ms just-cached. This is not a
matched performance comparison. Do not interpret those numbers as ready-cache
latency or attribute the difference entirely to the availability fix.

Offline fake-clock regression tests cover availability, missing/past metadata,
expiry, immediate success, same-URL reuse, exhausted recovery, cancellation,
pause/resume, privacy, entry ownership and playlist prefetch/advancement.
Opt-in real-mpv tests use a loopback server to assert the first HTTP request
occurs after declared readiness, observe real 403 failure/recovery, and verify
bounded persistent failure. They also check per-file header isolation, local
FLAC/MP3/Opus, native gapless handoff, pause, seek, Stop and ReplayGain. Unit
tests never require YouTube connectivity.

Final validation: `MEOW_REAL_MPV=1 python -m unittest discover -s tests`
passed all **368 tests** in 6.89 seconds, including the three real-mpv tests
(26 additional test methods over the 342-test baseline). A separate real
MPRIS registration/update check passed on an isolated session D-Bus.
Existing tests for NicoNico, Creator's Nest, queues, crossfade, lyrics, cache
behavior and IPC remained green; those services and interactive curses input
were not separately exercised live. The optional `web_safari` live control
failed at extraction and therefore supplied no playback timing evidence.

### Troubleshooting future failures

Enable MeowPlayer debug logging and inspect `YT_PLAY`, `YT_RETRY`, `YT_END`
and `YT_LATENCY`. Logs contain video ID, resolver path, cache hit, format ID,
stream age, attempt number, remaining wait, end reason and playback latency.
They do not include media URLs or HTTP headers. The availability wait is
identified by `wait_reason=availability`; a retry uses `resolver_path=same-url`.
`success` from loadfile only means the command was accepted.

For an opt-in live control (null audio, no saved media):

```bash
python tools/probe_youtube_readiness.py 'https://youtu.be/dhYOPzcsbGM'
python tools/probe_youtube_readiness.py 'https://youtu.be/dhYOPzcsbGM' --no-config
python tools/probe_youtube_readiness.py 'https://youtu.be/dhYOPzcsbGM' --format 140 --no-config
# Optional client comparison; availability/formats depend on extractor support:
python tools/probe_youtube_readiness.py 'https://youtu.be/dhYOPzcsbGM' --client web_safari --no-config
```

The diagnostic intentionally bypasses the application readiness gate for its
first attempt, then replays the exact same URL after the reported deadline (or
five seconds for the diagnostic control). That sleep is confined to the CLI
probe. It prints safe timings, HTTP-403 detection and actual playback evidence;
its private temporary mpv traces are deleted on exit. Trace parsing is
diagnostic only and may need adjustment with future FFmpeg log formats. A
failure that persists after readiness may involve expiry, rate limits, tokens,
headers, network conditions, or extractor changes; the timing fix does not
establish which of those applies. Redact manually retained mpv logs before
sharing because mpv itself may log signed URLs and headers.

The earlier DNS investigation below describes a separate failure mode.

Measured on 2026-09-25 with Python 3.14, mpv 0.41.0, yt-dlp
2026.08.19, Linux/glibc, and the default PipeWire audio output. The original
performance investigation was based on `95bda09` (main already included the
v0.16.2 fixes); the confirmed resolver workaround is shipped in v0.16.4.

## Baseline and resolver candidates

Same public video (`jNQXAC9IVRw`), sequential runs on the development
network, default resolver environment; one sample each:

| Path | Elapsed | stdout size |
| --- | ---: | ---: |
| Original mpv watch URL → advancing time-pos | 12,419 ms | — |
| yt-dlp `--dump-single-json` | 7,004 ms | 87,723 bytes |
| Candidate A: yt-dlp `-g` | 7,066 ms | 1,162 bytes |
| Candidate B: selected-field JSON `--print` | 6,837 ms | 1,477 bytes |
| Original flat search, 12 results, “On My Way” | 6,779 ms | 14,035 bytes |

The extraction differences are within network variability; this is **not**
evidence of a substantial extractor speedup. Selected-field JSON was chosen
because it preserves `url`, `http_headers`, and `format_id` without dumping
all formats. `-g` does not provide required headers. Both retain yt-dlp's
normal extractor behavior. The architectural gain is doing that work before
Enter and bypassing mpv's second extraction.

## Actual cold and prefetched playback

Timer starts **before** calling the TUI's `play_online` entry point. Readiness
requires file-loaded, playback-restart, a nonzero time-pos, and non-idle state.
These are player/output observations, not microphone measurements. The initial
recorded benchmark sampled readiness every 10 ms (the instrumentation now also
records the first nonzero position notification itself). Cache-hit samples do
not run another extractor. No intentional playback delay or discarded slow run.

Same video, default environment, three runs:

| Phase | Median | p95 (nearest rank) |
| --- | ---: | ---: |
| Cold Enter → playback | 12,713 ms | 13,925 ms |
| Prefetched Enter → playback | 5,350 ms | 5,484 ms |
| Fresh standalone resolution | 7,389 ms | 7,874 ms |
| Warm resolver cache lookup | 0.020 ms | 0.031 ms |

**The default-environment warm target was not achieved.** mpv's debug trace
showed about five seconds before its TCP connection attempt. A separate
`getaddrinfo(AF_UNSPEC)` call for that media host took **5,027 ms**; subsequent
IPv4/IPv6 calls took 19/4 ms. This isolates a DNS problem on this development
network, not five seconds of decoder work. Reopening the same direct URL took
5,754 / 5,440 / 296 ms, illustrating the variability.

A process-only diagnostic with **`RES_OPTIONS=single-request-reopen`** avoids
parallel A/AAAA socket reuse on glibc. No application or system DNS setting was
changed. Same original video, five runs with that environment:

| Phase | Median | p95 (nearest rank) |
| --- | ---: | ---: |
| Cold Enter → playback | 2,824 ms | 3,792 ms |
| Prefetched Enter → playback | **290 ms** | **331 ms** |
| Fresh standalone resolution | 1,716 ms | 3,083 ms |
| Warm resolver cache lookup | 0.038 ms | 0.099 ms |

All five prefetched samples were below one second. This demonstrates the warm
path's capability with the DNS issue removed, **not** an unconditional ≤2 s
claim. Cold resolution still misses the target in four of five samples; YouTube
extraction/network latency remains external. With only five samples, p95 is
the maximum observed sample, not a population-level reliability guarantee.

### v0.16.4 confirmation: the five-second stall was a DNS retry timeout

A later syscall trace reproduced the delay directly. With yt-dlp forced to IPv4,
`strace -f -tt -T -yy` showed a UDP socket connected to the local DNS proxy on
port 53 receive one reply in roughly 12 ms, then block waiting for another reply:

```text
poll(... UDP:[client -> local-resolver:53] ..., 4987)
    = 0 (Timeout) <4.992079>
```

The same socket retried immediately afterward and received the required replies
in roughly 10–20 ms. TCP setup after DNS was measured in tens of milliseconds.
This confirms that the ~5 s component was resolver retry latency rather than
YouTube decoding, Python CPU work, or media-server distance.

Independent resolver-profile testing found no substantial extractor-only win:
the default yt-dlp profile had a 7.103 s median across five runs, while the best
reliable tested client profile was 6.963 s. Forcing IPv4 produced a 6.862 s
median and forcing IPv6 a 6.814 s median, so address-family selection alone did
not remove the stall.

With `RES_OPTIONS=single-request-reopen`, five yt-dlp resolves completed in:

```text
3.348 s
2.692 s
2.455 s
3.680 s
2.229 s
```

Median: **2.692 s**. This removes most of the observed ~7 s cold-resolve delay
without changing the system resolver or selecting a third-party DNS service.

v0.16.4 therefore applies `single-request-reopen` process-locally on glibc to
the yt-dlp search/resolver workers and to mpv only when `--youtube` is enabled.
Existing `RES_OPTIONS` values are preserved, duplicate insertion is avoided,
and non-glibc platforms are left unchanged.

A separate streaming-search run with that DNS environment and “On My Way”
returned the first result in **1,586 ms**, all 12 in **1,675 ms**. This comparison
also changes DNS conditions, so it cannot attribute the entire improvement
over 6,779 ms to streaming. A final **default-DNS** run took **10,017 ms** to
the first result and **10,108 ms** to completion (warm playback 5,327 ms).
There is no demonstrated default-network search speedup; initial external
requests still dominate. The first result can now appear independently of
process completion; both search and extraction run off the TUI thread.

Machine-readable measurements:

- [default DNS, three runs](youtube-benchmark-default-dns.json)
- [default DNS search, final one-run check](youtube-benchmark-default-search.json)
- [DNS diagnostic, five runs](youtube-benchmark-single-request-reopen.json)
- [Final-code check, one run](youtube-benchmark-final-code.json): 2,687 ms cold,
  288 ms warm, 287 ms direct-open; same process-local DNS diagnostic.

## IPC traffic

A matched, three-second real-mpv workload reads eight observed properties per
frame, with a 100 ms delay between frames, after initial connection setup:

| Implementation | Commands | Commands/sec |
| --- | ---: | ---: |
| v0.16.2 synchronous getters | 232 | 77.09 |
| Event-driven getters | 0 | 0.00 |

The entire live benchmark, including initialization and load/play/stop commands,
used 25 commands over 71.86 s (**0.35/s**) in the default-DNS run and 37 over
26.66 s (**1.39/s**) in the five-run diagnostic. These whole-session rates are
workload-dependent; they are not a controlled comparison with a full curses
session. The user's original observation was about 1,200 requests in 13 s.

## Design and invariants

- One persistent mpv socket, one reader, newline framing, pending request IDs,
  concurrent reply correlation, reconnect/resubscription, and bounded waits.
- Frequent playback properties are observed. Gapless path/count/position remain
  fresh synchronous reads at the existing mutation gates. No append at -1.
- Search emits small JSON lines from a background worker. The UI publishes
  partial results, prefetches the first, and debounces selection for 150 ms.
- One resolver worker plus one replaceable pending request, deduplication,
  cancellation on shutdown/superseding Enter, 16-entry memory-only LRU, 180 s
  maximum TTL, and signed expiry minus a 30 s margin.
- Per-file mpv options preserve extractor HTTP headers, disable ytdl for direct
  streams, and restore options afterward. Named loadfile arguments support
  both sides of mpv 0.38's positional index change.
- Resolution failure falls back to the watch URL. Direct playback honors the
  extractor availability deadline; an early open failure can reuse the URL once
  before invalidating/resolving once and falling back. Repeated Enter cannot restart
  a resolving/loading track. No media files, SQLite inserts, or new dependency.
- Local playback and Bad Larry's seek/pause controls use the existing controller.
  Without `--youtube`, no online workers start.

## Reproduction and validation

```bash
python tools/benchmark_youtube_startup.py 'https://www.youtube.com/watch?v=jNQXAC9IVRw' --runs 5 --json
python tools/benchmark_youtube_startup.py --query 'On My Way' --runs 5 --json
python tools/benchmark_youtube_startup.py 'https://www.youtube.com/watch?v=jNQXAC9IVRw' --candidates --runs 3
# Diagnostic only, on affected glibc/Linux DNS configurations:
RES_OPTIONS=single-request-reopen python tools/benchmark_youtube_startup.py 'https://www.youtube.com/watch?v=jNQXAC9IVRw' --runs 5 --json
python -m unittest discover -s tests -v
MEOW_REAL_MPV=1 python -m unittest discover -s tests -p test_mpv_http.py -v
```

Normal unit tests require no live YouTube. The real HTTP integration generates
three seconds of WAV silence in a temporary directory, verifies per-file header
isolation, actual mpv startup events, zero property-poll traffic, and reader
shutdown. The existing Linux integration retains real mpv gapless, D-Bus/MPRIS,
inotify, debug logging, and artwork checks. mpv uses null audio in CI only.

MeowPlayer logs phase timings, IDs, and resolver paths, not signed media URLs
or headers. mpv verbose logs may include both: redact them before sharing.
