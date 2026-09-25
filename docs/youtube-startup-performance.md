# Internet Nest startup investigation

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
- Resolution failure falls back to the watch URL. Direct stream-open failure
  invalidates and resolves once, then falls back. Repeated Enter cannot restart
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
