# MeowPlayer 🐈🎵

**A terminal music player with suspiciously serious engineering and an entirely unnecessary cat.**

**MeowPlayer 0.15.1** is a local-first, keyboard-first terminal music player for Linux and Termux. `mpv` does the decoding, Python + `curses` run the TUI, SQLite remembers the library, Mutagen reads tags, Watchdog notices filesystem changes, LRCLIB can fetch synchronized or plain lyrics, MusicBrainz can fill missing metadata, and the cat takes credit for all of it.

No account is required. Your normal music library can remain ordinary files on disk. Online features are optional. The cat is not optional unless you invoke **Serious Mode**, which is legally distinct from making the cat leave.

```text
 /\_/\   ♫ MEOWPLAYER v0.15.1 — Purring
( ^.^ )
 > ♫ <

▶  Now Purring: Space Song — Beach House
00:42 ━━━━━━━∿──────────── 05:20

Meow Level: 70%   Pounce: ON (37 left)
Tail-Chase: OFF   Catnip: 4   Verdict: ★★★★☆   Mood: Zoomies

Music Nest / Songs — 842 meow(s)
🐾 Space Song — Beach House · Depression Cherry · Dream Pop · ★★★★☆ · 05:20
```

### The short version

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

### The Cat Constitution

MeowPlayer tries to stay true to a few rules:

- **Local files are the foundation.** The player does not require a proprietary cloud library.
- **Local tags are authoritative.** MusicBrainz may fill holes; it does not get to overrule good metadata you already own.
- **Online features fail soft.** No internet should mean fewer conveniences, not no music.
- **The cat may be ridiculous; playback state may not be.** Cat Incidents are presentation-only.
- **Your audio files are not secretly rewritten.** Online metadata and downloaded lyrics live in MeowPlayer's own cache/catalog unless you create sidecar files yourself.
- **Serious Mode remains a first-class citizen.** The application can remove most cat presentation without removing actual features.

### What lives under the fur

| Area | What MeowPlayer actually uses |
| --- | --- |
| Playback | `mpv` JSON IPC, gapless priming, ReplayGain |
| Library | SQLite **Cat Catalog**, recursive scanning, Watchdog/inotify |
| Metadata | Mutagen locally, optional MusicBrainz enrichment for missing fields |
| Lyrics | sidecar/embedded lyrics + optional LRCLIB synchronized/plain lookup |
| Discovery | Artists, Albums, Folders/Nests, Pawmarks, Purr History, Smart Mixes |
| Desktop | MPRIS / D-Bus, `playerctl`, media keys |
| Terminal candy | Kitty album art, CAVA spectrum |
| Critical infrastructure | `G` to pet the cat |

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

## What's new in 0.14.0 — The Cat Has Opinions

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

## What's new in 0.13.0

MeowPlayer 0.13.0 turns the library from something that is mostly scanned at startup into something that can react while the player is running.

### Custom Smart Mix rules

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

MeowPlayer now watches the music root recursively. Add, delete, rename, move, or retag music and the Cat Catalog refreshes automatically after a short debounce.

Library state is remapped by **file path**, not by old numeric index, so queue entries, Pounce Bag contents, playback history, Smart Mix sequences, and the current track do not silently turn into different songs after a rescan.

## Highlights — what the cat actually does

This section is intentionally long because calling MeowPlayer a "tiny terminal wrapper around mpv" has become increasingly difficult to defend in court.

### Music Nest / library

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

### Playback

- Real queueing through **The Catnip Stash**
- `.m3u` / `.m3u8` save + load
- Persistent no-repeat **Pounce Bag** shuffle
- Persistent Previous-history with shuffle-aware forward/back behavior
- Tail-Chase repeat
- Automatic next-track playback
- One-track-ahead **gapless playback** using mpv's internal playlist
- Verification/recovery around awkward mpv handoff states
- Native **ReplayGain** through mpv

### Personal library memory

- Persistent **Pawmarks** favorites
- Independent persistent **0–5 star ratings**
- Play counts, last-played timestamps, and listening history
- Session restore for queue, Pounce Bag, active Smart Mix sequence, volume, current track, and position

### Smart Mixes

- Built-ins for Pawmarks, recently played, most played, **Top Rated**, fresh additions, never played, and detected genres
- Custom rule parser with AND / OR / NOT, parentheses, text matching, numeric comparisons, sorting, and limits
- Rating-aware rules such as `rating >= 4`
- No Python `eval()` hiding under the rug

### Songbook / lyrics

- Same-name `.lrc` and `.txt` sidecars
- Embedded synchronized/plain lyrics
- Optional **LRCLIB** synchronized lookup
- Background download + persistent local LRC cache
- Truthful `Searching`, `network error`, and `not found` states instead of instantly blaming the song
- Live timestamp following and manual scroll
- Adaptive **lyrics + album-art split view** on wide Kitty terminals

### Terminal / desktop integration

- Kitty album art from embedded or folder artwork
- Pillow-based PNG artwork cache
- Optional **CAVA** FFT spectrum
- Linux MPRIS / D-Bus integration
- `playerctl`, media keys, MPRIS metadata, and `mpris:artUrl`
- Native Termux defaults and narrower phone-friendly behavior

### Necessary feline infrastructure

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
git clone https://github.com/Luqman234/MeowPlayer.git
cd MeowPlayer
python3 -m pip install .
meowplayer
```

### Termux / Android

```bash
pkg update
pkg install python python-pip mpv git
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

## Requirements — food, water, mpv

- Python **3.10+**
- `mpv`
- Mutagen
- `dbus-next` for Linux MPRIS integration
- Pillow for album-art normalization/cache
- Watchdog 6.x for live filesystem events
- CAVA *(optional)* for the spectrum
- Internet access *(optional)* for LRCLIB lyrics and MusicBrainz metadata enrichment
- A terminal with curses support
- Unix-domain socket support

Python dependencies live in `pyproject.toml` and are installed by normal `pip` / `pipx` installation.

If Mutagen is unavailable, MeowPlayer can still discover and play files using filename/folder fallbacks, but rich metadata and cached duration will naturally be worse.

If the internet disappears, the local player still plays. Downloaded lyrics and cached metadata remain available according to what was already stored. This is a music player, not a login screen with an audio feature.

## Music library views

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

### Songs

A flat metadata-aware track list.

```text
★ Space Song — Beach House · Depression Cherry · Dream Pop · 05:20
  Nude — Radiohead · In Rainbows · Art Rock · 04:15
```

### Artists

Artists are navigable rather than decorative group headers.

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

### Albums

Album view opens directly into the selected album's track list.

```text
Music Nest / Albums

>^.^< In Rainbows — Radiohead (2007) · 10 track(s) ›
      Kid A — Radiohead (2000) · 10 track(s) ›
```

### Folders / Nests

Groups tracks by their physical directory under the selected music root.

### Pawmarks

Press `F` on an individual track to toggle its persistent favorite state.

```text
★ Nude — Radiohead · In Rainbows · Art Rock · 04:15
```

View `5` shows only Pawmarked tracks.

### Purr History

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

## Smart Mixes

Press `7` to open **Smart Mixes**.

Unlike ordinary saved playlists, Smart Mixes are generated from the current Cat Catalog every time they are opened.

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

### Custom Smart Mix rules

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

## Scent Search

Press `/` in the Music Nest.

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

## The Cat Catalog — SQLite remembers what the cat will not

The **Cat Catalog** is MeowPlayer's persistent SQLite library model.

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

### Incremental metadata caching

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

### Rebuild metadata

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

### Schema migrations

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

## Online metadata enrichment — the Metadata Investigation Bureau

MeowPlayer's online metadata layer exists to answer a narrow question:

> "This track is missing information. Can we fill the holes without pretending the internet knows my library better than I do?"

The answer is **yes, cautiously**.

### Local-first precedence

For every field, local data wins when it is already meaningful.

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

### Finding the song

When tags are sparse, MeowPlayer can derive fallback clues from filenames such as:

```text
01 - Artist - Title.flac
```

MusicBrainz candidates must clear a confidence threshold. When both sides have useful durations, MeowPlayer also compares the MusicBrainz recording length against the actual local audio duration and rejects large mismatches.

That matters for covers, live versions, remasters, reprises, and the approximately seventeen billion songs named `Home`.

### Background worker and cache policy

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

### What gets sent

MeowPlayer sends MusicBrainz **search queries derived from available tags/filename clues**. It does not upload the audio file. Local duration is used for candidate validation.

### Disable it

One launch:

```bash
meowplayer --no-online-metadata
```

Persistent config:

```json
"online_metadata_enabled": false
```

The rest of MeowPlayer continues normally.

## Live filesystem watching

MeowPlayer 0.13.0 watches the selected music root recursively using Watchdog.

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

## Lyrics / Songbook — the cat has obtained the words

Press `L` to open the **Songbook**.

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

### Online LRCLIB lookup

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

### Songbook controls

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

## Audio visualizer

MeowPlayer 0.12.0 added a real frequency spectrum to the TUI using **CAVA**.

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

## Album art

MeowPlayer 0.10.0 added real album artwork directly inside **Kitty terminals** using Kitty's terminal graphics protocol.

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

## Gapless playback and ReplayGain

MeowPlayer 0.11.0 upgrades the audio engine in two places.

### Gapless playback

MeowPlayer no longer waits for a song to reach EOF before deciding what comes next.

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

### ReplayGain

ReplayGain uses gain values already stored in the audio file's metadata. MeowPlayer delegates the actual gain calculation and clipping protection to mpv.

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

## Pounce Bag shuffle

Pounce Mode is not independent `random.choice()` selection anymore.

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

## The Catnip Stash

The queue is officially called **The Catnip Stash**.

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

## Main controls

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
| `Space` | Paws / resume |
| `←` / `→` | Scritch backward / forward 5 seconds |
| `N` | Next meow |
| `P` | Previous purr |
| `+` / `-` | Adjust Meow Level |
| `S` | Toggle Pounce Mode |
| `R` | Toggle Tail-Chase |
| `X` | Quit / escape before the cat notices |

## Persistent config and state — because the cat has a memory now

MeowPlayer follows the XDG base-directory layout.

### Config

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

### Runtime state

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

## MPRIS and media keys

On Linux desktops, MeowPlayer exposes:

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

## Cat moods

The mascot reacts to player state:

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
 /\_/\   ♫ MEOWPLAYER v0.15.1 — Loafing
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

### Responsibility boundaries

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

## Build packages

Install the build frontend:

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
├── meowplayer_terminal-0.15.1-py3-none-any.whl
└── meowplayer_terminal-0.15.1.tar.gz
```

The installed CLI is still:

```text
meowplayer
```

## Project structure

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
├── mpris_support.py           # Linux MPRIS bridge
├── visualizer.py              # CAVA raw spectrum integration
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
│   ├── test_goofy.py
│   ├── test_lyrics.py
│   ├── test_online_metadata.py
│   ├── test_rescan.py
│   ├── test_shuffle.py
│   ├── test_smart.py
│   ├── test_visualizer.py
│   └── test_watcher.py
└── .github/
    └── workflows/
        ├── comprehensive-test.yml
        └── package-smoke.yml
```

There is a non-zero amount of code whose purpose is to make a cat react to volume. This is documented here for transparency.

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
  mpris_support.py \
  visualizer.py
```

Run the tests:

```bash
python -m unittest discover -s tests -v
```

Build the package:

```bash
python -m build
```

### CI

The lightweight package-smoke workflow checks the normal packaging path:

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

## Roadmap — possible future crimes

Ideas, not promises:

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

## License

MeowPlayer is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE).

The README may call a queue "The Catnip Stash." The license, mercifully, does not.

## Why "MeowPlayer"?

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
