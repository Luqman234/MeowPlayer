# MeowPlayer 🐈🎵

**A terminal music player with suspiciously serious engineering and an entirely unnecessary cat.**

**MeowPlayer 0.17.1** is a local-first, keyboard-first terminal music player for Linux and Termux. `mpv` does the decoding, Python + `curses` run the TUI, SQLite remembers the library, Mutagen reads tags, Watchdog notices filesystem changes, LRCLIB can fetch synchronized or plain lyrics, MusicBrainz can fill missing metadata, and the cat takes credit for all of it.

No account is required. Your normal music library can remain ordinary files on disk. Online features are optional. The cat is not optional unless you invoke **Serious Mode**, which is legally distinct from making the cat leave.

> 🐾 **Project doctrine:** local-first, keyboard-first, terminal-native, technically serious, catastrophically cat-themed.
>
> If a feature can be engineered properly, it should be. If that same feature can also be called **The Catnip Stash**, apparently it will be.

```text
 /\_/\   ♫ MEOWPLAYER v0.17.1 — Purring
( ^.^ )
 > ♫ <

▶  Now Purring: Space Song — Beach House
00:42 ━━━━━━━∿──────────── 05:20

Meow Level: 70%   Pounce: ON (37 left)
Tail-Chase: OFF   Catnip: 4   Verdict: ★★★★☆   Mood: Zoomies

Music Nest / Songs — 842 meow(s)
🐾 Space Song — Beach House · Depression Cherry · Dream Pop · ★★★★☆ · 05:20
```

### The short version — before the cat turns this README into a thesis

MeowPlayer started from a simple idea:

```text
find music → play music → add cat
```

It then made several questionable architectural decisions:

```text
find music
   ↓
index music
   ↓
cache metadata
   ↓
watch the filesystem
   ↓
generate Smart Mixes
   ↓
prime gapless playback
   ↓
fetch lyrics
   ↓
investigate Unknown Artist on the internet
   ↓
let the user pet the cat
```

The result is still supposed to feel like a terminal music player: fast to launch, keyboard-driven, local-first, readable, hackable, and comfortable living next to `git`, `ssh`, and whatever other crimes are occurring in your shell.

### The Cat Constitution — six laws written in paw ink

MeowPlayer tries to stay true to a few rules:

- **Local files are the foundation.** The player does not require a proprietary cloud library.
- **Local tags are authoritative.** MusicBrainz may fill holes; it does not get to overrule good metadata you already own.
- **Online features fail soft.** No internet should mean fewer conveniences, not no music.
- **The cat may be ridiculous; playback state may not be.** Cat Incidents are presentation-only.
- **Your audio files are not secretly rewritten.** Online metadata and downloaded lyrics live in MeowPlayer's own cache/catalog unless you create sidecar files yourself.
- **Serious Mode remains a first-class citizen.** The application can remove most cat presentation without removing actual features.

### What lives under the fur — an alarming amount of software

| Area | What MeowPlayer actually uses |
| --- | --- |
| Playback | `mpv` JSON IPC, gapless priming, ReplayGain, optional yt-dlp online streams |
| Library | SQLite **Cat Catalog**, recursive scanning, Watchdog/inotify |
| Metadata | Mutagen locally, optional MusicBrainz enrichment for missing fields |
| Lyrics | sidecar/embedded lyrics + optional LRCLIB synchronized/plain lookup |
| Discovery | Artists, Albums, Folders/Nests, Pawmarks, Purr History, Smart Mixes |
| Desktop | MPRIS / D-Bus, `playerctl`, media keys |
| Terminal candy | Kitty album art, CAVA spectrum |
| Critical infrastructure | `G` to pet the cat |

## What's new in 0.17.1 — The Cat Has Obtained a Settings Nest

MeowPlayer 0.17.1 gives the cat a first-class configuration screen and fixes the packaging mistake that briefly caused the cat to ship the house without the nest.

Press `,` from the TUI to open **Settings Nest**.

```text
SETTINGS NEST

  Remember yesterday's nap               [ ON ]       NEXT LAUNCH
  Desktop cat privileges                 [ ON ]       NEXT LAUNCH
  Terminal rectangle pictures            [ ON ]       LIVE
>^.^< No awkward silence between zoomies [ weak ]     LIVE
  Volume diplomacy                       [ track ]     LIVE
  Extra loudness seasoning               [ +0.0 dB ]  LIVE
  Songbook                               [ ON ]       LIVE
  Internet lyric cats                    [ ON ]       LIVE
  Metadata detective cat                 [ ON ]       LIVE
  Wiggly fence                           [ ON ]       LIVE
  Hear files move through walls          [ ON ]       LIVE
```

The Settings Nest edits the same persistent XDG config used by the rest of MeowPlayer. Live-safe settings apply immediately; settings that would require restarting a subsystem are clearly marked **NEXT LAUNCH**.

0.17.1 also fixes the clean-install packaging failure where `meowplayer.py` imported `settings_nest` but the wheel did not contain `settings_nest.py`. The module is now explicitly included in the setuptools `py-modules` list, so wheel/sdist smoke installs can actually find the nest they were promised.

The Internet Nest also now uses a **🐾 paw marker for the actively streaming online track in cat mode** instead of the generic 🌐 internet globe. Serious Mode keeps the conventional `▶` marker, while `>^.^<` remains the ordinary selection cursor for a highlighted result that is not currently playing.

In short:

```text
0.17.0: the cat learned to follow an Artist Scent
0.17.1: the cat obtained a settings panel
        and remembered to put it in the box
```

> **MeowPlayer 0.17.1 — household rules are now editable from the TUI, and the wheel once again contains all required cats.**

## What's new in 0.17.0 — The Cat Has Discovered That Songs Come From Humans

A major scientific breakthrough has occurred inside the Internet Nest.

Until now, MeowPlayer understood YouTube roughly like this:

```text
human types words
        ↓
internet produces videos
        ↓
cat points at one
        ↓
music probably happens
```

This was sufficient.

Then somebody asked the dangerous question:

> “Can I search for the **artist**?”

The cat stared into the middle distance.

The database went quiet.

Somewhere, an SQLite connection closed itself respectfully.

After several minutes of intense feline research, MeowPlayer has now discovered that multiple songs can apparently come from the **same human**.

This concept is called an **artist**.

We are calling the resulting feature:

# 🐾 ARTIST SCENT™

because “artist-name search” was rejected for insufficient whiskers.

### Press A to deploy Detective Cat

Inside the Internet Nest:

```text
A
↓
ARTIST SCENT DEPLOYED
↓
human enters: Porter Robinson
↓
cat sniffs the internet
↓
"Porter Robinson" music
↓
possible Porter Robinson-shaped objects detected
```

In practical terms, `A` opens a dedicated artist search prompt.

Example:

```text
Internet Nest artist scent: Porter Robinson
```

Behind the curtain, MeowPlayer asks yt-dlp for something equivalent to:

```text
ytsearch12:"Porter Robinson" music
```

The cat has therefore advanced from:

```text
"find Shelter"
```

to:

```text
"find the creature responsible for Shelter,
then bring me more evidence"
```

This is progress.

Probably.

### The secret second entrance: artist:

If pressing `A` feels insufficiently dramatic, the normal YouTube search box also understands:

```text
artist:Porter Robinson
artist:Beach House
artist:YOASOBI
artist:Radiohead
```

So Internet Nest now has two hunting licenses:

```text
/ or Y
   ↓
GENERAL HUNT
   ↓
"find these words on YouTube"
   ↓
song titles / mixed queries / internet nonsense


A or artist:Name
   ↓
ARTIST SCENT
   ↓
"follow this musician specifically"
   ↓
artist-biased music results
```

The cat is still not permitted to lick the network cable.

### Why doesn't Artist Scent just filter by channel name?

Because YouTube metadata is a box of cables someone shook violently.

A perfectly legitimate song may be uploaded by:

```text
the artist
the artist's "- Topic" channel
VEVO
a record label
a distributor
an official partner
some mysterious sanctioned cupboard with 14 million subscribers
```

A strict rule like:

```text
uploader == artist
```

would look elegant for approximately six seconds.

Then it would start throwing away real songs.

So Artist Scent does **not** say:

```text
"If the channel name is not exactly Porter Robinson,
THIS MOUSE IS COUNTERFEIT."
```

Instead it biases the YouTube search toward the artist name and music, then lets the normal result machinery do its job.

This is less pure.

It is also substantially less stupid.

### The cat now checks more nametags

Search results now ask yt-dlp for more identity clues:

```text
artist
artists
creator
uploader
channel
```

MeowPlayer then behaves approximately like this:

```text
          incoming YouTube result
                    │
                    ▼
           artist metadata exists?
             /              \
           yes               no
            │                 │
            ▼                 ▼
     use artist/creator   check uploader
                              │
                              ▼
                         check channel
                              │
                              ▼
                    "fine, you may enter"
```

The goal is not to construct a perfect global ontology of musicians.

The goal is to stop displaying:

```text
SomeRecordLabelOfficialVEVOThing
```

as the artist when YouTube already gave us an actual artist field two properties away.

### The Internet Nest now displays what kind of nonsense it is doing

Normal search:

```text
Internet Nest — scent: shelter · 12 meow(s)
```

Artist search:

```text
Internet Nest — artist scent: Porter Robinson · 12 meow(s)
```

The footer also gained another tiny command because apparently we had spare room:

```text
/  normal hunt
A  artist scent
Y  YouTube search
```

In Serious Mode this is explained like respectable software.

In normal mode, the cat is tracking musicians.

### Important: the cat did not knock over the architecture

Artist Scent uses the **same Internet Nest machinery** already built in the 0.16.x series:

```text
artist query
    ↓
background JSON-line search
    ↓
results appear incrementally
    ↓
first / highlighted result
    ↓
150 ms "are you actually staying there?" debounce
    ↓
one resolver worker
    ↓
one replaceable queued request
    ↓
short-lived direct-stream cache
    ↓
Enter
    ↓
mpv gets dinner
```

Still preserved:

```text
background search                  ✓
incremental results                ✓
first-result prefetch              ✓
highlight prefetch                 ✓
150 ms selection debounce          ✓
one active resolver                ✓
one queued replacement             ✓
direct-stream caching              ✓
scoped glibc DNS workaround        ✓
mpv fallback path                  ✓
ephemeral online results           ✓
Cat Catalog contamination          ✗
mysterious automatic downloads     ✗
cat promoted to root               absolutely not
```

Artist search results remain **ephemeral**.

They are not inserted into the Cat Catalog.

They are not downloaded.

They do not become fake local files.

They do not wake up tomorrow with a mortgage and an inode.

### The cat's official artist-identification policy

For legal and feline clarity:

```text
Artist Scent is:

artist-biased search
+ better metadata extraction
+ existing Internet Nest playback

Artist Scent is NOT:

an official YouTube Music API
a channel-only browser
a discography database
a recommendation engine
a remote library importer
Spotify wearing terminal makeup
```

The Internet Nest is still intentionally lightweight and temporary.

The cat visits the internet.

The cat does not move there.

### Why is this 0.17.0 instead of 0.16.5?

Because this is not another repair to Internet Nest.

0.16.x was largely:

```text
make YouTube work
↓
make YouTube stop breaking
↓
make YouTube stop blocking the TUI
↓
make YouTube stop interrogating mpv 77 times per second
↓
make DNS stop stealing five seconds of everyone's lifespan
```

0.17.0 is:

```text
"okay, now give the Internet Nest a new way to discover music"
```

That is a user-facing capability, not just another wrench applied to the plumbing.

The cat has learned **taxonomy**.

We are all extremely proud and slightly concerned.

### 0.17.0 in one diagram

```text
                    HUMAN
                      │
          "I want Porter Robinson"
                      │
                      ▼
                press A
                      │
                      ▼
              /_/\
             ( o.o )   ← Detective Cat
              > ^ <
                │
                │ sniff sniff
                ▼
          INTERNET NEST
                │
      "Porter Robinson" music
                │
      ┌─────────┼─────────┐
      ▼         ▼         ▼
   result 1  result 2  result 3
      │
      ▼
 background prefetch cat
      │
      ▼
     Enter
      │
      ▼
     mpv
      │
      ▼
   ♫ music ♫

Meanwhile:
Cat Catalog = untouched
local files = untouched
DNS = hopefully behaving
Bad Larry = still banned from architecture meetings
```

And thus MeowPlayer enters the 0.17 era with the completely reasonable ability to search for musicians by name.

> **MeowPlayer 0.17.0 — the Internet Nest can now follow an artist scent, the cat has discovered recurring human entities, and somehow this required a minor-version bump.**

## What's new in 0.16.4 — The Router Ate a DNS Reply and the Cat Took It Personally

0.16.4 exists because the Internet Nest was still occasionally doing this:

```text
user: play song
cat:  absolutely
cat:  one moment
cat:  ...
cat:  ...
cat:  ...
cat:  why is the router not answering me
cat:  ...
cat: finally
```

We eventually stopped blaming yt-dlp, stopped glaring at mpv, and put the whole thing under `strace`.

The crime scene was extremely specific:

```text
DNS request → local resolver
        ↓
one reply arrives                 ~12 ms
        ↓
the other reply apparently enters the void
        ↓
cat stares at socket
        ↓
poll timeout                      ~4.992 s
        ↓
retry
        ↓
replies arrive                    ~10–20 ms
```

That nearly-five-second nap was a UDP DNS wait on port 53. After the retry, the actual network work moved quickly.

So no, yt-dlp was not spending seven seconds performing forbidden mathematics.

It was mostly waiting for DNS.

### The fix: bother glibc differently, not the whole computer

On affected glibc/Linux systems, `single-request-reopen` avoids the resolver behavior that triggered the lost-companion-reply problem.

Before the fix, repeated yt-dlp runs on the affected machine were around:

```text
default resolver median     ~7.1 s
```

With the workaround:

```text
3.348 s
2.692 s
2.455 s
3.680 s
2.229 s

median: ~2.692 s
```

That is not a tiny optimization.

That is the cat reclaiming roughly **four to five seconds of its life**.

MeowPlayer now applies the workaround only where the Internet Nest needs it. Existing resolver options are preserved, the option is not duplicated, and non-glibc platforms are left alone.

The affected children are:

- the yt-dlp search worker;
- the yt-dlp direct-stream resolver;
- mpv when MeowPlayer was started with `--youtube`.

Local-only playback does not get dragged into this DNS drama.

And MeowPlayer still does **not** edit `/etc/resolv.conf`, replace NetworkManager settings, force a public DNS service, or sneak into your router at 3 AM with a screwdriver.

The parent shell stays untouched.

### Before and after, in cat terms

Before:

```text
highlight result
   ↓
background cat starts hunting
   ↓
DNS drops one answer
   ↓
cat waits ~5 seconds in complete spiritual defeat
   ↓
yt-dlp continues
   ↓
stream finally cached
```

Now:

```text
highlight result
   ↓
background cat starts hunting
   ↓
resolver behaves itself
   ↓
~2–3 s observed resolve time
   ↓
stream cached
   ↓
Enter
   ↓
mpv already has dinner
```

0.16.3 made the architecture fast.

0.16.4 removed the networking gremlin that was sitting on top of it.

Tests cover preserving existing `RES_OPTIONS`, avoiding duplicate insertion, leaving non-glibc systems alone, propagating the environment to both yt-dlp workers, and giving YouTube-enabled mpv the same scoped workaround.

> **0.16.3 taught the cat to hunt before Enter. 0.16.4 discovered the router had been hiding one of the mice.**

## What's new in 0.16.3 — The Cat Starts Hunting Before You Ask

Internet Nest used to be technically correct in the most annoying possible way.

You pressed `Enter`.

Then MeowPlayer began doing all the expensive internet work.

Then you waited.

Then the cat insisted this was a feature.

The old path looked approximately like this:

```text
search
  ↓
TUI waits for yt-dlp
  ↓
results finally appear
  ↓
Enter
  ↓
yt-dlp starts another expensive job
  ↓
wait some more
  ↓
mpv opens stream
  ↓
music
```

0.16.3 changed the philosophy from:

> **do the work after the human asks**

to:

> **send the cat hunting while the human is still deciding**

```text
Internet Nest search worker
        ↓
results appear as they arrive
        ↓
first / highlighted result
        ↓
150 ms "are you actually staying on this row?" debounce
        ↓
one background resolver
        ↓
short-lived ResolvedStream cache

             meanwhile, the human exists

                        ↓

                      Enter
                        ↓
cached direct audio URL + per-file headers
                        ↓
mpv opens the already-resolved stream
                        ↓
music
```

### Search escaped from the main thread

YouTube search now runs in a background worker and publishes JSON-line results as they arrive.

The TUI no longer has to sit frozen like a cat that heard a plastic bag move in another room.

The first usable result can immediately begin prefetching. When you move the selection, MeowPlayer waits **150 ms** before resolving the highlighted row so frantic arrow-key movement does not summon an entire army of yt-dlp processes.

There is only:

```text
1 active resolver worker
1 replaceable queued request
0 reasons to spawn 14 extractors because you held ↓
```

Requests for the same video are deduplicated.

### Enter is allowed to benefit from previous labor

Resolved streams live in a **16-entry memory-only LRU** for at most **180 seconds**, shortened when the signed media URL expires sooner.

The cache contains what playback actually needs:

```text
video identity
direct audio URL
required HTTP headers
format id
```

It does **not**:

```text
download the song
insert it into Cat Catalog
pretend YouTube is your local library
survive the next launch
become a mysterious cache folder named DO_NOT_DELETE_FINAL_v7
```

When the highlighted result is already resolved:

```text
Enter
  ↓
no second yt-dlp extraction
  ↓
direct stream → mpv
  ↓
headers apply to this file only
  ↓
music
```

If that direct stream gets rejected, MeowPlayer throws away the stale entry, tries one fresh resolve, then still has mpv's normal watch-URL ytdl path as a fallback.

And repeatedly punching `Enter` while the same track is already resolving/loading still does not make the internet more motivated.

Without `--youtube`, none of these online workers start.

### mpv is no longer questioned like a suspicious witness 77 times per second

0.16.2 gave MeowPlayer one persistent, framed mpv JSON IPC connection.

0.16.3 taught it to actually use that connection like an adult.

Frequently-read playback properties are now observed and cached instead of synchronously asking mpv the same questions every TUI loop.

Measured property traffic:

```text
before: 77.09 commands / second
after:   0.00 commands / second after observer setup
```

The cat has stopped repeatedly asking:

```text
are we paused?
are we paused?
are we paused?
what about now?
what about now?
what about now?
```

Gapless playback is intentionally more paranoid. Path, playlist position, and playlist count still use fresh synchronous reads at the mutation points where stale information could break the one-track-ahead playlist.

The sacred local-gapless arrangement remains:

```text
playlist-current-pos = 0
playlist-count       = 2
```

And if mpv says:

```text
playlist-current-pos = -1
```

MeowPlayer does not touch the future playlist.

The cat may be impulsive.

The gapless state machine is not.

### Benchmarks, because apparently the cat has a laboratory now

The measurements do not call playback "started" just because mpv acknowledged a command.

Startup requires the expected stream plus real playback evidence: `file-loaded`, `playback-restart`, non-idle state, and advancing playback time.

Development setup:

```text
mpv       0.41.0
yt-dlp    2026.08.19
platform  Linux / glibc
video     jNQXAC9IVRw
```

| Measurement | Result |
| --- | ---: |
| Previous mpv watch-URL → playback baseline | 12,419 ms |
| Full JSON extractor baseline | 7,004 ms / 87,723 bytes |
| Direct `-g` candidate | 7,066 ms / 1,162 bytes |
| Selected-JSON candidate | 6,837 ms / 1,477 bytes |
| Default DNS, cold median / p95 (3 runs) | 12,713 / 13,925 ms |
| Default DNS, warm median / p95 (3 runs) | 5,350 / 5,484 ms |
| DNS diagnostic, cold median / p95 (5 runs) | 2,824 / 3,792 ms |
| DNS diagnostic, warm median / p95 (5 runs) | **290 / 331 ms** |
| Final diagnostic cold run | 2,687 ms |
| Final diagnostic warm run | **288 ms** |
| Final diagnostic direct-open time | **287 ms** |

The selected-JSON resolver won because it preserves the HTTP headers needed for reliable direct playback.

The important trick is **not** that yt-dlp suddenly learned to resolve YouTube in 287 ms.

It did not.

The trick is:

```text
expensive extraction
        ↓
happens before Enter

Enter
        ↓
reuse finished work
        ↓
fast direct open
```

That is prefetching doing exactly what prefetching is supposed to do, except with more whiskers.

### Did we actually hit the two-second target?

The goal was:

> **≤2 seconds from Enter to real mpv playback on a prefetched result**

In the original default environment: **nope**.

A media-host DNS lookup independently reproduced about **5,027 ms** before TCP even got a chance to do anything useful.

With the process-only resolver diagnostic used during 0.16.3 development:

```bash
RES_OPTIONS=single-request-reopen \
  python tools/benchmark_youtube_startup.py \
  'https://www.youtube.com/watch?v=...' \
  --runs 5 --json
```

all five warm samples were under one second:

```text
median: 290 ms
p95:    331 ms
```

At the time of the 0.16.3 investigation, MeowPlayer deliberately did **not** set that resolver option itself because the DNS cause had not yet been proven strongly enough.

Then 0.16.4 arrived with `strace`, caught the exact **4.992-second DNS timeout**, and turned that diagnostic into a scoped product fix.

So the historical sequence is:

```text
0.16.3:
"interesting, this DNS workaround makes the warm path ~0.3 s"

0.16.4:
"we caught the 4.992 s timeout red-pawed; deploy the scoped fix"
```

Cold extraction can still take a few seconds because YouTube is still the internet and the internet remains committed to being the internet.

### Debug logs: receipts, but please inspect them before posting

With `--debug` or `--log-file`, MeowPlayer records performance events such as:

```text
YT_LATENCY
YT_PREFETCH
YT_PLAY
IPC_STATS
```

using monotonic timing.

MeowPlayer's own performance logging intentionally avoids direct stream URLs and HTTP-header values.

mpv's verbose debug log can still contain signed URLs and headers, because mpv has never met a secret it did not want to print at maximum verbosity.

So redact before posting.

Useful benchmark commands:

```bash
python tools/benchmark_youtube_startup.py \
  'https://www.youtube.com/watch?v=...' \
  --runs 5 --json

python tools/benchmark_youtube_startup.py \
  --query 'On My Way' \
  --runs 5 --json

python tools/benchmark_youtube_startup.py \
  'https://www.youtube.com/watch?v=...' \
  --candidates --runs 3
```

Full measurements, reproduction commands, DNS evidence, caveats, and the serious-adult version of this story live in [`docs/youtube-startup-performance.md`](docs/youtube-startup-performance.md).

### Did the cat break everything else?

That would be embarrassing, so we checked.

The performance work includes deterministic coverage for cache expiry, deduplication, rapid selection changes, debounce, Enter during and after prefetch, cancellation, late results, fallback/re-resolution, partial IPC frames, interleaved replies, observed values, reconnect/resubscription, reader shutdown, and HTTP-header isolation.

The existing Linux integrations still exercise mpv IPC, stable gapless `position=0/count=2`, playback/re-prime, debug logs, D-Bus/MPRIS, Watchdog/inotify, and Pillow.

Packaging still gets wheel/sdist builds, metadata validation, clean-install checks, CLI version/help checks, and coverage.

Normal CI does **not** call live YouTube. The direct-stream integration uses a local HTTP fixture because depending on YouTube in every CI run would be less "continuous integration" and more "continuous bargaining with an external website."

A real-mpv CI run even caught a gapless re-prime timing race during development, so the fresh synchronous gapless confirmation stayed exactly where it belonged.

In short:

> **the internet cat starts hunting early, the playback cat stopped interrogating mpv 77 times a second, and the gapless cat still wears a tiny safety helmet.**

## What's new in 0.16.2 — The Cat Learned How Newlines Work

The first real `--youtube --debug` session exposed two problems that were easy to miss without logs. The cat had, until this moment, apparently assumed one socket read contained exactly one polite JSON object. The socket disagreed.

First, mpv JSON IPC is a **newline-delimited message stream**. A single socket read can contain an event and a command reply together. Older MeowPlayer code treated the whole read as exactly one JSON document, which could produce:

```text
JSONDecodeError: Extra data: line 2 column 1
```

even when mpv had successfully executed the command.

MeowPlayer 0.16.2 replaces that assumption with a persistent, framed IPC connection:

```text
MeowPlayer
    │
    │ one Unix socket
    ▼
mpv JSON IPC
    │
    ├── event: start-file
    ├── request_id: 41 → get_property reply
    ├── event: playback-restart
    └── request_id: 42 → seek reply
```

Each command now carries a monotonically increasing `request_id`. MeowPlayer buffers bytes until complete newline-delimited JSON messages are available, ignores/records asynchronous events while waiting, and returns only the reply matching the current request. Malformed individual lines are skipped without poisoning later replies.

The same connection is reused instead of creating dozens of short-lived Unix socket clients every second. If the connection genuinely dies, it is discarded cleanly and the next command reconnects.

Second, the Internet Nest now **debounces repeated Enter presses** while a YouTube result is resolving. Previously, repeatedly pressing Enter could issue repeated `loadfile replace` commands and kill yt-dlp extraction jobs that were still working.

Now:

```text
Enter
  ↓
Resolving YouTube stream...
  ↓
Enter again
  ↓
ignored

More Enter will not make the router go faster.
```

Online playback has explicit `resolving`, `streaming`, and `failed` states. A failed/idle attempt becomes retryable after a short guard window instead of being permanently wedged, while an active stream cannot be accidentally restarted by hammering Enter.

Regression tests cover multi-message IPC reads, asynchronous events before replies, request correlation, connection reuse, malformed-line recovery, duplicate YouTube playback requests, failed-stream retry, and resolving→streaming transitions.

## What's new in 0.16.1 — The Cat Finally Keeps Receipts

The era of “it broke but the curses screen ate the evidence” is over.

MeowPlayer now has a proper **file-based debug mode** designed specifically for a curses TUI, where dumping diagnostics into the terminal would otherwise turn the screen into ANSI soup.

Start normally with debug logging enabled:

```bash
meowplayer --debug
```

By default, MeowPlayer writes its own rotating log to:

```text
$XDG_STATE_HOME/meowplayer/debug.log
```

or, when `XDG_STATE_HOME` is not set:

```text
~/.local/state/meowplayer/debug.log
```

mpv gets a separate verbose log beside it:

```text
~/.local/state/meowplayer/debug.mpv.log
```

The MeowPlayer log rotates at roughly **2 MiB**, keeping up to **3 backups**, so turning on debug mode does not create an immortal text monster. The mpv log is refreshed for each debug run and receives verbose mpv/ytdl-hook diagnostics.

For a custom location:

```bash
meowplayer --log-file /tmp/meowplayer-debug.log
```

`--log-file` automatically enables debug mode. Its mpv sibling becomes:

```text
/tmp/meowplayer-debug.mpv.log
```

A particularly useful command for the experimental Internet Nest is:

```bash
meowplayer --youtube --debug
```

Then, in another terminal:

```bash
tail -f ~/.local/state/meowplayer/debug.log
```

and for the lower-level playback/extractor side:

```bash
tail -f ~/.local/state/meowplayer/debug.mpv.log
```

The main debug log records useful events such as startup/runtime information, enabled modes, player initialization, local and online playback starts, TUI status changes, YouTube searches, yt-dlp search failures, mpv lifecycle events, IPC failures, shutdown, and uncaught TUI exceptions.

Debug output is deliberately **file-only**. MeowPlayer does not attach a noisy console logging handler while curses owns the screen.

Debug logs can contain local music paths, YouTube search terms, selected video URLs, and low-level diagnostics. Read them before posting them publicly if any of that information matters to you.

In short:

```text
something broke
     ↓
meowplayer --debug
     ↓
debug.log       ← MeowPlayer / YouTube search / Python side
debug.mpv.log   ← mpv / ytdl-hook / playback side
     ↓
the cat can no longer claim there were no witnesses
```

## What's new in 0.16.0 — The Cat Found the Internet Radio

The cat discovered the Internet Nest. Supervision became necessary almost immediately.

MeowPlayer can now opt into **experimental YouTube search and online audio playback** through the same mpv backend used for local music.

Start it with:

```bash
meowplayer --youtube
```

Then press `Y` from the TUI to open the **Internet Nest**. Type a song/title search, choose a result with the arrow keys, and press `Enter` to stream it.

```text
INTERNET NEST

query: porter robinson shelter

>^.^< Shelter — Porter Robinson & Madeon · 3:38 · YouTube
      Shelter (Official Video) — Porter Robinson · 3:50 · YouTube
      Something Comforting — Porter Robinson · 4:41 · YouTube
```

Once an online result is actually streaming, cat mode marks that active row with a paw:

```text
🐾 Shelter — Porter Robinson & Madeon · 3:38 · YouTube
```

`>^.^<` is still the selection cursor for a highlighted result; `🐾` means **this is the Internet Nest track currently playing**. Serious Mode uses `▶` instead.

The implementation deliberately keeps the local and online worlds separate:

```text
local file
    ↓
Cat Catalog / tags / lyrics / gapless queue
    ↓
mpv

async YouTube search (JSON lines)
    ↓
first result / highlighted result
    ↓
one background yt-dlp resolver → short-lived URL + header cache
    ↓ Enter
mpv direct stream (per-file headers, ytdl disabled)
    ↓
audio stream
```

Online search results are **ephemeral**. They are not inserted into the SQLite Cat Catalog, do not pretend to be local files, and are not restored as a local track on the next launch. Switching back to a local track cleanly leaves online playback state.

The online track still participates in ordinary playback controls such as pause, seek, volume, repeat, and MPRIS metadata. Bad Larry can also interfere with an active online stream because apparently the cat has jurisdiction over the internet now.

This feature is intentionally **opt-in and experimental**. It requires a working `yt-dlp` executable on `PATH`, and YouTube-side changes can temporarily break extraction until `yt-dlp` catches up. Local playback remains completely independent.

MeowPlayer never saves online audio files or adds remote tracks to Cat Catalog. The cat now stalks the stream before you press Enter: the first search result is prefetched immediately, and selection changes are debounced for 150 ms. Search and resolution run in background workers; you can navigate results as they arrive.

One resolver runs at a time, with at most one queued selection. Enter shares any existing resolve instead of starting another process. Successful URLs and their required HTTP headers live in a 16-entry memory-only LRU for at most three minutes (less when a signed URL expires sooner). A cache hit loads the direct URL into mpv without another yt-dlp extraction. Headers apply only to that file.

If resolution fails, mpv's watch-URL ytdl hook remains the fallback. A rejected direct stream invalidates its cache entry, gets one fresh resolve, then falls back if necessary. Repeated Enter while resolving/loading remains ignored. Playback is only reported as streaming after mpv reports file-loaded, playback-restart, and a nonzero playback position.

Without `--youtube`, no search or resolver worker starts. Local playback, ReplayGain, MPRIS, lyrics, Pawmarks, and Bad Larry keep their existing jobs.

This is an unofficial integration built around mpv + yt-dlp, not an official YouTube Music API client.

### Measuring the internet cat — because vibes are not benchmarks

With `--debug` or `--log-file PATH`, look for `YT_LATENCY`, `YT_PREFETCH`, `YT_PLAY`, and `IPC_STATS`. Durations use a monotonic clock and include the time from Enter, including any unresolved stream work. Logs identify cache/fresh/fallback paths and mpv startup events. The IPC reader observes frequently used playback properties; gapless path/playlist-position/count queries remain synchronous to preserve gapless mutation safety.

The developer benchmark uses actual mpv playback events and advancing time-pos, not merely a successful `loadfile` reply:

```bash
python tools/benchmark_youtube_startup.py 'https://www.youtube.com/watch?v=...' --runs 5 --json
python tools/benchmark_youtube_startup.py --query 'On My Way' --runs 5 --json
python tools/benchmark_youtube_startup.py 'https://www.youtube.com/watch?v=...' --candidates --runs 3
```

This opt-in tool uses the network and plays audio through your configured mpv output. It changes no library data. Normal CI uses fake extractors and a loopback HTTP audio fixture, never live YouTube.

The target is **≤2 seconds from Enter on a prefetched result**, not a promise about YouTube or your network. See [measured results and methodology](docs/youtube-startup-performance.md). Development measurements uncovered intermittent five-second DNS stalls before mpv connected to the media host. On affected **glibc/Linux** systems only, a process-local comparison can help diagnose that issue:

```bash
RES_OPTIONS=single-request-reopen python tools/benchmark_youtube_startup.py 'https://www.youtube.com/watch?v=...' --runs 5 --json
```

As of 0.16.4, MeowPlayer applies `single-request-reopen` **process-locally on affected glibc systems** to its YouTube-facing child processes. It does not rewrite system DNS configuration or force a public resolver. Cold extraction, DNS, and remote media opening remain external bottlenecks. `time-pos` confirms playback at mpv's output, not acoustic arrival at a speaker.

MeowPlayer's own performance logs omit direct URLs and header values. **mpv's verbose debug log can still contain signed stream URLs and HTTP headers**; review/redact both log files before sharing them.

### Internet Nest controls — keyboard commands for supervised hunting

```text
Y          search YouTube / open Internet Nest
A          search by artist name
↑ / ↓      choose a search result
Enter      stream selected result
/          normal search again while in Internet Nest
artist:X   artist search from the normal search prompt
Q or Esc   return to the local Music Nest
Space      pause / resume
← / →      seek
```

If `--youtube` is enabled but `yt-dlp` is missing, MeowPlayer fails soft and tells you what is unavailable. Your local library continues to work normally.

## What's new in 0.15.1 — The Lyrics Cat Learned Suspicion

MeowPlayer 0.15.1 is a small release with one very important lesson:

> finding lyrics is not the same thing as finding the **right** lyrics.

The LRCLIB path now validates candidates instead of accepting the first result that happens to contain words.

A real failure that triggered this update looked like this:

```text
local track:      04:18
LRCLIB candidate: 01:02
difference:       03:16
previous verdict: MINE.
new verdict:      absolutely not.
```

Candidate selection now checks the useful identity clues LRCLIB provides:

```text
LRCLIB candidate
      ↓
has lyrics?
      ↓
title plausible?
      ↓
artist plausible?
      ↓
duration plausible?
      ↓
accept
```

Large duration mismatches are treated as a hard rejection instead of something that a good title match can accidentally overpower. If one search result is rejected, MeowPlayer keeps examining later candidates instead of giving up or grabbing the first lyric result it sees.

Downloaded lyric cache keys were also versioned for this change, so lyrics cached by the old overly-trusting matcher are not silently reused after upgrading.

### Plain LRCLIB lyrics are useful now too

LRCLIB does not always have synchronized lyrics. In 0.15.1, a valid result with only `plainLyrics` is still displayed in the **Songbook**.

```text
syncedLyrics available?
        │
        ├── yes → timed Songbook lyrics + playback highlighting
        │
        └── no
             ↓
        plainLyrics available?
             │
             ├── yes → normal scrollable Songbook lyrics
             └── no  → no lyric document
```

MeowPlayer still prefers synchronized lyrics whenever a plausible synchronized candidate exists. Plain downloaded lyrics do **not** receive fake timestamps or pretend to follow playback.

Unsynchronized LRCLIB lyrics are cached separately and can be reused offline. Local sidecar and embedded lyrics still retain priority over a plain online copy.

The cat is still allowed on the internet. It now has to check the nametag first. 🐈‍⬛

### Also in 0.15.1 — the cat has obtained playback authority

Three explicitly opt-in malicious playback modes now exist:

```bash
meowplayer --bad-bad-cat
meowplayer --very-bad-cat
meowplayer --dangerous-cat
```

These are not cosmetic joke modes. They deliberately interfere with playback.

- **Bad Bad Cat** is mildly annoying: rare rewinds, tiny pauses, tiny tempo crimes, and temporary volume theft.
- **Very Bad Cat** retaliates more often, rewinds farther, changes speed more noticeably, restarts tracks, and may choose another track.
- **Dangerous Cat** summons **Bad Larry**, whose job description is essentially "fight the listener." He can deny skips, counter seeks, restart tracks, jump two songs, repeat short sections, trigger multi-action Larry Chains, temporarily alter speed/volume, and otherwise contest playback authority.

Dangerous Cat requires three confirmations. The final one must be typed exactly:

```text
Yes! Summon Bad Larry into The Room!
```

Inside Dangerous Cat mode, `Ctrl+E` starts the emergency dismissal ritual. Bad Larry only leaves after the exact apology:

```text
YES, I APOLOGIZE FOR DISTURBING BAD LARRY
```

Normal OS termination still works. Bad Larry does not trap the process, delete music, alter ratings, rewrite playlists, corrupt the Cat Catalog, or receive permission to vandalize the rest of the system. His jurisdiction is playback.

#### Bad Larry Mathematics Incidents

Dangerous Cat now performs one mathematics roll every **60 seconds**. Each roll has a **1-in-5 chance** of interrupting the listener with a question while the music keeps playing.

When a math incident fires, the difficulty distribution is:

| Difficulty | Chance among math incidents |
| --- | ---: |
| Easy | 50% |
| Medium | 30% |
| Hard | 19% |
| Stochastic Calculus | 0.5% |
| IMO P6-style boss | 0.5% |

Answers are deliberately machine-checkable so the terminal can grade them without pretending to understand arbitrary handwritten proofs. Type `SKIP` to surrender.

Surrender is legal. Bad Larry simply makes it increasingly regrettable:

| Difficulty | First-surrender punishment |
| --- | --- |
| Easy | 5–10 s rewind, +3 Malice |
| Medium | 10–20 s rewind, temporary 0.95x speed, +6 Malice |
| Hard | 20–35 s rewind, temporary 0.90x speed, +10 Malice |
| Stochastic Calculus | restart track, temporary 0.85x speed, +18 Malice |
| IMO P6-style | restart track, temporary 0.82x speed, delayed track hijack, +25 Malice |
| Three-Qubit Final Exam | heavy Larry chain, temporary 0.80x speed, +35 Malice |

Repeated surrender multiplies later penalties by **1.00x, 1.15x, 1.30x, then 1.50x**, capped at 1.50x.

And if the listener somehow answers the IMO P6-style boss correctly:

```text
IMO P6-STYLE: CORRECT

Bad Larry:
No.
```

MeowPlayer immediately opens a **five-minute Three-Qubit Dynamics final exam** containing the full 9-part Hamiltonian / reduced-state / partial-transpose / negativity / Cayley-hyperdeterminant / three-tangle / SLOCC / W-to-GHZ problem. The modal is scrollable while playback continues.

The final exam is intentionally theatrical rather than pretending that a curses text box can rigorously grade a multi-page symbolic derivation. `D` declares a completed derivation, `S` surrenders, and `Ctrl+E` still reaches the Bad Larry dismissal ritual. Timeout or surrender applies the heaviest math punishment.

## What's new in 0.15.0 — The Metadata Cat Goes Online

The cat has finally been granted restricted internet access.

When a track is missing useful information, MeowPlayer can now ask **MusicBrainz** for help and cache the result in the Cat Catalog. This is metadata **enrichment**, not metadata conquest: local tags always win.

MeowPlayer considers fields such as these incomplete:

```text
title = filename fallback
artist = Unknown Artist
album = Unknown Album
album artist = missing
year = missing
genre = missing
```

Then the Metadata Investigation Bureau does approximately this:

```text
local tags / filename
        ↓
anything actually missing?
        ↓ yes
derive a MusicBrainz recording query
        ↓
inspect candidate confidence
        ↓
compare remote duration to the real local file
        ↓
suspicious match? ───── yes ───→ hiss politely and reject it
        │
        no
        ↓
fill missing fields only
        ↓
record source + MusicBrainz ID + query + timestamp
        ↓
Cat Catalog
```

A filename such as:

```text
01 - Beach House - Space Song.flac
```

can provide fallback clues even when the tags say `Unknown Artist` and `Unknown Album`.

The lookup happens in a **single background worker**, so the TUI and playback do not sit around staring at an HTTP request. Requests are serialized/rate-limited instead of unleashing hundreds of metadata cats on MusicBrainz at once.

The cache policy deliberately distinguishes outcomes:

```text
found          → normally reuse for ~30 days
not found      → normally wait ~7 days before asking again
network error  → retryable after ~15 minutes
```

No audio is uploaded, and MeowPlayer does not rewrite the tags inside your MP3/FLAC/etc. files. The enriched values live in MeowPlayer's own library model.

Disable the investigation department for one run:

```bash
meowplayer --no-online-metadata
```

Or permanently set:

```json
"online_metadata_enabled": false
```

The cat will return to judging filenames manually.

## What's new in 0.14.1 — The Cat Stops Lying About Lyrics

0.14.1 fixes the online Songbook state so a background LRCLIB lookup is no longer reported as an immediate false negative.

While a request is pending, Songbook now shows the exact lookup state:

```text
Searching LRCLIB for: Artist Title
```

If the network request fails transiently, MeowPlayer retries once automatically with a longer timeout. A failed request is **not** cached as permanent `None`, so later attempts can recover.

LRCLIB matching is also more forgiving when audio tags are wrong or overly decorated. MeowPlayer now tries, in order:

```text
exact tagged metadata
        ↓
artist + title search
        ↓
filename stem
        ↓
title-only search
```

After synchronized lyrics arrive, Songbook immediately switches to the downloaded document and reports the LRCLIB source. If the lookup genuinely finds nothing, the UI shows the exact query that was tried instead of the generic `No lyrics found` message.

## What's new in 0.14.0 — The Cat Has Opinions and a Five-Star Scale

0.14.0 adds a second layer of personal library data beyond Pawmarks: persistent **0–5 star ratings**, plus a wider Songbook layout that can show lyrics and album art together.

### Ratings beyond Pawmarks

Pawmarks remain a binary favorite / save signal. Ratings are a separate 0–5 judgment stored in the Cat Catalog.

Use:

```text
[  lower rating
]  raise rating
```

In the Music Nest, the selected track is rated. In the Catnip Stash, the selected queued track is rated. In Songbook or normal playback contexts, the current track is rated.

```text
🐾 Space Song — Beach House · ★★★★☆
   Nude — Radiohead · ★★★★★
```

`🐾` means Pawmarked. `★★★★☆` means rated 4/5. They are intentionally independent.

Ratings survive restarts and library rescans. Smart Mix rules can use `rating` as a numeric field:

```text
rating >= 4
genre ~ "Dream Pop" and rating >= 4
favorite = true and rating = 5
```

There is also a built-in **Top Rated** Smart Mix ordered by rating and then play count.

### Lyrics + album-art split Songbook

On a sufficiently wide supported Kitty terminal, Songbook now becomes a real split view:

```text
┌──────────────────────── lyrics ────────────────────────┬──── album art ────┐
│                                                       │                   │
│   >♫< current synchronized lyric                     │      cover        │
│       next lyric                                     │       art         │
│       next lyric                                     │                   │
│                                                       │                   │
└───────────────────────────────────────────────────────┴───────────────────┘
```

The split only activates when artwork is available and the terminal has enough room. Narrow terminals, Termux, unsupported terminals, or tracks without artwork keep the normal full-width lyrics view.

### The review board has become unprofessional

Rating a track now produces intentionally unnecessary cat verdicts and temporary review-board incidents. The quote/incident pool also contains more album-art, lyrics, SQLite, Unicode-star, and terminal-cat nonsense.

None of the extra cat behavior changes files, playback order, ratings by itself, Smart Mix rules, or mpv state.

## What's new in 0.13.1 — The Cat Got Worse

MeowPlayer had become suspiciously respectable, so 0.13.1 restores unnecessary feline behavior without letting any of it touch playback correctness.

### Pet the cat

Press `G` anywhere in the normal TUI to pet the cat.

```text
G
↓
Scritch #1 accepted.
↓
cat reacts
↓
session Scritches counter increases
```

Every tenth scritch gets a special milestone response.

### Cat Incidents

Normal and Maximum Meow modes can now experience harmless temporary **Cat Incidents** in the footer:

```text
🚨 CAT INCIDENT: attempted to eat the waveform. The waveform survived.
```

Incidents are presentation-only. They do not alter playback, files, queues, the Cat Catalog, or mpv state.

### More reactive moods

Meow Level now affects the mascot:

```text
0–10%   → Whispering
11–89%  → normal state-dependent moods
90–100% → Screaming
```

At high volume, `Now Purring` may become **Now YOWLING**. At very low volume, the cat **tiny-purrs**.

Serious Mode suppresses all of this nonsense.

## What's new in 0.13.0 — The Cat Learned to Hear Files Move

MeowPlayer 0.13.0 turns the library from something that is mostly scanned at startup into something that can react while the player is running.

### Custom Smart Mix rules — teach the cat Boolean algebra

Smart Mixes are no longer limited to MeowPlayer's built-ins. Define your own rules in:

```text
~/.config/meowplayer/smart-mixes.json
```

For example:

```text
genre ~ "Dream Pop" and favorite = true
rating >= 4 and play_count >= 5
duration >= 300 and played = false
year >= 2015 and (genre ~ "Rock" or genre ~ "Metal")
```

Rules support boolean logic, parentheses, text matching, numeric comparisons, sorting, and limits. Press `M` to reload them without restarting.

### Live library watching

MeowPlayer now watches the music root recursively. The cat has obtained inotify and is acting like this makes it omniscient. Add, delete, rename, move, or retag music and the Cat Catalog refreshes automatically after a short debounce.

Library state is remapped by **file path**, not by old numeric index, so queue entries, Pounce Bag contents, playback history, Smart Mix sequences, and the current track do not silently turn into different songs after a rescan.

## Highlights — what the cat actually does when nobody is watching

This section is intentionally long because calling MeowPlayer a "tiny terminal wrapper around mpv" has become increasingly difficult to defend in court.

### Music Nest / library — the cat's filing cabinet

- Recursive local-library scanning for MP3, FLAC, OGG, Opus, WAV, M4A, AAC, and WMA
- Persistent SQLite **Cat Catalog** with incremental metadata caching
- Metadata for title, artist, album, album artist, track number, year, genre, and duration
- Automatic invalidation when files change and pruning when files disappear
- Live Watchdog/inotify rescans while the application is running
- Songs, Artists, Albums, Folders/Nests, Pawmarks, Purr History, and Smart Mix views
- Artist → album → track and album → track drill-down navigation
- Unicode **Scent Search** with NFKC normalization + case folding

### Metadata Investigation Bureau

- Optional **MusicBrainz** enrichment for incomplete tracks
- Local tags are never replaced merely because the web disagrees
- Filename `Artist - Title` fallback when tags are sparse
- Confidence checks plus local-vs-remote duration sanity checking
- Serialized/rate-limited network work in a background worker
- Persistent provenance: source, MusicBrainz ID, query, status, and fetch time
- Different cache TTLs for success, genuine miss, and transient failure

### Playback — the part that must remain serious

- Real queueing through **The Catnip Stash**
- `.m3u` / `.m3u8` save + load
- Persistent no-repeat **Pounce Bag** shuffle
- Persistent Previous-history with shuffle-aware forward/back behavior
- Tail-Chase repeat
- Automatic next-track playback
- One-track-ahead **gapless playback** using mpv's internal playlist
- Verification/recovery around awkward mpv handoff states
- Native **ReplayGain** through mpv

### Personal library memory — the cat keeps receipts here too

- Persistent **Pawmarks** favorites
- Independent persistent **0–5 star ratings**
- Play counts, last-played timestamps, and listening history
- Session restore for queue, Pounce Bag, active Smart Mix sequence, volume, current track, and position

### Smart Mixes — playlists generated by a cat with WHERE-clause energy

- Built-ins for Pawmarks, recently played, most played, **Top Rated**, fresh additions, never played, and detected genres
- Custom rule parser with AND / OR / NOT, parentheses, text matching, numeric comparisons, sorting, and limits
- Rating-aware rules such as `rating >= 4`
- No Python `eval()` hiding under the rug

### Songbook / lyrics — unauthorized karaoke department

- Same-name `.lrc` and `.txt` sidecars
- Embedded synchronized/plain lyrics
- Optional **LRCLIB** synchronized lookup
- Background download + persistent local LRC cache
- Truthful `Searching`, `network error`, and `not found` states instead of instantly blaming the song
- Live timestamp following and manual scroll
- Adaptive **lyrics + album-art split view** on wide Kitty terminals

### Terminal / desktop integration — the cat escapes the TUI, slightly

- Kitty album art from embedded or folder artwork
- Pillow-based PNG artwork cache
- Optional **CAVA** FFT spectrum
- Linux MPRIS / D-Bus integration
- `playerctl`, media keys, MPRIS metadata, and `mpris:artUrl`
- Native Termux defaults and narrower phone-friendly behavior

### Settings Nest — edit household rules without touching JSON

- Press `,` from the TUI to open the **Settings Nest**
- Arrow-key navigation with live value previews
- `Enter` / `Space` toggles booleans or cycles values
- `←` / `→` adjusts choices and ReplayGain preamp
- `R` restores the selected option to its default
- Changes are written through MeowPlayer's normal XDG config writer
- Settings clearly say **LIVE** or **NEXT LAUNCH** instead of pretending everything hot-reloads
- Live controls include gapless mode, ReplayGain, lyrics, online lyrics, MusicBrainz, album art, CAVA, and filesystem watching
- Session restore and MPRIS are saved for the next launch

In other words, editing `~/.config/meowplayer/config.json` by hand is still allowed, but no longer a mandatory rite of passage.

### Necessary feline infrastructure — absolutely essential, do not audit

- Reactive moods: Waiting, Purring, Loafing, Zoomies, Tail-Chasing, Guarding Catnip, Whispering, Screaming
- Volume can transform `Now Purring` into **Now YOWLING**
- `G` pets the cat and increments session Scritches
- Every tenth Scritch is treated with unjustified ceremony
- Temporary **Cat Incidents**
- Rating review-board verdicts
- Maximum Meow mode
- Serious Mode for people who need to open the application during a meeting

Underneath the jokes, the normal presentation layer remains separated from playback state. Random Cat Incidents do not get permission to reorder playback, mutate ratings, alter music files, or rewrite Smart Mix rules. The only exception is the explicitly requested malicious playback family: `--bad-bad-cat`, `--very-bad-cat`, and `--dangerous-cat`.

## Quick start — summon the cat

### Arch Linux

Install the system runtime dependency and `pipx`:

```bash
sudo pacman -S mpv python-pipx
pipx ensurepath

# Optional: online YouTube playback
sudo pacman -S yt-dlp

# Optional: make the bars wiggle
sudo pacman -S cava
```

Clone and install:

```bash
git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
pipx install .
```

Release the cat:

```bash
meowplayer
```

Point it at another nest:

```bash
meowplayer ~/Music
meowplayer /mnt/big-drive/music
```

Useful launch variants:

```bash
meowplayer --maximum-meow
meowplayer --serious-mode
meowplayer --bad-bad-cat
meowplayer --very-bad-cat
meowplayer --dangerous-cat
meowplayer --no-mpris
meowplayer --no-restore
meowplayer --rebuild-catalog
meowplayer --no-album-art
meowplayer --gapless-mode weak
meowplayer --replaygain track
meowplayer --replaygain album --replaygain-preamp -1.0
meowplayer --no-lyrics
meowplayer --no-online-lyrics
meowplayer --no-online-metadata
meowplayer --no-visualizer
meowplayer --no-watch
meowplayer --youtube
meowplayer --debug
meowplayer --youtube --debug
meowplayer --log-file /tmp/meowplayer-debug.log
meowplayer --version
```

Update an existing local `pipx` install:

```bash
cd MeowPlayer
git pull
pipx reinstall meowplayer-terminal
```

### Debian / Ubuntu

```bash
sudo apt install python3 mpv
# Optional online playback:
sudo apt install yt-dlp

git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
python3 -m pip install .
meowplayer
```

### Termux / Android

```bash
pkg update
pkg install python python-pip mpv git
# Optional online playback:
pkg install yt-dlp
termux-setup-storage

cd ~
git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
python -m pip install .
meowplayer
```

With no explicit music directory, Termux prefers:

```text
~/storage/music
/storage/emulated/0/Music
~/Music
```

Keep the repository itself in Termux's private home directory; shared storage is fine for the music but is a bad place to raise executable Python kittens.

MPRIS is intentionally disabled on Termux because a normal Linux desktop D-Bus session is usually unavailable there.

## Requirements — food, water, mpv, and one emotionally invested cat

- Python **3.10+**
- `mpv`
- Mutagen
- `dbus-next` for Linux MPRIS integration
- Pillow for album-art normalization/cache
- Watchdog 6.x for live filesystem events
- CAVA *(optional)* for the spectrum
- `yt-dlp` *(optional)* for `--youtube` search and streaming
- Internet access *(optional)* for LRCLIB lyrics, MusicBrainz metadata enrichment, and YouTube playback
- A terminal with curses support
- Unix-domain socket support

Python dependencies live in `pyproject.toml` and are installed by normal `pip` / `pipx` installation.

> 🐾 **Cat translation:** install the dependencies once so the cat does not have to discover `ImportError` live on stage.

If Mutagen is unavailable, MeowPlayer can still discover and play files using filename/folder fallbacks, but rich metadata and cached duration will naturally be worse.

If the internet disappears, the local player still plays. Downloaded lyrics and cached metadata remain available according to what was already stored. YouTube search/streaming simply becomes unavailable. This is a music player, not a login screen with an audio feature.

## Music Nest districts — seven places for the cat to reorganize your music

Press the corresponding key from the Music Nest:

| Key | View |
| --- | --- |
| `1` | Songs |
| `2` | Artists |
| `3` | Albums |
| `4` | Folders / Nests |
| `5` | Pawmarks |
| `6` | Purr History |
| `7` | Smart Mixes |
| `Tab` | Cycle views |

### Songs — the big pile

A flat metadata-aware track list. No hierarchy, no ceremony, just every song lined up while the cat pretends this counts as inventory management.

```text
★ Space Song — Beach House · Depression Cherry · Dream Pop · 05:20
  Nude — Radiohead · In Rainbows · Art Rock · 04:15
```

### Artists — sort the humans into sensible boxes

Artists are navigable rather than decorative group headers. The cat has discovered relational grouping and is being unbearable about it.

```text
Music Nest / Artists

>^.^< Radiohead · 42 track(s) ›
      YOASOBI · 18 track(s) ›
      宇多田ヒカル · 27 track(s) ›
```

Press `Enter`:

```text
Music Nest / Artists / Radiohead

>^.^< In Rainbows (2007) · 10 track(s) ›
      Kid A (2000) · 10 track(s) ›
      OK Computer (1997) · 12 track(s) ›
```

Press `Enter` again:

```text
Music Nest / Artists / Radiohead / In Rainbows

>^.^< 01. 15 Step — Radiohead · 03:57
      02. Bodysnatchers — Radiohead · 04:02
      03. Nude — Radiohead · 04:15
```

Use `B` or `Backspace` to move up one level.

### Albums — rectangular memories, now represented by SQL

Album view opens directly into the selected album's track list.

```text
Music Nest / Albums

>^.^< In Rainbows — Radiohead (2007) · 10 track(s) ›
      Kid A — Radiohead (2000) · 10 track(s) ›
```

### Folders / Nests — the filesystem is already a filing cabinet

Groups tracks by their physical directory under the selected music root. If your music collection is organized by folders, MeowPlayer politely respects the existing nest architecture instead of pretending tags solved civilization.

### Pawmarks — favorites, except the cat stepped on them

Press `F` on an individual track to toggle its persistent favorite state.

```text
★ Nude — Radiohead · In Rainbows · Art Rock · 04:15
```

View `5` shows only Pawmarked tracks.

### Purr History — the database remembers your 2 AM decisions

Every deliberate track start records:

```text
play_count += 1
last_played = now
history event = now
```

Session restoration and simply resuming the current track do not create fake listens.

View `6` is ordered by most recently played:

```text
Nude — Radiohead · played 14× · 04:15
夜に駆ける — YOASOBI · played 9× · 04:21
Space Song — Beach House · played 6× · 05:20
```

## Smart Mixes — playlists generated by a cat with WHERE-clause energy

Press `7` to open **Smart Mixes**.

Unlike ordinary saved playlists, Smart Mixes are generated from the current Cat Catalog every time they are opened.

The cat does not maintain a static playlist spreadsheet. The cat asks the database questions and acts like this was always the plan.

Built-in mixes include:

```text
Pawmarked Mix
Recently Purrred
Most Purrred
Top Rated
Fresh Finds
Never Purrred
Genre Mix · Dream Pop
Genre Mix · Rock
Genre Mix · ...
```

Genre mixes are dynamic: if your library contains a genre tag, MeowPlayer creates a mix for it automatically.

```text
Music Nest / Smart Mixes

>^.^< Pawmarked Mix · 31 track(s) ›
      Recently Purrred · 126 track(s) ›
      Most Purrred · 91 track(s) ›
      Top Rated · 54 track(s) ›
      Fresh Finds · 100 track(s) ›
      Never Purrred · 403 track(s) ›
      Genre Mix · Dream Pop · 47 track(s) ›
```

Press `Enter` to open a mix, then `Enter` on a track to play it.

Smart Mixes are real playback sequences:

```text
Next
  ↓
next track in the active Smart Mix

Pounce Mode
  ↓
Pounce Bag contains only tracks in that Smart Mix
```

The active playback sequence is persisted in runtime state, so restarting MeowPlayer does not silently turn a Smart Mix back into the full library.

Use `B` or `Backspace` to return to the Smart Mix list.

### Custom Smart Mix rules — teach the cat Boolean algebra

Define your own Smart Mixes in:

```text
~/.config/meowplayer/smart-mixes.json
```

or the equivalent `XDG_CONFIG_HOME` path.

A ready-to-copy example is included at:

```text
examples/smart-mixes.json
```

Example:

```json
{
  "mixes": [
    {
      "name": "Late Night Purrs",
      "description": "Dreamy favorites with some listening history.",
      "rule": "genre ~ \"Dream\" and favorite = true and rating >= 4",
      "sort": "-rating",
      "limit": 100
    },
    {
      "name": "Long Unplayed Tracks",
      "rule": "duration >= 300 and played = false",
      "sort": "artist"
    }
  ]
}
```

The rule language is parsed by MeowPlayer itself. It does **not** use Python `eval()`.

This is important because “let the cat execute arbitrary Python from a playlist rule” was rejected by the architectural review board, which for once made a good decision.

Supported fields:

```text
title
artist
album
album_artist
genre
year
filename
folder
duration
play_count      (alias: plays)
rating
favorite        (aliases: pawmarked, favourite)
played
tagged
last_played_ns
added_at_ns
```

Supported operators:

| Operator | Meaning |
| --- | --- |
| `=` / `==` | equals |
| `!=` | not equal |
| `~` | contains, case-insensitive |
| `!~` | does not contain |
| `>` / `>=` | numeric/ordered comparison |
| `<` / `<=` | numeric/ordered comparison |
| `and` | both expressions must match |
| `or` | either expression may match |
| `not` | invert an expression |
| `(...)` | control precedence |

Examples:

```text
genre ~ "Dream Pop" and favorite = true
rating >= 4 and play_count >= 3
duration < 300 and play_count >= 5
year >= 2015 and (genre ~ "Rock" or genre ~ "Metal")
not artist = "Unknown Artist" and tagged = true
```

`sort` accepts a field name. Prefix it with `-` for descending order:

```json
"sort": "-play_count"
```

`limit` optionally caps the generated playlist.

Press `M` after editing `smart-mixes.json` to reload custom rules without restarting MeowPlayer. Invalid rules are skipped instead of breaking the built-in mixes.

To start from the repository example:

```bash
mkdir -p ~/.config/meowplayer
cp examples/smart-mixes.json ~/.config/meowplayer/smart-mixes.json
```

## Scent Search — grep, but with whiskers

Press `/` in the Music Nest.

The cat then sniffs title, artist, album, year, genre, filename, and path until your library stops being mysterious.

Search checks:

- title
- artist
- album
- album artist
- year
- genre
- filename
- folder/path

For example:

```text
SCENT SEARCH > dream pop_       (18 meows)
SCENT SEARCH > 宇多田ヒカル_     (8 meows)
SCENT SEARCH > 夜に駆ける_       (1 meow)
```

Search accepts full Unicode input through `curses.get_wch()` and normalizes text with Unicode NFKC + case folding.

Controls while searching:

| Key | Action |
| --- | --- |
| Type | Refine the scent |
| `Backspace` | Delete a character |
| `Enter` | Keep the current filter |
| `Esc` | Clear the filter |

## The Cat Catalog — SQLite remembers what the cat absolutely will not

The **Cat Catalog** is MeowPlayer's persistent SQLite library model.

Without it, the cat would rediscover the same 842 songs every launch and call that “freshness.”

Default location:

```text
~/.local/share/meowplayer/library.sqlite3
```

With `XDG_DATA_HOME`, the database follows that location instead.

It stores ordinary library facts:

```text
path
library root
size + mtime
title
artist
album
album artist
track number
year
genre
duration
folder
filename
tagged/fallback status
```

It also stores MeowPlayer-specific memory:

```text
Pawmark
0–5 rating
play count
last played
added-at time
listening-history events
```

And as of schema v5, it can remember online metadata provenance:

```text
online lookup status
source
MusicBrainz recording ID
query
fetch timestamp
```

### Incremental metadata caching — cold sniff vs warm sniff

Cold sniff:

```text
music file
   ↓
Mutagen reads tags + duration
   ↓
Cat Catalog stores metadata
```

Warm sniff:

```text
path + size + mtime
        ↓
   unchanged?
   /       \
 yes       no
  ↓         ↓
SQLite    Mutagen
 cache    re-sniff
```

A normal warm launch can therefore look like:

```text
Cat Catalog checked: 842 remembered, 3 re-sniffed, 1 vanished; 821/844 tagged meow(s).
```

### Rebuild metadata — make the cat sniff every file again

```bash
meowplayer --rebuild-catalog
```

This invalidates cached file metadata for the selected root and forces a fresh local sniff while preserving personal library state such as:

- Pawmarks
- ratings
- play counts
- last-played values
- listening history

Changed/rebuilt metadata can become eligible for fresh online enrichment again when fields remain incomplete.

Do **not** casually treat `library.sqlite3` as disposable cache. Deleting it leaves the audio files untouched, but removes MeowPlayer-owned Pawmarks, ratings, play history, cached enrichment, and other database state.

### Schema migrations — the cat has a database age and refuses amnesia

The Cat Catalog is versioned and migrated forward. Older schema upgrades are designed to preserve personal library data even when cacheable metadata needs to be re-sniffed.

MeowPlayer 0.8.0 also moved the database from:

```text
~/.cache/meowplayer/library.sqlite3
```

to:

```text
~/.local/share/meowplayer/library.sqlite3
```

and migrates the legacy database automatically when appropriate.

## Online metadata enrichment — the Metadata Investigation Bureau has a tiny badge

MeowPlayer's online metadata layer exists to answer a narrow question:

> "This track is missing information. Can we fill the holes without pretending the internet knows my library better than I do?"

The answer is **yes, cautiously**.

### Local-first precedence — the internet does not outrank your tags

For every field, local data wins when it is already meaningful.

MeowPlayer is willing to ask the internet for help. It is not willing to let the internet walk into your library, move the furniture, and insist it knows better.

```text
Local Artist = Beach House
Remote Artist = something else
        ↓
keep Beach House
```

But:

```text
Local Artist = Unknown Artist
Remote Artist = Beach House
        ↓
fill Beach House
```

The same missing-only rule applies to title, album, album artist, year, and genre.

### Finding the song — Detective Cat enters the room

When tags are sparse, MeowPlayer can derive fallback clues from filenames such as:

```text
01 - Artist - Title.flac
```

MusicBrainz candidates must clear a confidence threshold. When both sides have useful durations, MeowPlayer also compares the MusicBrainz recording length against the actual local audio duration and rejects large mismatches.

That matters for covers, live versions, remasters, reprises, and the approximately seventeen billion songs named `Home`.

### Background worker and cache policy — one detective, not 300 feral threads

Network I/O happens away from the curses loop. One metadata worker processes jobs serially, while the main thread remains responsible for merging results into in-memory `TrackMetadata` and writing SQLite.

```text
TUI / playback / SQLite
          ↕ result queue
MusicBrainz worker
          ↓
rate-limited HTTP
```

Cached outcomes are intentionally not treated equally:

| Result | Normal refresh window |
| --- | --- |
| Found | ~30 days |
| Not found | ~7 days |
| Network/transient failure | ~15 minutes |

The catalog also records the MusicBrainz source/ID/query used, which makes the enrichment traceable instead of magical.

### What gets sent — evidence leaving the nest

MeowPlayer sends MusicBrainz **search queries derived from available tags/filename clues**. It does not upload the audio file. Local duration is used for candidate validation.

### Disable it — dismiss the detective

One launch:

```bash
meowplayer --no-online-metadata
```

Persistent config:

```json
"online_metadata_enabled": false
```

The rest of MeowPlayer continues normally.

## Live filesystem watching — the cat hears a file move from three rooms away

MeowPlayer 0.13.0 watches the selected music root recursively using Watchdog.

Add a song, rename an album, delete a file, retag something at 02:14 — the cat notices. Eventually. After the debounce. We are still professionals.

On Linux, Watchdog uses the kernel's **inotify** backend. The observer thread only records events; SQLite, metadata parsing, curses updates, and playback-state remapping remain in MeowPlayer's main thread.

Events are debounced:

```text
copy / retag / rename
      ↓
several filesystem events
      ↓
Watchdog observer
      ↓
~0.75 s quiet period
      ↓
one Cat Catalog refresh
```

Because the Cat Catalog is incremental, a refresh does not imply reparsing the entire library. Unchanged files remain SQLite cache hits, while new or modified tracks are re-read with Mutagen and deleted paths are pruned.

During a live rescan MeowPlayer preserves state by absolute path:

```text
current track
Catnip Stash
Pounce Bag
Previous-history
active Smart Mix sequence
current selection
      ↓
old numeric indices discarded
      ↓
new filesystem scan
      ↓
paths remapped to new indices
```

That prevents inserting a new alphabetically earlier song from turning a queued numeric index into the wrong track.

If the currently playing file itself disappears, MeowPlayer stops it rather than retaining an invalid library index.

Filesystem watching is enabled by default:

```json
"filesystem_watch_enabled": true
```

Disable it for one run:

```bash
meowplayer --no-watch
```

## Lyrics / Songbook — the cat has obtained the words and will now sing incorrectly

Press `L` to open the **Songbook**.

This is where the terminal music player briefly decides it is also a karaoke machine, except nobody promised the cat can carry a tune.

MeowPlayer resolves lyrics in this order:

```text
same-name .lrc sidecar
        ↓
downloaded LRCLIB cache
        ↓
embedded synchronized lyrics
        ↓
LRCLIB synchronized lookup (background)
        ↓
same-name .txt sidecar
        ↓
embedded plain lyrics
```

A local sidecar can simply live beside the song:

```text
Music/
└── Album/
    ├── 01 Song.flac
    └── 01 Song.lrc
```

Synchronized LRC example:

```text
[00:12.40]First line
[00:17.85]Second line
[00:22.10]Third line
```

Multiple timestamps per line and standard `[offset:+/-milliseconds]` tags are supported.

### Online LRCLIB lookup — ask the internet what the cat forgot

If synchronized lyrics are not available locally, MeowPlayer can ask **LRCLIB** in the background.

The UI distinguishes real states instead of immediately declaring defeat:

```text
Searching LRCLIB for: Artist Title
        ↓
found        → load + cache synchronized LRC
not found    → report the query that actually missed
network fail → report failure and allow a later retry
```

Transient network failure gets an automatic retry. Failed requests are not cached as permanent `None`, so one bad connection cannot curse the track for the rest of the session.

Search fallback is intentionally forgiving of messy files: MeowPlayer can fall back from tagged metadata to artist/title search, filename stem, and title-only search.

Successful downloads are cached under:

```text
~/.cache/meowplayer/lyrics/
```

or `$XDG_CACHE_HOME/meowplayer/lyrics/`. Once cached, they can be reused later without another network lookup. A user-provided same-name `.lrc` still has priority.

Disable only online lookup:

```bash
meowplayer --no-online-lyrics
```

Disable the entire lyrics subsystem:

```bash
meowplayer --no-lyrics
```

Persistent config:

```json
"lyrics_enabled": true,
"lyrics_online_enabled": true
```

### Songbook controls — pages, paws, and poor vocal technique

| Key | Action |
| --- | --- |
| `L` | Open / close Songbook |
| `↑` / `↓` | Scroll manually |
| `Enter` | Resume timestamp following |
| `N` / `P` | Next / previous track |
| `[` / `]` | Lower / raise rating |
| `Space` | Paws / resume |

The active synchronized line is highlighted and centered while follow mode is active.

On a sufficiently wide supported Kitty terminal, the Songbook may split itself:

```text
┌──────────────────── Songbook ────────────────────┬──── cover ────┐
│                                                 │               │
│   previous lyric                                │   album art   │
│ >♫< current lyric                               │               │
│   next lyric                                    │               │
│                                                 │               │
└─────────────────────────────────────────────────┴───────────────┘
```

Narrow terminals, unsupported terminals, Termux, or tracks without artwork simply keep the full-width text view. The cat has been instructed not to demand a 4K monitor.

## Audio visualizer — scientifically measuring the wiggles

MeowPlayer 0.12.0 added a real frequency spectrum to the TUI using **CAVA**.

This contributes almost nothing to the acoustic signal and approximately 73% to the feeling that your terminal has become a tiny nightclub.

CAVA is optional. If it is missing, MeowPlayer continues normally with no visualizer.

On Arch Linux:

```bash
sudo pacman -S cava
```

When available, MeowPlayer starts CAVA in raw ASCII mode and consumes its FFT bar values instead of letting CAVA draw its own terminal interface.

The spectrum appears directly beneath the playback progress bar:

```text
▁▂▄▆█▇▅▃▂▁▂▅▇█▆▄▂▁
```

Press `V` to toggle it at runtime.

The generated CAVA configuration uses the default audio monitor source when available, so the visualizer observes the system output path rather than decoding the music file again inside Python.

Disable it for one launch with:

```bash
meowplayer --no-visualizer
```

Persistent config:

```json
"visualizer_enabled": true
```

Because the default sink monitor can contain audio from other applications, the displayed spectrum may react to other system audio playing at the same time.

## Album art — your terminal now contains a JPEG somehow

MeowPlayer 0.10.0 added real album artwork directly inside **Kitty terminals** using Kitty's terminal graphics protocol.

The terminal was text. Then the cat found graphics protocols. We all live with the consequences.

Album art is enabled automatically when:

- MeowPlayer is running directly in Kitty / `xterm-kitty`
- the terminal is large enough to preserve the TUI layout
- Pillow is available
- a cover can be resolved
- MeowPlayer is not inside tmux
- `--no-album-art` was not supplied

The cover is rendered in the upper-right portion of the normal player while the curses UI remains usable. In Songbook, wide terminals instead use the artwork as a dedicated right-side split panel beside the lyrics.

MeowPlayer looks for art in this order:

1. embedded artwork in the audio file
2. common cover files beside the track

Embedded artwork support covers common MP3/FLAC/MP4/Vorbis-style metadata. Folder artwork matching is case-insensitive and recognizes names such as:

```text
cover.jpg
cover.png
cover.webp
folder.jpg
folder.png
front.jpg
front.png
album.jpg
album.png
```

Artwork is converted to PNG and cached at:

```text
~/.cache/meowplayer/album-art/
```

or the equivalent `XDG_CACHE_HOME` path. Audio files are never modified.

Disable terminal artwork for one launch with:

```bash
meowplayer --no-album-art
```

The persistent config also supports:

```json
"album_art_enabled": true
```

If the terminal is unsupported, the window is too small, or no cover exists, MeowPlayer simply falls back to the normal text UI.

Resolved covers are also exported over MPRIS as `mpris:artUrl`, allowing compatible desktop widgets and media controls to reuse the same cached image.

## Gapless playback and ReplayGain — the cat takes audio continuity personally

MeowPlayer 0.11.0 upgrades the audio engine in two places.

### Gapless playback — no awkward silence between zoomies

MeowPlayer no longer waits for a song to reach EOF before deciding what comes next.

The next track is already crouched behind the current one, prepared to pounce the instant mpv reaches the boundary.

While a track is playing, it resolves the next track using the same playback priority as the rest of the app:

```text
Catnip Stash
      ↓
Pounce Bag
      ↓
active Smart Mix
      ↓
normal sequential library
```

That next track is inserted into mpv's internal playlist **before the current track ends**:

```text
current decoder
      │
      ├──────────────┐
      ▼              ▼
 Track A          Track B already primed
      │              │
      └──── boundary ┘
             ↓
       mpv advances
             ↓
MeowPlayer commits queue/history state
             ↓
       Track C is primed
```

This lets mpv keep its audio output alive across compatible files instead of MeowPlayer tearing down one file and loading the next only after EOF.

The default is:

```json
"gapless_mode": "weak"
```

Available modes:

| Mode | Behavior |
| --- | --- |
| `weak` | Default. Keeps the audio device open when mpv can safely reuse the output format; may reopen it when formats differ. |
| `yes` | Strongest gapless behavior. Keeps the first output format for later tracks, which may require resampling. |
| `no` | Disables MeowPlayer's gapless preload and mpv gapless output mode. |

Override it for one launch:

```bash
meowplayer --gapless-mode weak
meowplayer --gapless-mode yes
meowplayer --gapless-mode no
```

Queue edits, Pounce Mode changes, Tail-Chase changes, and Smart Mix playback all re-prime the upcoming file so the internal mpv playlist remains consistent with MeowPlayer's own Next logic.

### ReplayGain — volume diplomacy

ReplayGain uses gain values already stored in the audio file's metadata. MeowPlayer delegates the actual gain calculation and clipping protection to mpv.

The cat has opinions about loudness. Fortunately, mpv has mathematics.

The default mode is:

```json
"replaygain_mode": "track"
```

Modes:

| Mode | Behavior |
| --- | --- |
| `track` | Normalize each track independently. Good for shuffled libraries and mixed playlists. |
| `album` | Prefer album gain for preserving intended loudness relationships within an album; falls back to track gain when album gain is unavailable. |
| `no` | Disable ReplayGain adjustment. |

MeowPlayer also defaults to:

```json
"replaygain_preamp": 0.0
```

and starts mpv with clipping protection enabled:

```text
--replaygain-clip=no
```

Examples:

```bash
meowplayer --replaygain track
meowplayer --replaygain album
meowplayer --replaygain no
meowplayer --replaygain track --replaygain-preamp -1.5
```

ReplayGain only changes loudness when the file contains usable ReplayGain metadata. Files without those tags remain effectively unadjusted with the default preamp.

## Pounce Bag shuffle — random, but not goldfish-random

Pounce Mode is not independent `random.choice()` selection anymore.

The cat is allowed to be chaotic. It is not allowed to play the same three songs forever and call that shuffle.

It uses a real no-repeat **Pounce Bag**:

```text
all tracks except current
          ↓
      shuffle once
          ↓
     Pounce Bag
          ↓
  consume one by one
          ↓
        empty?
          ↓
refill excluding current
```

Every eligible track gets one turn before a new shuffle cycle starts.

The UI shows the remaining bag:

```text
Pounce: ON (37 left)
```

The exact next song stays a mystery:

```text
Next Treat: mystery meow (37 left in Pounce Bag)
```

The bag is persisted in the state file, so restarting MeowPlayer does not reset the shuffle cycle.

Playback Previous-history is also persistent. In Pounce Mode:

```text
A → B → C → D

Previous
   ↓
   C

Previous
   ↓
   B

Next
 ↓
 C
```

When going backward, the track you leave is placed at the top of the Pounce Bag so forward navigation remains natural.

The Catnip Stash always has priority over the Pounce Bag.

## The Catnip Stash — a queue, but legally more delicious

The queue is officially called **The Catnip Stash**.

This naming decision survived code review.

From a leaf-level track, press `A` to stash it.

Press `Q` to switch between the Music Nest and Catnip Stash.

Queue playback has priority:

```text
Catnip Stash
     ↓
Pounce Bag / sequential library
```

Inside the stash:

| Key | Action |
| --- | --- |
| `↑` / `↓` | Select queued track |
| `Enter` | Play and consume selected item |
| `D` | Remove |
| `K` | Move up |
| `J` | Move down |
| `C` | Clear stash |
| `W` | Save as `.m3u` |
| `O` | Load `.m3u` / `.m3u8` |
| `Q` | Return to Music Nest |

The default playlist path is:

```text
<current music root>/catnip-stash.m3u
```

Loaded playlist entries must resolve to tracks already indexed in the current library.

## Main controls — keyboard treaty between human and cat

| Key | Action |
| --- | --- |
| `↑` / `↓` | Choose |
| `Enter` | Open artist/album group or play track |
| `1`–`7` | Select library view |
| `Tab` | Cycle library view |
| `B` / `Backspace` | Go up one drill-down level |
| `/` | Scent Search |
| `F` | Toggle Pawmark |
| `[` / `]` | Lower / raise 0–5 star rating |
| `A` | Add track to Catnip Stash |
| `Q` | Toggle Music Nest / Catnip Stash |
| `L` | Toggle Songbook / lyrics view |
| `V` | Toggle live spectrum visualizer |
| `M` | Reload custom Smart Mix rules |
| `G` | Pet the cat / add one Scritch |
| `,` | Open the Settings Nest |
| `Space` | Paws / resume |
| `←` / `→` | Scritch backward / forward 5 seconds |
| `N` | Next meow |
| `P` | Previous purr |
| `+` / `-` | Adjust Meow Level |
| `S` | Toggle Pounce Mode |
| `R` | Toggle Tail-Chase |
| `X` | Quit / escape before the cat notices |

## Settings Nest — the cat has obtained a control panel

Press `,` from the main TUI to open the **Settings Nest**.

```text
SETTINGS NEST — 11 household rule(s)

  Remember yesterday's nap              [     ON     ]  NEXT LAUNCH
  Desktop cat privileges                [     ON     ]  NEXT LAUNCH
  Terminal rectangle pictures           [     ON     ]  LIVE
>^.^< No awkward silence between zoomies [    weak    ]  LIVE
  Volume diplomacy                      [   track    ]  LIVE
  Extra loudness seasoning              [  +0.0 dB   ]  LIVE
  Songbook                              [     ON     ]  LIVE
  Internet lyric cats                   [     ON     ]  LIVE
  Metadata detective cat                [     ON     ]  LIVE
  Wiggly fence                          [     ON     ]  LIVE
  Hear files move through walls         [     ON     ]  LIVE
```

Controls:

| Key | Settings Nest action |
| --- | --- |
| `↑` / `↓` | Move the paw |
| `←` / `→` | Change/cycle the selected value |
| `Enter` / `Space` | Toggle or advance the selected value |
| `R` | Reset the selected option to its default |
| `,` / `Q` / `Esc` | Leave Settings Nest and return to the previous view |
| `X` | Quit MeowPlayer |

Settings marked **LIVE** update the running player immediately. Settings marked **NEXT LAUNCH** are saved immediately but intentionally do not attempt a risky hot restart of their subsystem.

Current live settings include:

```text
album art
gapless mode
ReplayGain mode
ReplayGain preamp
lyrics
online lyrics
MusicBrainz metadata
CAVA visualizer
filesystem watching
```

The two deliberate next-launch settings are:

```text
restore_session
mpris_enabled
```

MPRIS stays next-launch because disconnecting and re-registering a D-Bus media service in the middle of normal playback is substantially more exciting than a settings screen needs to be.

Every change still goes through the ordinary XDG config path:

```text
~/.config/meowplayer/config.json
```

So Settings Nest is not a second configuration system. It is simply a TUI editor for the same household rules.

> **The cat may now edit configuration. The cat still does not get arbitrary JSON access.**

## Persistent config and state — because the cat has a memory now, unfortunately

MeowPlayer follows the XDG base-directory layout.

### Config — permanent household rules

```text
~/.config/meowplayer/config.json
```

Custom Smart Mix definitions:

```text
~/.config/meowplayer/smart-mixes.json
```

Representative config:

```json
{
  "album_art_enabled": true,
  "filesystem_watch_enabled": true,
  "gapless_mode": "weak",
  "lyrics_enabled": true,
  "lyrics_online_enabled": true,
  "online_metadata_enabled": true,
  "mpris_enabled": true,
  "music_dir": "/home/you/Music",
  "replaygain_mode": "track",
  "replaygain_preamp": 0.0,
  "restore_session": true,
  "visualizer_enabled": true
}
```

### Runtime state — what the cat was doing five minutes ago

```text
~/.local/state/meowplayer/state.json
```

It remembers things such as:

- volume / Meow Level
- Pounce Mode
- Tail-Chase
- current library view
- last track + playback position
- Catnip Stash
- remaining Pounce Bag
- Previous-history
- active Smart Mix playback sequence

State is written periodically and again during shutdown.

Session restore loads the saved track at its saved position **paused**. Launching MeowPlayer is not supposed to surprise the entire room with whatever you were listening to at 02:17 yesterday.

## MPRIS and media keys — the cat gains limited desktop privileges

On Linux desktops, MeowPlayer exposes:

> 🐾 **Important:** “desktop privileges” means media controls, not root access. Bad Larry has been informed of this distinction.

```text
org.mpris.MediaPlayer2.meowplayer
```

Supported controls include:

- Play / Pause / PlayPause
- Next / Previous
- Stop
- relative and absolute seek
- volume
- Shuffle / Pounce Mode
- LoopStatus / Tail-Chase
- remote Quit

MPRIS metadata includes:

- title
- artist
- album
- album artist
- genre
- file URI
- duration
- album-art URL when available

Test with `playerctl`:

```bash
sudo pacman -S playerctl

playerctl -l
playerctl --player=meowplayer status
playerctl --player=meowplayer metadata
playerctl --player=meowplayer play-pause
playerctl --player=meowplayer next
playerctl --player=meowplayer previous
```

If `playerctl` says no players were found:

```bash
python -c 'import dbus_next; print("dbus-next: OK")'
busctl --user list >/dev/null && echo "user D-Bus: OK"
busctl --user list | grep org.mpris.MediaPlayer2.meowplayer
```

MeowPlayer stays usable if MPRIS registration fails and displays the startup error in its status line.

## Cat chaos — carefully sandboxed workplace misconduct

MeowPlayer contains a presentation layer whose job description can best be summarized as **unhelpful cat**.

It may:

- rotate increasingly questionable footer quotes
- trigger temporary **Cat Incidents**
- count Scritches from the `G` key
- celebrate every tenth Scritch as if a release candidate just passed certification
- change the mascot according to playback state and Meow Level
- rename `Now Playing` to `Now Purring`, `Now tiny-purring`, or **Now YOWLING**
- issue melodramatic rating verdicts
- convene an unauthorized review board
- comment on SQLite, D-Bus, Unicode stars, album art, lyrics, and the Metadata Investigation Bureau
- claim credit for successful background work it absolutely did not personally perform

It may **not**, merely because a random Cat Incident fired:

- modify your audio files
- add/remove queue entries
- reorder the Pounce Bag
- change a rating
- toggle a Pawmark
- rewrite Smart Mix rules
- alter gapless/ReplayGain state
- write different metadata
- initiate network work

Those actions only happen through actual feature logic or explicit user input.

The malicious cat modes are the deliberate exception for **playback only**. When you launch one of those flags, you are explicitly opting into a cat that may seek, pause, resume, restart, skip, change temporary playback speed, temporarily lower mpv volume, or choose another track.

Even Bad Larry does not get permission to damage data.

```text
normal cat jokes      = presentation chaos
malicious cat modes   = opt-in playback chaos
music files / ratings = still off limits
```

The distinction is deliberate: MeowPlayer can become obnoxious on request without becoming destructive.

## Cat modes

### Normal mode — recommended dosage

```bash
meowplayer
```

All normal features, plus the standard amount of feline misconduct.

### Serious Mode — the cat is wearing a tie

```bash
meowplayer --serious-mode
```

Uses conventional labels and suppresses most feline presentation while keeping the actual player features intact.

Useful for:

- screen sharing
- classrooms
- work
- pretending this repository contains no `G = pet cat` keybinding

### Maximum Meow — insufficiently peer-reviewed

```bash
meowplayer --maximum-meow
```

For situations where Normal Mode fails the laboratory's minimum cat requirement.

### Bad Bad Cat — mildly criminal DJ

```bash
meowplayer --bad-bad-cat
```

The cat occasionally touches the controls. Expect rare 2–5 second rewinds, sub-second pauses, tiny tempo shifts, temporary volume theft, and occasional retaliation when you press transport controls.

### Very Bad Cat — hostile DJ

```bash
meowplayer --very-bad-cat
```

The cat now believes playback is a shared custody arrangement. Interference is more frequent and stronger: longer rewinds, more obvious tempo changes, restarts, counter-seeks, skip resistance, and occasional track hijacking.

### Dangerous Cat — summon Bad Larry

```bash
meowplayer --dangerous-cat
```

This mode is intentionally annoying. It requires **three confirmations** before the player starts. The final phrase is exact and case-sensitive:

```text
Yes! Summon Bad Larry into The Room!
```

Bad Larry can trigger frequent spontaneous sabotage and directly retaliate against Next, Previous, Pause, Seek, Volume, and Quit attempts. As his Malice rises, the UI reports declining **Human Authority** and stronger events such as repeated-section abuse and **Larry Chains**.

A normal `X` quit attempt can be denied while Bad Larry is active. Use `Ctrl+E` for the in-app emergency dismissal ritual and type exactly:

```text
YES, I APOLOGIZE FOR DISTURBING BAD LARRY
```

`Ctrl+C`, terminal closure, `SIGTERM`, and ordinary OS process control remain real escape hatches. Dangerous Cat does not install persistence, modify shell configuration, delete files, or raise playback above the user's configured Meow Level.

Serious Mode, Maximum Meow, Bad Bad Cat, Very Bad Cat, and Dangerous Cat are mutually exclusive because even this project has boundaries.

## Cat moods — telemetry, but emotionally compromised

The mascot reacts to player state because apparently “idle-active=false” was not expressive enough:

| State | Mood |
| --- | --- |
| Nothing playing | Waiting |
| Normal playback | Purring |
| Paused | Loafing |
| Pounce Mode | Zoomies |
| Tail-Chase | Tail-Chasing |
| Catnip queued | Guarding Catnip |
| Meow Level ≤10% | Whispering |
| Meow Level ≥90% | Screaming |

```text
 /\_/\   ♫ MEOWPLAYER v0.17.1 — Loafing
( -.- )
 > ^ <  ...
```

## Feline vocabulary — translation guide for responsible adults

| Conventional software term | MeowPlayer has decided to call it |
| --- | --- |
| Library | Music Nest |
| Folders | Nests |
| Search | Scent Search |
| Queue | The Catnip Stash |
| Favorites | Pawmarks |
| Rating | Cat verdict / stars |
| Listening history | Purr History |
| Smart playlists | Smart Mixes |
| Lyrics | Songbook |
| Online metadata enrichment | Metadata Investigation Bureau |
| Audio visualizer | Spectrum |
| Now Playing | Now Purring |
| Volume | Meow Level |
| Shuffle | Pounce Mode |
| Shuffle pool | Pounce Bag |
| Repeat | Tail-Chase |
| Pause | Paws |
| Seek | Scritch |
| Save playlist | Bury stash |
| Load playlist | Dig up stash |
| Press `G` | Pet the cat, obviously |

Serious Mode translates most of the visible vocabulary back into something fit for a project-management meeting.

## Architecture — far too much engineering for a cat

```text
                           LOCAL MUSIC FILES
                                  │
                 recursive scan + Watchdog/inotify
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
              Mutagen                       file changes
          tags / duration                        │
                  │                              │
                  └──────────────┬───────────────┘
                                 ▼
                       ┌─────────────────┐
                       │   CAT CATALOG   │
                       │     SQLite      │
                       ├─────────────────┤
                       │ file metadata   │
                       │ Pawmarks        │
                       │ 0–5 ratings     │
                       │ Purr History    │
                       │ lookup state    │
                       │ provenance      │
                       └────────┬────────┘
                                │
          ┌─────────────────────┼──────────────────────┐
          │                     │                      │
          ▼                     ▼                      ▼
   MusicBrainz worker     Smart Mix engine      library views
   (missing fields)        + rule parser      + Scent Search
          │
          └── result queue ───────────────┐
                                         ▼
                                  MAIN TUI THREAD
                               curses + library state
                                │              │
                     ┌──────────┘              └──────────┐
                     ▼                                    ▼
              Catnip Stash                         Lyrics manager
              Pounce Bag                           local / embedded
              playback sequence                    + LRCLIB thread
                     │                                    │
                     └──────────────┬─────────────────────┘
                                    ▼
                             MeowPlayer scheduler
                                    │
                             mpv JSON IPC
                                    │
                      one-track-ahead gapless priming
                                    │
                                    ▼
                                   mpv
                         decoding + ReplayGain + audio

                 Kitty art / CAVA             MPRIS / D-Bus
                        │                          │
                        ▼                          ▼
                   terminal UI              playerctl/media keys
```

### Responsibility boundaries — who is responsible when the cat denies everything

- **Python / MeowPlayer** owns the UI, library model, queue, Pounce Bag, ratings, Pawmarks, Smart Mixes, persistence, lyrics state, search, metadata merge policy, and gapless scheduling decisions.
- **mpv** owns decoding, actual audio output, seeking, ReplayGain processing, and the final handoff between primed playlist entries.
- **Mutagen** reads local tags, embedded artwork, embedded lyrics where supported, and stream duration.
- **SQLite** persists the Cat Catalog.
- **Watchdog** supplies filesystem events; library mutation remains in the main application logic.
- **MusicBrainz** is an optional enrichment source for missing metadata.
- **LRCLIB** is an optional synchronized-lyrics source.
- **Pillow** normalizes artwork into cached PNGs.
- **CAVA** optionally supplies spectrum values.
- **MPRIS / D-Bus** exposes desktop media controls.

Most importantly, the cat-chaos presentation layer sits **above** these systems rather than being allowed to rummage through them.

In architectural terms: the jokes may observe the machine. The jokes do not get database write access just because the footer announced a CAT INCIDENT.

## Build packages — put the cat in a wheel (and an sdist)

Install the build frontend:

The cat has requested reproducible packaging and a cardboard box. Only one of those ships to PyPI.

```bash
python -m pip install build
```

Build wheel + source distribution:

```bash
python -m build
```

Output:

```text
dist/
├── meowplayer_terminal-0.17.1-py3-none-any.whl
└── meowplayer_terminal-0.17.1.tar.gz
```

The installed CLI is still:

```text
meowplayer
```

## Project structure — anatomy of the creature

```text
MeowPlayer/
├── meowplayer.py              # TUI, playback state, orchestration, cat
├── album_art.py               # artwork resolution/cache/Kitty rendering
├── lyrics_support.py          # LRC/plain lyrics + LRCLIB
├── online_metadata.py         # MusicBrainz enrichment worker/client
├── library_watcher.py         # Watchdog event collection/debounce
├── meow_catalog.py            # SQLite Cat Catalog + migrations
├── meow_smart.py              # Smart Mix parser/generator
├── meow_persistence.py        # XDG config + runtime state
├── settings_nest.py           # Settings Nest definitions/value logic
├── meow_logging.py            # rotating debug logs + XDG log paths
├── mpris_support.py           # Linux MPRIS bridge
├── visualizer.py              # CAVA raw spectrum integration
├── youtube_online.py          # experimental yt-dlp YouTube catalog
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE                    # the only adult in the room
├── examples/
│   └── smart-mixes.json
├── tests/
│   ├── test_album_art.py
│   ├── test_audio.py
│   ├── test_catalog.py
│   ├── test_debug_logging.py
│   ├── test_goofy.py
│   ├── test_lyrics.py
│   ├── test_online_metadata.py
│   ├── test_rescan.py
│   ├── test_shuffle.py
│   ├── test_smart.py
│   ├── test_visualizer.py
│   ├── test_watcher.py
│   └── test_youtube_online.py
└── .github/
    └── workflows/
        ├── comprehensive-test.yml
        └── package-smoke.yml
```

There is a non-zero amount of code whose purpose is to make a cat react to volume. This is documented here for transparency.

There is also a non-zero amount of code ensuring that the code which makes the cat react to volume does not break gapless playback. This project has priorities.

## Development and tests — prove the cat still works

Compile first-party modules:

```bash
python -m py_compile \
  meowplayer.py \
  album_art.py \
  lyrics_support.py \
  online_metadata.py \
  library_watcher.py \
  meow_catalog.py \
  meow_smart.py \
  meow_persistence.py \
  meow_logging.py \
  mpris_support.py \
  visualizer.py \
  youtube_online.py
```

Run the tests:

```bash
python -m unittest discover -s tests -v
```

Build the package:

```bash
python -m build
```

### CI — Continuous Inspection by Cat

The lightweight package-smoke workflow checks the normal packaging path.

The cat is not trusted to declare a release “probably fine.”

```text
compile
  ↓
unit/regression tests
  ↓
build wheel + sdist
  ↓
clean venv install
  ↓
CLI version/help smoke
```

The comprehensive workflow goes substantially further. It is designed to exercise:

- Python 3.10, 3.11, 3.12, 3.13, and 3.14
- minimum declared dependency versions
- coverage
- source/config/version consistency
- wheel + sdist contents and clean installation
- real Linux mpv JSON IPC
- real gapless playlist priming / top-level playback
- Watchdog/inotify delivery
- MPRIS registration on a session D-Bus
- Pillow album-art cache behavior
- a final **Comprehensive test gate** used by protected `main`

The goal is not to prove that the jokes are funny. The goal is to prove that adding jokes did not break the music player.

A failed joke is survivable. A broken queue is an incident.

## Roadmap — possible future crimes, pending feline review

Ideas, not promises. The cat is not allowed to convert bullet points into contractual obligations:

- broader terminal graphics protocols beyond Kitty
- an in-TUI inspector for local vs enriched metadata + provenance
- manual metadata refresh / reject controls
- in-TUI Smart Mix rule editing
- automatic reload when `smart-mixes.json` changes
- per-track lyric timing offsets and lyric editing
- additional visualizer backends / more player-specific capture
- ReplayGain tag inspection and loudness diagnostics
- broader gapless stress testing across mixed codecs/sample rates
- tagged release automation
- Arch `PKGBUILD` / AUR packaging
- optional remote/self-hosted music-library sources such as an OpenSubsonic-compatible server, without making local files second-class citizens
- more scientifically unnecessary cat behavior, provided it remains presentation-safe

A future feature has to fit the project's identity: **terminal-native, local-first, keyboard-first, and capable of being used seriously even if a cat is currently filing a bug report against gravity.**

## License — the only adult still in the room

MeowPlayer is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE).

The README may call a queue "The Catnip Stash." The license, mercifully, does not.

The cat has attempted to rename GPLv3 to the **General Purring License**. Legal rejected the patch.

## Why "MeowPlayer"? — because "mpv-but-a-cat-keeps-commenting" was too long

Because every respectable terminal deserves at least one application that is simultaneously:

```text
useful
keyboard-first
weirdly over-engineered
and supervised by this employee:

 /\_/\
( o.o )
 > ^ <
```

The project is intentionally not trying to hide the joke as it becomes more capable.

If anything, increased engineering seriousness has made the joke funnier. A tiny cat now sits on top of SQLite migrations, persistent IPC, DNS diagnostics, MPRIS, metadata provenance, gapless state recovery, and multi-version CI like this is a normal place for a tiny cat to be.

The point is the contrast:

```text
SQLite migrations                 → serious
mpv JSON IPC                     → serious
gapless handoff recovery         → serious
MusicBrainz matching             → serious
MPRIS / D-Bus                   → serious
Python 3.10–3.14 CI             → serious

G = pet cat                     → absolutely critical
```

MeowPlayer should remain a player you can depend on **and** a player that occasionally informs you that `Unknown Artist has been placed under investigation.`

That is the bit. We are committing to it.

> **MeowPlayer should be reliable enough that the cat theme feels irresponsible, and cat-themed enough that the reliability feels suspicious.**
