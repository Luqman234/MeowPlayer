# Bug Archaeology — cmus, Round 1

MeowPlayer v0.20.0; investigation date: 2026-09-28.

## Findings

Thirteen historical cmus failure modes were selected from release notes and Git
history, then checked against MeowPlayer's ownership boundaries. Classification
is exclusive per entry: **2 directly transferable (A), 4 conceptually transferable
(B), 6 already protected (D), 1 architecture-specific (C)**.

Seventeen deterministic tests were added in `tests/test_bug_archaeology_cmus.py`.
Five MeowPlayer defects were reproduced before production edits:

1. An idle crossfade deck retained its old numerical reservation across rescans.
   Deleting its file could reuse that index for a different song: the audio deck
   and Python's eventual track identity would disagree. Deleting the current
   track also left an obsolete incoming reservation behind.
2. Rescanning a shortened queue did not clamp `stash_selected`; removing the
   selected item could index beyond the new queue.
3. MPRIS text accepted surrogate code points and embedded NUL. The former fails
   real D-Bus serialization; the latter violates the D-Bus string boundary.
4. Invalid UTF-8 in saved JSON escaped the persistence fallback.
5. A non-path `current_track` in valid JSON raised `TypeError` during restore.

Fixes are confined to three existing modules. No cmus implementation was copied.
Python still owns logical playback, mpv owns decoding/audio, and Cat Presence
remains presentation-only. No decoder, playback engine, or UI architecture was
replaced.

## Method and sources

For each entry: read historical evidence; identify the violated invariant;
translate the user-visible behavior to MeowPlayer; classify; add a deterministic
regression where applicable; run it **before** production changes; fix only a
reproduced defect; rerun the new and complete suites. A passing translation means
protection against that tested case, not proof that the subsystem has no bugs.

Sources inspected:

- [cmus release notes / release shortlogs](https://github.com/cmus/cmus/releases),
  particularly 2.9.1, 2.10.0, 2.11.0 and 2.12.0. These supplied the changelog view;
  a raw `CHANGELOG` fetch did not provide a usable file.
- cmus Git history, inspected locally in `/tmp/cmus-archaeology`, at checkout
  `b69fb9cd42c750d7e0f6aeaed4a3bb55756d4c0e`. Historical commit links below pin
  the evidence independently of that checkout.
- Full patches and relevant source contexts in `pl.c`, `editable.c`, `track.c`,
  `search.c`, `tree.c`, `mpris.c`, `uchar.c`, `ui_curses.c`, `options.c`, `job.c`,
  `play_queue.c`, `input.c`, and `player.c`.
- [Issue #847](https://github.com/cmus/cmus/issues/847), a playback/UI freeze
  associated with malformed text; [issue #1332](https://github.com/cmus/cmus/issues/1332),
  an unresponsive search. The historical patches provide the causal evidence,
  rather than inferring causes solely from issue titles.

The scope is deliberately bounded to the thirteen entries below, not an audit
of all cmus history. Unselected search hits are not counted as reviewed bugs.

## MeowPlayer architecture inspected first

| Owner / files | State and boundary |
| --- | --- |
| `meowplayer.py` | UI thread owns `current`, `playback_sequence`, Stash, Pounce bag/history, Tail-Chase, online context and transition commits. `peek_next_index` supplies gapless/crossfade reservations; `next_song` independently implements manual/automatic ordering. |
| `MPVController` | Persistent JSON IPC, reply matching, property cache, observed playback events. `_awaiting_mpv_path` delays playlist mutation until manual-load confirmation. mpv decodes; it does not own the library sequence. |
| Crossfade | Python owns active/outgoing vs preloaded/incoming deck references. The incoming deck becomes authoritative only on commit; reservations were numerical indexes, exposing the rescan defect. |
| `meow_catalog.py`, Mutagen reads | SQLite metadata/stat cache and path-based identity. Rescans rebuild lookup and remap queue, history, sequence and shuffle; surviving current playback must not reload. Metadata cache validity uses file stat information. |
| `library_watcher.py` | Locked, debounced path/event batches; callbacks do not mutate playback. The UI polls batches and rescans. Stop joins the observer with a timeout. |
| `meow_persistence.py`, restore methods | XDG JSON, temporary-file replacement, path-based restore. Playback restores paused. Syntax errors already fell back, but encoding and path-type errors did not. |
| `meow_smart.py`, library/search methods | Smart-rule evaluation and ordered views feed sequence snapshots. Search normalizes with NFKC/casefold and filters a finite index list. Selection is separate from current playback. |
| `youtube_online.py`, online methods | Resolver futures, cancellation and session caches; Python holds `online_current` and a copied playlist context. Twenty-second prefetch is preparation only. Online EOF checks reason and load timestamp. |
| `mpris_support.py` | D-Bus thread consumes snapshots and enqueues external actions for UI processing. Metadata is presentation data; sanitation must not rewrite filesystem paths in the library. |
| `visualizer.py`, shutdown | CAVA reader publishes bars; shutdown closes sessions/resolver, enrichment, MPRIS, watcher, art, visualizer, catalog and both mpv decks. No broad concurrency proof is claimed. |
| Cat Presence | Reads playback snapshots; never selects or advances tracks. |

Also inspected `tests/`, README architecture/release history, `pyproject.toml`,
`PKGBUILD`, and all three GitHub Actions workflows. The project uses unittest
discovery, so the new file is automatically included. Packaging remains the
existing flat module layout. Existing untracked package/source directories were
left alone.

## BA-CMUS-001 — Deleted playback references and reserved deck identity

- **cmus source/reference:** [fc03303](https://github.com/cmus/cmus/commit/fc03303d0e96b07c826d3d1374afe9f214dbe675).
- **cmus failure:** Deleting the playing playlist entry retained its playing-track reference.
- **Relevant MeowPlayer subsystem:** Rescan, current identity, gapless/crossfade reservation.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE. Python has no dangling C pointer; a reused integer index can still identify the wrong track.
- **Equivalent scenario:** A plays, B is reserved, B disappears, rescan turns old index 1 into C. Also remove A while B is preloaded.
- **Expected:** A keeps playing without a restart; reservation becomes C; deleting A stops gracefully and invalidates the incoming deck.
- **Existing protection:** Path remapping and `test_rescan_remaps_state_by_path_not_old_index`; current deletion already stopped the main deck. Idle crossfade reservations were omitted.
- **Regression tests:** `CmusArchaeologyTests.test_001_deleted_future_reservation_is_rebuilt_by_identity`, `test_001_deleted_current_stops_and_discards_incoming_deck`.
- **Result:** FAIL before fix for crossfade; gapless case passed. PASS after fix.
- **Fix:** Cancel/discard crossfade reservations before every rescan, including preloaded but inactive decks. Reprime using the new path mapping afterward when current survives.
- **Why safe:** Cancellation only stops the incoming deck; an active fade restores outgoing volume. It never reloads the surviving current song. Discarding before indexes change prevents the equality shortcut from accepting the wrong file.
- **Test significance:** Asserts the actual fake deck path as well as Python identity and absence of main-deck stop/load calls.
- **Status:** Fixed and retained.

## BA-CMUS-002 — Deleting an entire playing container

- **cmus source/reference:** [e22b50a](https://github.com/cmus/cmus/commit/e22b50a19bccfeba6d848de9b7ac4e06c6bc744b).
- **cmus failure:** Deleting the playing playlist cleared the playlist reference but left its playing-track reference.
- **Relevant subsystem:** Catnip Stash vs independently owned current track and sequence.
- **Classification:** D — ALREADY PROTECTED (ownership).
- **Equivalent scenario:** A queued song is current; clear all pending Stash entries, including duplicates, with a gapless reservation outstanding.
- **Expected:** Keep current; discard pending queue reservation; continue in the saved sequence, not raw scan order.
- **Existing protection:** Played Stash entries are popped before playback; `clear_stash` reprimes through Python order. No current pointer is owned by the pending queue.
- **Regression test:** `test_002_clear_queue_preserves_current_and_sequence`.
- **Result:** PASS before and after edits.
- **Fix:** None.
- **Test significance:** Checks current is not reloaded and both the replacement reservation and subsequent manual Next follow a non-scan sequence.
- **Status:** Tested protection; not a claim that every queue mutation is safe.

## BA-CMUS-003 — Selection after list mutation

- **cmus source/reference:** [ddaf8e3 / #916](https://github.com/cmus/cmus/commit/ddaf8e3cf41d490413e888303cafd7e91bca17ad).
- **cmus failure:** Moving every marked track set selection before refreshing window state, causing a crash.
- **Relevant subsystem:** Queue selection after rescan; reorder and gapless commit.
- **Classification:** A — DIRECTLY TRANSFERABLE (selection must reference the new list).
- **Equivalent scenario:** Select the last of three queued files, delete it, rescan, then remove the newly selected item. Separately reorder the queue before a gapless transition.
- **Expected:** Selection stays in bounds and the next audible track follows the reordered queue exactly once.
- **Existing protection:** Explicit queue remove/move clamp selection; rescan did not. Reordering already reprimes gapless.
- **Regression tests:** `test_003_rescan_clamps_queue_selection_before_remove`, `test_003_reordering_queue_replaces_gapless_reservation`.
- **Result:** Rescan selection FAIL before fix; reorder PASS. Both PASS afterward.
- **Fix:** Clamp `stash_selected` immediately after remapping the Stash, using zero for an empty queue.
- **Why safe:** Only repairs a UI cursor; preserves queue order, duplicates and current identity.
- **Test significance:** Executes removal after rescan and commits a reordered mpv path, checking remaining queue and history.
- **Status:** Fixed and retained.

## BA-CMUS-004 — Shuffle when current is outside the pool

- **cmus source/reference:** [99ee004](https://github.com/cmus/cmus/commit/99ee004609921dff36403429b1efe2139cd1da58).
- **cmus failure:** A current track excluded by filtering did not trigger the expected reshuffle on traversal.
- **Relevant subsystem:** Pounce, sequence-scoped bag, queued track outside sequence.
- **Classification:** D — ALREADY PROTECTED.
- **Equivalent scenario:** Current is outside `[D, B]`; bag contains current, duplicates, invalid indexes and another library track.
- **Existing protection:** `sanitize_shuffle_bag`, sequence-scoped refill; existing `test_shuffle_bag_is_scoped_to_active_playback_sequence`.
- **Regression test:** `test_004_shuffle_outside_sequence_never_uses_scan_order`.
- **Result:** PASS before/after.
- **Fix:** None; do not adopt cmus's shuffle algorithm or change MeowPlayer's cycle semantics.
- **Test significance:** Peek and actual automatic Next agree, and remaining bag is confined to the active sequence.
- **Status:** Tested protection.

## BA-CMUS-005 — Search wraps without terminating

- **cmus source/reference:** [ef177ed](https://github.com/cmus/cmus/commit/ef177edf3cefe19c67383f495bd54132656ee4b4), [#1332](https://github.com/cmus/cmus/issues/1332).
- **cmus failure:** Search traversal could wrap forever when iterator implementations never returned the initial position.
- **Relevant subsystem:** Library search.
- **Classification:** D — ALREADY PROTECTED (finite filtering).
- **Equivalent scenario:** No match for a slash-heavy query across all tracks.
- **Existing protection:** `filtered_song_indices` evaluates a bounded list rather than cyclic traversal.
- **Regression test:** `test_005_no_match_search_visits_each_track_at_most_once`.
- **Result:** PASS before/after.
- **Fix:** None.
- **Test significance:** A visit guard fails immediately on a second evaluation of any index; no timing threshold or sleep is used.
- **Status:** Tested protection.

## BA-CMUS-006 — Restricted tree search starts from an unreachable position

- **cmus source/reference:** [084db8d](https://github.com/cmus/cmus/commit/084db8df59fa283b6e86d3064f6fea43b515e118).
- **cmus failure:** Restricted search traversed album endpoints while starting at an interior track, preventing its wrap-termination comparison from succeeding.
- **Relevant subsystem:** Artist/album drill-down, empty library and stale selection.
- **Classification:** D — ALREADY PROTECTED. Related to 005, but a distinct concrete iterator mismatch and fix.
- **Equivalent scenario:** Search in an album with selection beyond the list, no result; library then empties while searching.
- **Existing protection:** Search doesn't start at `selected`; finite filtering and Escape resetting selection.
- **Regression test:** `test_006_restricted_search_with_stale_selection_and_empty_library`.
- **Result:** PASS before/after.
- **Fix:** None.
- **Test significance:** Applies and clears the no-match search after removing all songs; proves stale selection cannot determine search traversal.
- **Status:** Tested protection.

## BA-CMUS-007 — Invalid metadata text crosses D-Bus

- **cmus source/reference:** [e27e813 / #871](https://github.com/cmus/cmus/commit/e27e813bec7a60cca72f75ec018a3bb8b3d5326a), [#847](https://github.com/cmus/cmus/issues/847).
- **cmus failure:** Invalid UTF-8 sent through MPRIS could close the bus connection; the patch sanitized outgoing metadata.
- **Relevant subsystem:** `mpris_support._metadata_variants`, Mutagen/filename-derived presentation strings.
- **Classification:** A — DIRECTLY TRANSFERABLE.
- **Equivalent scenario:** Metadata contains POSIX surrogateescape-style text, embedded NUL, CJK, emoji and combining accents.
- **Expected:** D-Bus text is encodable and NUL-free; valid Unicode remains intact.
- **Existing protection:** Python strings alone do not guarantee valid D-Bus text; none at this boundary.
- **Regression tests:** `test_007_mpris_text_is_utf8_without_nul_and_preserves_valid_unicode`, `test_007_metadata_marshals_on_real_dbus_wire`.
- **Result:** UnicodeEncodeError before fix, including actual dbus-next marshalling. PASS afterward.
- **Fix:** Sanitize outgoing text fields to valid UTF-8 and replace NUL. Do not mutate catalog metadata or filesystem identity.
- **Why safe:** Valid text and D-Bus signatures remain unchanged. Invalid scalar values affect only external presentation. The dependency-free boundary test always runs; real marshalling skips only when optional dbus-next is unavailable.
- **Test significance:** Covers all seven outgoing text fields and actual wire serialization, not merely Variant construction.
- **Status:** Fixed and retained. SQLite handling of surrogateescape paths is outside this test's guarantee.

## BA-CMUS-008 — Activation accidentally follows current instead of selection

- **cmus source/reference:** [2628502 / #1044](https://github.com/cmus/cmus/commit/2628502b33725537d6691e2d34b7219ce18d08b6).
- **cmus failure:** A shuffle-related regression selected the currently playing track before activating the user's chosen row.
- **Relevant subsystem:** Library selection, Pounce, visible playback order.
- **Classification:** D — ALREADY PROTECTED.
- **Equivalent scenario:** Shuffle enabled; activate another row in a non-scan-order view.
- **Existing protection:** Selection lookup precedes `play`; existing `test_enter_activation_preserves_visible_order_for_crossfade` and `test_library_playback_sequence_matches_visible_order_for_crossfade`.
- **Regression test:** `test_008_explicit_selection_wins_over_current_during_shuffle`.
- **Result:** PASS before/after.
- **Fix:** None.
- **Test significance:** Asserts selected identity, preserved visible sequence and departed-track history after actual playback entry.
- **Status:** Tested protection.

## BA-CMUS-009 — Restore must preserve playback context safely

- **cmus source/reference:** [e8e2432 / #729](https://github.com/cmus/cmus/commit/e8e24329273b2b50ec600539116fe9bba7048e53).
- **cmus failure:** Resume did not remember playlist position; the fix also accounted for an offline-cleared playlist being repopulated after load.
- **Relevant subsystem:** Saved path sequence and session restore.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE.
- **Equivalent scenario:** Restore a reordered sequence containing a deleted file; current resumes paused with the right successor. Stress extensions: invalid JSON encoding and non-path current identity.
- **Existing protection:** Path-based sequence restoration drops missing files. JSON syntax and filesystem errors already fell back. Encoding errors and restore path types were not handled.
- **Regression tests:** `test_009_restore_uses_paths_and_keeps_next_order`, `test_009_corrupt_state_encoding_falls_back`, `test_009_invalid_saved_track_does_not_load`.
- **Result:** Valid path/context PASS before fix; encoding and bad type ERROR. All PASS afterward.
- **Fix:** Persistence loader handles Unicode errors; restore rejects invalid path values/types.
- **Why safe:** Valid restoration semantics are unchanged. Unusable state degrades to defaults or no playback instead of crashing startup.
- **Test significance:** Checks paused playback and next identity; actual malformed bytes and typed JSON-equivalent values exercise the failure boundaries. These two corruption bugs are MeowPlayer discoveries, not claims about the original cmus report.
- **Status:** Two defects fixed and retained.

## BA-CMUS-010 — Terminal dimensions used before valid initialization

- **cmus source/reference:** [417523c / #1119](https://github.com/cmus/cmus/commit/417523c54a7b5a36d5bcd305ba3be34597d6aced).
- **cmus failure:** Window sizes initialized only in the main loop could produce negative string lengths when used earlier.
- **Relevant subsystem:** Prompt dimensions, resize and curses mode restoration.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE.
- **Equivalent scenario:** Prompt shrinks from normal size to 1x1 and 0x0, emits curses drawing errors, then grows while input remains active.
- **Existing protection:** Prompt queries size per iteration, clamps geometry, catches curses errors and restores modes in `finally`; main loop has a minimum-size guard.
- **Regression test:** `test_010_prompt_resize_preserves_input_and_restores_terminal`.
- **Result:** PASS before/after.
- **Fix:** None.
- **Test significance:** Exercises the input loop with a resize event and drawing failures, preserves Unicode input, verifies nodelay/timeout restoration. It does not verify visual cell-width correctness or every modal.
- **Status:** Equivalent stress test retained.

## BA-CMUS-011 — Ultra-wide terminal overruns a fixed print buffer

- **cmus source/reference:** [85e1650](https://github.com/cmus/cmus/commit/85e1650) (maximum draw width fix, #1065).
- **cmus failure:** Terminal width could exceed the statically bounded C print buffer; drawing width needed a cap.
- **Relevant subsystem:** TUI rendering; no equivalent first-party fixed C print buffer.
- **Classification:** C — ARCHITECTURE-SPECIFIC TO CMUS.
- **Equivalent scenario:** The memory-overrun mechanism does not transfer to Python strings. Curses and its C implementation remain dependencies with their own risks.
- **Existing protection:** Python-managed string allocation; drawing error guards.
- **Regression test:** None for this C buffer mechanism; 010 independently covers a transferable geometry invariant.
- **Result:** Not applicable to MeowPlayer-owned code.
- **Fix:** None. Do not impose cmus's width limit on MeowPlayer.
- **Status:** Documented exclusion.

## BA-CMUS-012 — Activate an empty filtered tree

- **cmus source/reference:** [27134b9](https://github.com/cmus/cmus/commit/27134b91ad112fe3aa2058c7d9a1d821581bf692).
- **cmus failure:** Activation dereferenced a missing selected track after live filtering emptied the tree.
- **Relevant subsystem:** Empty library view activation.
- **Classification:** D — ALREADY PROTECTED.
- **Equivalent scenario:** Existing playback continues while the visible track list becomes empty with a stale cursor.
- **Existing protection:** `selected_library_song` returns None; `activate_library_selection` returns without playing.
- **Regression test:** `test_012_activate_empty_view_does_not_load`.
- **Result:** PASS before/after.
- **Fix:** None.
- **Test significance:** Activates the real handler and checks that existing playback identity and load history are unchanged.
- **Status:** Tested protection.

## BA-CMUS-013 — Terminal input errors need explicit end-state semantics

- **cmus source/reference:** [063370f](https://github.com/cmus/cmus/commit/063370f847e70297bf13b83b4c7a254a332b3cef).
- **cmus failure:** Error returns did not consistently set the input EOF state at the input boundary; callers had to repair it.
- **Relevant subsystem:** Online playback event interpretation.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE. Decoder internals belong to mpv; transfer only the invariant that termination reason and playback ownership must be explicit.
- **Equivalent scenario:** Current online load sees an older timestamped EOF, a current error or stop, then a current successful EOF.
- **Expected:** Only the eligible EOF advances the active playlist. MeowPlayer deliberately does not adopt cmus's error-as-EOF policy.
- **Existing protection:** `process_online_playlist_streaming` checks reason and load timestamp; existing `test_online_playlist_eof_advances_to_next_track` and `test_online_playlist_last_track_stops_without_wrapping`.
- **Regression test:** `test_013_old_eof_and_current_error_do_not_advance_online_playlist`.
- **Result:** PASS before/after.
- **Fix:** None.
- **Test significance:** Negative cases plus a positive control rule out a test that passes merely because advancement is disabled. No internet, real decoder or sleeps.
- **Status:** Equivalent event stress test retained; late arrival with a newer receive timestamp is not covered.

## Verification and testing the tests

All test names above refer to `tests/test_bug_archaeology_cmus.py::CmusArchaeologyTests`.
Tests reuse the existing FakeMPV and player factory, while calling production
rescan, queue, selection, search, restore and transition methods. Filesystem scan
and metadata reads are substituted with deterministic snapshots; no external
YouTube/MusicBrainz/LRCLIB service or timing sleep is required.

- Baseline: **255 tests, OK, 1 skip**, Python 3.14.
- New regression suite: **17 tests, OK**, including real dbus-next marshalling.
- Complete suite after fixes: **272 tests, OK, 1 skip** (existing opt-in real mpv integration).
- Tests were first run before production edits. After completion, all 17 were
  also rerun against copies of the three original HEAD modules in `/tmp`, without
  reverting workspace changes: **3 failing assertions, 11 error subcases**,
  across seven test methods covering the five defects, including the real-marshalling
  confirmation. This includes per-field Unicode and per-value restore subtests;
  these are not fourteen separate bugs.
- Already-passing regressions document their behavioral oracle in each entry.
  They were not weakened to match implementation. No sleeps were introduced.
- `py_compile`, `git diff --check`, wheel and sdist build passed. Twine metadata
  validation was unavailable (`No module named twine`).
- Socket tests initially failed under sandbox restrictions. The complete
  baseline and post-fix runs above used permitted local socket access.
- The existing opt-in real mpv integration was then run separately with
  `MEOW_REAL_MPV=1`: **1 test, OK**, loopback HTTP and null audio output.
- GitHub-hosted OS/Python matrices, real audio devices and interactive terminals
  were not run here. These are local results, not a claim of a remote green CI run.

## Remaining suspicious areas and Round 2

Prioritize mutation during **active** crossfade (queue clear/reorder and remote
Next), rather than only idle deck priming. Exercise the full transition commit
against a playback-generation oracle. Also investigate:

- Local EOF polling while a replacement load is pending, and late online EOF
  events received after the new load timestamp. Receive time alone cannot prove
  event ownership; do not infer this protection from BA-013.
- A saved/active sequence whose every file disappears while a queued track
  outside it survives. Empty sequence and unrestricted library order currently
  share a representation; test whether that loses user intent.
- Surrogateescape filenames across SQLite, persistence writes, logging and mpv
  JSON IPC; BA-007 establishes only outgoing MPRIS text safety.
- Canonical path aliases/symlink duplicates and file renames during playback.
- Entire-library deletion, shutdown-time worker completions, watcher bursts,
  stale futures and external seek identity after a rescan.
- Cell-width-aware rendering of combining marks and emoji; the resize test
  establishes prompt survival and input preservation, not perfect alignment.

Round 2 should mine another bounded set of queue/worker/EOF fixes, with a
state-machine scenario matrix for manual Next, EOF, gapless, crossfade, Pounce,
Tail-Chase and restoration. Keep the same test-first rule and preserve mpv,
Cat Catalog, Catnip Stash and all the project's personality.

# Bug Archaeology — cmus, Round 2

Continuation from Round 1 commit `1b4d23f`, on
`hardening/cmus-round-2`. The Round 1 text and tests above remain unchanged.
The checkout initially pointed at `main`; the existing Round 1 branch was found
and used as the base, rather than reconstructing or repeating that work.

## Scope, evidence and results

**13 additional historical cases**, BA-CMUS-014–026: **A: 1, B: 7, C: 1,
D: 4**. These include bug fixes and a documented behavior change (stop after
queue); that distinction matters. There are **28 new test methods** in
`tests/test_bug_archaeology_cmus_round2.py`, with parameterized variants. The
extra three beyond the approximate 25-test target cover the main-loop EOF and
Stop boundaries found during investigation.

Research continued through the [cmus release shortlogs](https://github.com/cmus/cmus/releases),
local Git history, and complete patches/source contexts in `play_queue.c`,
`editable.c`, `job.c`, `track_info.c`, `input.c`, `player.c`, `cmus.c`,
`command_mode.c`, `cmdline.c`, `worker.c`, `ui_curses.c` and `jack.c`.
Commit links in the entries pin the evidence. Issue numbers below are historical
cross-references recorded by those commits, not claims of independently
reproducing cmus itself. No cmus implementation was copied.

Current MeowPlayer inspection covered Round 1's document/tests/fixes and Git
history, the playback/rescan/restore/IPC code, online resolver lifecycle,
SQLite catalog paths, persistence, watcher batching, MPRIS, lyrics/art path
lookup and the current tests/workflows/package configuration.

**PROVEN BUG / violated boundary:**

- Editing the head of the queue during an active fade left the old incoming
  choice active. Reorder could leave the played item queued for another play.
- Rescanning an unrelated deletion or index reorder cancelled a valid active
  fade. Round 1's idle-deck invalidation was correct but too broad for an active
  transition whose two identities survive.
- The completion handler accepted an inactive, merely preloaded deck, including
  on a second call. This is a proven handler weakness; the normal polling caller
  already checked `_crossfade_active`. No asynchronous completion callback
  exists, so this does **not** establish an independently reachable callback race.
- End events were recorded without entry ownership, and cached EOF observations
  could authorize a transition after seek/replacement. A pending local replacement
  could advance from the previous file's EOF before its path was confirmed.
- Remote Stop could be followed by the polling loop starting/committing another
  transition. MPRIS could still report Playing while mpv's idle update lagged.
- Losing every explicit sequence member converted it into unrestricted playback;
  invalid final indexes could also select the wrong song through modulo loading.
- Playlist loading stripped legal filename whitespace.

**Requested behavior correction:** explicit ordered sequences previously wrapped.
Round 2 deliberately changes this to stop at the end, as requested. The old
wrapping behavior is not presented as an accidental implementation error under
the old contract. Queue-only playback is now bounded too. Automatic repeat
handling is checked before queue consumption.

## Playback semantics fixed for this round

| State | Next / EOF / reservation policy |
| --- | --- |
| Explicit ordered sequence, including visible view, Smart Mix and restored sequence | Next follows the same valid index pool; final member stops. No gapless or crossfade reservation beyond it. |
| Explicit sequence becomes empty after deletion | Remains explicit and empty, including in saved state; never falls back to the library. |
| Current not in an explicit ordered sequence and queue empty | Stop; do not guess a position or restart at the first member. |
| Queue-only session | Play pending entries, then stop. |
| Queue over an explicit sequence | Queue has priority. After it drains, continue if current is in the sequence; otherwise stop rather than invent a resume position. |
| Tail-Chase | Native current-track repeat; automatic Next does not consume the queue. Manual Next still skips to an available successor; at the sequence boundary it keeps current. |
| Pounce | Preserve existing cyclic shuffle semantics, scoped to valid explicit members; empty explicit pool stops. This intentional cycle is not scan-order fallback. |
| No explicit sequence and no queue-only session | Preserve legacy unrestricted-library behavior. |
| Previous | Preserve history and existing backward-wrap behavior; this round's stop-at-end requirement concerns forward progression. |
| Active A → B fade, queue head removed/reordered/cleared | A remains current. Cancel B, restore A's volume, and prepare the new next item. No history/queue commit for the cancelled fade. |
| Active A → B fade, unrelated C removed or indexes reordered | Preserve both decks and fade timing; remap A and B by canonical path. |
| Incoming B or outgoing A deleted | Cancel the fade. If A disappeared, stop gracefully. No stale index commit. |
| Manual Next/Previous/Stop | The old fade cannot commit an inactive preloaded deck afterward. Stop suppresses automatic polling until explicit playback restarts. |

The small `playback_sequence_active` persisted boolean distinguishes an exhausted
explicit list from unrestricted playback. Older state is inferred from its saved
nonempty list. `_next_local_index` is the shared ordering decision; it does not
move playback authority into a new subsystem.

At the IPC boundary, existing mpv `playlist_entry_id` values identify start/end
ownership, including same-path reloads. Pending loads and Stop invalidate old
end/restart state. No custom decoder or competing playback authority was added.
EOF is fetched with a fresh request because property-change observations carry
no entry ID. Local EOF also requires the actual mpv path to match logical
current. Online snapshots produced by the real controller carry `entry-id` and
require fresh EOF confirmation; legacy timestamp-only test adapters retain their
existing compatibility path. Actual mpv without entry IDs has weaker protection
against arbitrarily reordered same-path events; timestamps alone are not claimed
to prove ownership.

## BA-CMUS-014 — Queue mutation must use one consistent ownership model

- **cmus reference:** [8ec61d4](https://github.com/cmus/cmus/commit/8ec61d412b7a55fbdcadbda32a71d28114ed3e94).
- **Historical failure:** Switching library → queue → library and adding another item could crash because queue mutations mixed incompatible editable/list bookkeeping.
- **MeowPlayer subsystem:** Stash and active crossfade.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE. Python has no cmus tree corruption; reservation and consumption must still agree about the authoritative queue.
- **Equivalent scenario:** A → B is audible but uncommitted; remove B, clear the queue or move B behind C. Also delete C while B remains the head.
- **Expected invariant:** Head mutations supersede the uncommitted choice; unrelated tail mutations preserve it; consume only the committed head once.
- **Regression tests:** `test_queue_head_mutation_cancels_uncommitted_crossfade`, `test_deleting_later_queue_item_preserves_active_fade`.
- **Result:** Head variants FAIL before, PASS after; tail variant already PASS.
- **Fix:** Cancel an active fade when the head occurrence is explicitly removed/moved/cleared; otherwise compare the primed target with current next semantics. Explicit occurrence checks also handle duplicate track indexes.
- **Status:** PROVEN BUG, fixed. History and MPRIS remain on A until commit.

## BA-CMUS-015 — Cache/library updates must reconcile every playback reference

- **cmus reference:** [98950a6](https://github.com/cmus/cmus/commit/98950a642a01b116c15a52332e60c231390f99ed).
- **Historical failure:** Cache refresh updated the library but omitted playlist and play-queue references, including removed tracks.
- **MeowPlayer subsystem:** Rescan, active deck indexes and queue paths.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE.
- **Equivalent scenario:** Remove C during A → B, reorder raw scan indexes, remove B, or rename a queued/current file on a real temporary filesystem.
- **Expected invariant:** Preserve surviving active identities without restarting audio; cancel only invalid transitions; removed paths cannot substitute another song.
- **Regression tests:** `test_rescan_deleting_later_file_preserves_active_decks`, `test_active_deck_identity_survives_raw_index_reorder`, `test_removed_incoming_file_cannot_commit_after_rescan`, `test_renamed_future_path_is_removed_without_wrong_substitution`, `test_current_rename_stops_gracefully_without_selecting_replacement`.
- **Result:** Active-preservation cases FAIL before, PASS after. Rename reconciliation already PASS; stale completion rejection is shared with BA-016.
- **Fix:** Snapshot active incoming identity, remap after scanning, validate against current ordering. Retain Round 1's discard/reprime for idle reservations.
- **Status:** PROVEN BUG, fixed; rename cases PROTECTED. Renaming current intentionally stops rather than guessing inode continuity.

## BA-CMUS-016 — An operation already finished cannot finish again

- **cmus reference:** [58f2b9d](https://github.com/cmus/cmus/commit/58f2b9d0f017463468a8cbf8f96202621a541deb).
- **Historical failure:** JACK drop could be entered again while an earlier drop was unfinished; writes also needed to honor that transition state.
- **MeowPlayer subsystem:** Crossfade commit, independent of mpv's audio backend.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE (one operation owns completion).
- **Equivalent scenario:** Invoke completion twice, or after manual Next/Previous has cancelled the old fade and preloaded a new candidate.
- **Expected invariant:** A preloaded deck is not an active transition and cannot commit; history and queue are unchanged on rejected completion.
- **Regression tests:** `test_crossfade_completion_consumes_queue_once`, active-fade variants of `test_manual_navigation_cannot_be_overruled_by_old_fade`.
- **Result:** FAIL before; PASS after.
- **Fix:** `_finish_crossfade` rejects inactive transitions before touching decks.
- **Status:** PROVEN HANDLER WEAKNESS, fixed. The ordinary polling caller was already guarded; an actual asynchronous callback race is NOT PROVEN.

## BA-CMUS-017 — Identity and lifetime must survive asynchronous activity

- **cmus reference:** [8d26cc8](https://github.com/cmus/cmus/commit/8d26cc875c321df5535fd46795e333d446aa3643).
- **Historical failure:** Track UID allocation and reference updates raced across threads; unique identity/lifetime required atomic operations.
- **MeowPlayer subsystem:** Persistent IPC playback-event ownership and gapless path commit.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE. This translates the identity invariant, not cmus reference counting.
- **Equivalent scenario:** Start entry 10, start entry 11, then deliver entry 10's EOF/error/stop; deliver an old event during load or after Stop. Also report an unreserved old local path.
- **Expected invariant:** Only the active entry can publish an end reason; rejected old events cannot advance online context or replace local current.
- **Regression tests:** `test_late_end_file_cannot_replace_current_entry_events`, `test_load_and_stop_invalidate_old_entry_events`, `test_gapless_rejects_unreserved_old_path`.
- **Result:** FAIL before; PASS after, with a valid current EOF positive control through the online handler.
- **Fix:** Match native playlist-entry IDs, invalidate ownership on load/advance/stop, reject unreserved gapless paths. No timestamp-based invented ownership token.
- **Status:** PROVEN EVENT-BOUNDARY VULNERABILITY, fixed for tested IDs/orderings. Synthetic delayed delivery demonstrates acceptance of an old event, not that every mpv version emits that ordering normally.

## BA-CMUS-018 — Stop remains authoritative during later activity

- **cmus reference:** [6506fe4](https://github.com/cmus/cmus/commit/6506fe4dcbdf98e4fe0d6257b2879e95d5fffdf6).
- **Historical failure:** Seek unexpectedly started stopped playback; stopped/paused intent was not preserved.
- **MeowPlayer subsystem:** External Stop, crossfade polling, local EOF, MPRIS.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE.
- **Equivalent scenario:** Stop A → B, then poll stale near-end position/EOF before mpv publishes idle.
- **Expected invariant:** No fade restart, no queue consumption, no logical advance; MPRIS reports Stopped immediately.
- **Regression test:** `test_remote_stop_cannot_restart_crossfade_on_late_eof`.
- **Result:** FAIL before; MPRIS's delayed status was separately demonstrated after the transition guard. PASS afterward.
- **Fix:** A logical stopped flag gates automatic transition processors and the MPRIS status snapshot. Explicit local/online play or restoration resets it.
- **Status:** PROVEN BUG, fixed. Seek is still delegated to mpv, and no new seek semantics were copied from cmus.

## BA-CMUS-019 — End of a bounded queue is not the whole library

- **cmus reference:** [2aa28a1 / #696 / #1006](https://github.com/cmus/cmus/commit/2aa28a1b165134d457e5ee5a5f2a3ff4a896e155).
- **Historical failure/behavior change:** Users wanted queue completion to stop rather than continue through the library. cmus added an optional stop-after-queue policy; it was not an unconditional decoder fix.
- **MeowPlayer subsystem:** Explicit sequence, Stash, restoration, Pounce, Tail-Chase.
- **Classification:** A — DIRECTLY TRANSFERABLE (bounded playback intent).
- **Equivalent scenario:** End `[3,0,2]`; delete every sequence member while a queued outsider survives; corrupt the final index; exhaust a queue-only session.
- **Expected invariant:** The policy table above applies equally to manual, automatic, gapless and crossfade ordering. Preserve repeat/shuffle semantics explicitly.
- **Regression tests:** `test_explicit_sequence_end_stops_all_next_paths`, `test_entire_sequence_deleted_does_not_become_unrestricted`, `test_invalid_final_sequence_entry_never_loads_modulo_index`, `test_current_outside_ordered_sequence_stops_instead_of_restarting`, `test_stash_only_playback_stops_when_last_entry_is_consumed`, `test_repeat_at_sequence_end_keeps_current_without_consuming_queue`, `test_repeat_eof_does_not_consume_queued_track`, `test_pounce_cycles_only_inside_explicit_sequence`.
- **Result:** Boundary/fallback/repeat cases FAIL before and PASS after; scoped Pounce already PASS.
- **Fix:** Share `_next_local_index`; filter invalid sequence members; persist explicit-list intent independently of membership; stop when no successor remains; check automatic repeat before consuming the queue.
- **Status:** Requested stop-at-end contract implemented; lost-intent/invalid-index failures fixed. No claim that cmus shares MeowPlayer's repeat policy.

## BA-CMUS-020 — Seeking around EOF must use current playback state

- **cmus reference:** [8cccf70 / #803](https://github.com/cmus/cmus/commit/8cccf702a348bd19670217f824c8e5d8e336381f).
- **Historical failure/behavior change:** Relative seeking beyond duration was clamped near the end rather than advancing; seek/EOF semantics were corrected.
- **MeowPlayer subsystem:** EOF observations and local replacement confirmation.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE.
- **Equivalent scenario:** Cache says EOF but current engine reply says not EOF after seek/reload; Python requests B while mpv still reports A at EOF.
- **Expected invariant:** Old EOF cannot advance B. A current matching-path EOF remains a positive control.
- **Regression tests:** `test_cached_eof_is_confirmed_live_after_seek_or_replacement`, `test_pending_local_replacement_cannot_advance_on_old_eof` (no/weak/yes gapless modes).
- **Result:** FAIL before; PASS after. The local run-loop block was first lifted unchanged into `process_local_eof`, then tested red before adding guards.
- **Fix:** Fresh EOF request instead of cached unowned observation; actual-path check in the local EOF decision; online real-controller EOF also requires fresh confirmation.
- **Status:** PROVEN BUG, fixed. Adds a small IPC roundtrip when checking EOF; no sleeps or IPC transport redesign.

## BA-CMUS-021 — Whitespace can be part of a filename

- **cmus reference:** [8b7c3ee](https://github.com/cmus/cmus/commit/8b7c3ee244925f8528da90b150de9f0f74689b0f).
- **Historical failure:** Filename-oriented command editing treated spaces as delimiters despite common music directory names containing spaces.
- **MeowPlayer subsystem:** M3U parsing and path consumers.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE.
- **Equivalent scenario:** Relative leading-space filename in a playlist; exact saved path ending in whitespace; real paths containing tabs, quotes, backslash, punctuation, CJK, emoji, combining marks and a 245-byte ASCII filename in nested directories.
- **Expected invariant:** Preserve path bytes/text, use structured IPC and SQLite parameters, encode a valid URI; sidecar/art lookup must address the same path.
- **Regression tests:** `test_playlist_preserves_whitespace_in_real_filename`, `test_unusual_paths_round_trip_catalog_load_uri_and_watcher`.
- **Result:** Playlist trimming FAIL before, PASS after. Other path pipeline cases PASS before and after.
- **Fix:** Do not `.strip()` the pathname; still skip empty/whitespace-only lines and M3U comments.
- **Status:** PROVEN PARSING BUG, fixed. The leading-space case is discovered normally. A filename with whitespace after `.flac` is legal but not currently admitted by discovery's suffix whitelist; the exact-path M3U roundtrip tests it as an existing library member, not as proof of discovery support.

## BA-CMUS-022 — Symlinks into hidden content must not vanish incorrectly

- **cmus reference:** [d6d0e34](https://github.com/cmus/cmus/commit/d6d0e34600c55aaa3a37c3cfb92c6a948b5dd389).
- **Historical failure:** Directory traversal suppressed an internal symlink under the assumption its target would be scanned, but hidden targets were skipped too.
- **MeowPlayer subsystem:** `Path.rglob`, file existence and resolved paths.
- **Classification:** D — ALREADY PROTECTED for the tested missing-content case.
- **Equivalent scenario:** A visible file symlink points into `.content`; remove its target, leaving the broken link.
- **Expected invariant:** Hidden content is discoverable; broken file symlinks are ignored without crashing.
- **Regression test:** `test_broken_symlink_is_ignored_without_changing_surviving_identity`.
- **Result:** PASS before and after.
- **Fix:** None. MeowPlayer does not apply cmus's hidden-directory exclusion.
- **Status:** PROTECTED CASE. Deduplicating multiple aliases and following directory symlinks are not established by this test.

## BA-CMUS-023 — Worker completion must be reconciled by the main owner

- **cmus reference:** [becef8d](https://github.com/cmus/cmus/commit/becef8de4f301491fb0ce57bc3ae445353a95892).
- **Historical failure:** A job finishing between update and job-presence checks could leave a loaded playlist apparently empty because the UI missed its wakeup.
- **MeowPlayer subsystem:** Resolver future and main-loop polling.
- **Classification:** D — ALREADY PROTECTED for the translated stale-result case.
- **Equivalent scenario:** An online resolution finishes after the user selects local playback.
- **Expected invariant:** Polling cannot resurrect the old online track/context; current local file and last load remain unchanged.
- **Regression test:** `test_late_online_resolution_cannot_replace_local_selection`.
- **Result:** PASS before and after.
- **Fix:** None. Local `play` clears `_online_future`; the worker publishes a result but does not control playback.
- **Status:** PROTECTED CASE. This is a different completion interleaving from cmus's lost-wakeup bug, not a copied fix or general liveness proof.

## BA-CMUS-024 — Worker lifecycle limits when work may run

- **cmus reference:** [b220a51](https://github.com/cmus/cmus/commit/b220a513a0f612481864332826b492653d5f269e).
- **Historical failure:** A worker started before initialization finished and could access cache/options too early; startup was deferred until the owner was ready.
- **MeowPlayer subsystem:** Resolver lifecycle boundary.
- **Classification:** D — ALREADY PROTECTED for the opposite, closed-boundary stress case.
- **Equivalent scenario:** Submit foreground/background-capable work after resolver close.
- **Expected invariant:** Closed work cannot acquire playback authority or start a new extraction.
- **Regression test:** `test_closed_resolver_cannot_accept_new_background_work`.
- **Result:** PASS before and after.
- **Fix:** None. `request` returns a cancelled future when `_closed` is set.
- **Status:** PROTECTED CASE. Does not prove every active worker exits promptly or every shutdown callback is harmless.

## BA-CMUS-025 — Decoder-plugin priority list races

- **cmus reference:** [9da313f](https://github.com/cmus/cmus/commit/9da313ffeddaf96db0c0e72e185290243e95fa27).
- **Historical failure:** Input-plugin lookup/sorting and priority changes accessed shared decoder lists without appropriate locking.
- **MeowPlayer subsystem:** None in Python; decoding/plugin selection belongs to mpv.
- **Classification:** C — ARCHITECTURE-SPECIFIC / NOT APPLICABLE.
- **Equivalent scenario:** No MeowPlayer-owned decoder registry to mutate.
- **Expected invariant:** Keep decoder authority in mpv; do not build a new plugin-locking subsystem in Python.
- **Regression test:** None for this backend-specific mechanism.
- **Result:** NOT APPLICABLE.
- **Fix:** None.
- **Status:** Documented exclusion, not a claim about mpv internals.

## BA-CMUS-026 — Previous at the first album track with repeat

- **cmus reference:** [5feece0](https://github.com/cmus/cmus/commit/5feece0be8491287625b105af35d0091cbb05aa6).
- **Historical failure:** Previous from the first track in album mode with repeat followed the wrong tree relationship and crashed rather than selecting the album's final track.
- **MeowPlayer subsystem:** Previous/history and explicit sequence indexing.
- **Classification:** D — ALREADY PROTECTED for backward boundary selection.
- **Equivalent scenario:** First track of a non-scan-order two-member sequence; repeat enabled; no history.
- **Expected invariant:** Previous remains within the sequence and selects its last member.
- **Regression test:** First boundary subcase of `test_manual_navigation_cannot_be_overruled_by_old_fade` (separate active-fade subcases belong to BA-016).
- **Result:** Boundary subcase PASS before and after.
- **Fix:** None for backward traversal; no new cmus-like tree structure.
- **Status:** PROTECTED CASE.

## Round 2 verification and limits

All named new tests are methods of `Round2Tests` in
`tests/test_bug_archaeology_cmus_round2.py`. Round 1's 17 methods remain unchanged.
The existing audio test fixture now calls `_init_ipc()` before testing manual
playlist advancement, because advancement invalidates event state. Its expected
commands and assertions were not weakened.

Test-first evidence:

1. Initial 25 tests ran before production changes: **26 failing assertions**
   across test methods/subcases, no errors. These are not 26 distinct bugs.
2. Three additional main-loop/repeat tests were added after extracting the old
   EOF block unchanged: **5 failing assertions** before their fixes.
3. An added MPRIS assertion separately demonstrated Playing after logical Stop;
   its fix is part of the Stop ownership change.
4. All final tests were replayed against copies of the Round 1 `HEAD` modules in
   `/tmp/round2-original`: **28 tests, 31 failing assertions**. The original local
   EOF block was lifted into the callable seam without its new guards so the
   replay measures behavior, not a missing-method AttributeError. Production
   files in the workspace were never reverted during this check.
5. Passing cases use explicit oracles: unchanged deck/load history, canonical
   path identity, exactly-once queue/history consumption, no online advancement,
   and a valid current EOF positive control. No sleeps were added to regressions.

Validation is local/offline; no YouTube/MusicBrainz/LRCLIB availability is needed.
The real-mpv test uses loopback HTTP and null audio. The separate MPRIS check uses
an isolated D-Bus session, reads metadata through `busctl`, and includes CJK,
emoji, combining marks, a surrogate and NUL input. Twine is not installed locally;
its validation is not claimed. The PKGBUILD is unchanged; existing Arch packaging
regressions are part of the complete suite, not a new full Arch clean-chroot run.

Remaining **SUSPICIOUS / UNPROVEN** areas:

- mpv versions/events without playlist-entry IDs; unlabelled start/restart/property
  events cannot by themselves prove load identity under arbitrary reordering.
- Reconnect while an online load is already in progress, stale same-path start
  events, and unexpected audible engine paths after rejecting a gapless commit.
- Rescan while mpv naturally advances *during* the scan, rather than the tested
  deterministic before/after mutations; no audio-engine transaction is claimed.
- Queue detours could benefit from a separately specified resume cursor; this
  round deliberately stops when current is outside the ordered sequence instead
  of inventing a position.
- Alias deduplication, directory-symlink cycles, surrogateescape filenames through
  SQLite/state writes, and filenames containing newline (M3U cannot represent
  those unambiguously). Ordinary valid Unicode was tested; arbitrary bytes were not.
- Active extraction completion during shutdown, bounded thread joins, terminal
  resize during two-deck commits and real audible fade quality under load.

**Recommendation:** do a bounded cmus Round 3 focused on reconnect/start-event
ownership, active worker shutdown, and rescan-during-natural-handoff before moving
to MPD archaeology. These results defend the listed states, not entire subsystems.

Final local validation for Round 2:

- Round 1 + Round 2 archaeology: **45 tests, OK**.
- Complete suite with `MEOW_REAL_MPV=1`: **300 tests, OK, no skips** on Python 3.14.
- Existing CI real gapless/manual advancement and top-level construction/playback/
  persistence/shutdown smoke scripts: **PASS**, using temporary fixtures and null audio.
- Isolated real MPRIS registration and Unicode metadata read through D-Bus: **PASS**.
- All first-party modules compile; `git diff --check`: **PASS**.
- Wheel and sdist builds, expected-module contents checks, offline wheel install
  into a temporary target and installed CLI version smoke: **PASS**.
- Twine, remote CI matrices and a full Arch chroot build: **not run**. PKGBUILD
  unchanged; its unit checks passed in the full suite.
- Round 1 document prefix and its regression file remain unchanged. Existing
  untracked package/source artifacts were left alone.

# Bug Archaeology — cmus, Round 3

MeowPlayer v0.20.0; investigation date: 2026-10-02;
branch: `hardening/cmus-round-3`.

## Scope, terminology and evidence

This is the bounded ownership/lifecycle follow-up to Round 2, not a new general
sweep. Eight additional historical cases were inspected, with **0 directly
transferable, 6 conceptually transferable, 1 already protected, 1 not applicable**.
This section uses the requested labels **A direct / B conceptual / C protected /
D not applicable**; the earlier sections' opposite C/D lettering is preserved.
There are **32 new test methods** in `tests/test_bug_archaeology_cmus_round3.py`.
Some methods exercise multiple variants. No cmus implementation was copied.

The starting tree included uncommitted Round 2 production edits and its untracked
regression file. Those were preserved, not replaced with Git HEAD (which was
Round 1). Before production edits, copies were saved in
`/tmp/meow-round3-baseline`. The baseline SHA-256 values are:

- `meowplayer.py`: `9a0a97cdcabbef6474cbe1be3f0c0f8d5d635e1a97c154cb8f6a0cdcfae28e17`
- `youtube_online.py`: `def39c73fbf5da8c7c5e96a9a9ffa7e9f652b9a5bdb79944bf35dd78f1119d4a`
- `library_watcher.py`: `db9502102fcab8021fc0543b9e8e2583c0360d286bcb7d227e164c1b452802f2`

Historical patches and parent context were read from cmus checkout
`b69fb9cd42c750d7e0f6aeaed4a3bb55756d4c0e` in `/tmp/cmus-round3`.
The references below are pinned commits. Historical enhancements are identified
as enhancements, not inflated into reported crashes.

Production ownership was inspected before writing tests: controller receive/send
locks, socket identity checks, native playlist entry IDs, event caches, pending
manual loads, online fallback/resolution/streaming, crossfade deck swaps,
rescan/catalog remapping, Stash/sequence consumption, watcher batches, MPRIS
queues, teardown, metadata and lyrics workers. Album-art extraction is synchronous;
there is no first-party asynchronous art completion to cancel. Cat Presence was
not changed and retains its read-only snapshot boundary.

### What was actually proved

**Reachable behavioral defects:**

1. A queued second occurrence of the *same file* naturally starts with a new mpv
   entry ID but the same path. Python did not consume the occurrence, including
   when the handoff happened inside rescan. The deterministic engine model changes
   identity at precisely that boundary; no arbitrary callback order is required.
2. A handoff during filesystem enumeration or metadata loading left Python on A
   while mpv played reserved B. Rescan could prime B again, omit its listen and
   queue/history commit, or retain A when audible B disappeared from the view.
3. Explicit MPRIS Play immediately after Stop could leave logical Stop latched
   when the cached mpv idle observation still said false. Online duplicate-request
   suppression also prevented an immediate intentional restart.

**Proven boundary/handler weaknesses, not claims of observed user races:**

- A delayed native `start-file` for a retired entry could replace a newer event
  owner; unlabelled start/end pairs treated `None == None` as ownership.
- Same-path pending replacement could accept old live EOF before the new load
  was confirmed. The synthetic boundary is demonstrated; normal mpv command/event
  scheduling is not claimed to reproduce every injected ordering.
- Disconnect retained event timestamps; property updates could repopulate timing
  state after Stop; Stop plus rescan still issued gapless priming. These calls are
  proved, but audible Stop resurrection from these variants alone is not claimed.
- Post-shutdown owner-thread polling could load a resolver fallback, consume a
  Creator result, process a MPRIS action or rescan. The normal `run` loop exits
  before shutdown, and workers do not call these methods: this is **internal
  robustness hardening**, not a demonstrated background callback into curses.
- An extraction completing after `close` could publish/cache a successful result.
  The real worker thread and close barrier are exercised with Events. No stale
  result is shown reaching normal playback after the loop has exited.
- Repeated player shutdown repeated resource teardown; a watcher accepted events
  during its stop callback and retained an actionable batch.

Reconnect recovery is also tested positively. The engine does not replay missed
start/file-loaded notifications. Merely discarding caches or adding a pending latch
would lose liveness. The final implementation confirms the live native entry on
both sides of a fresh decoder-position query. A real mpv reconnect/same-path reload
smoke confirmed entry 1 remained 1 across reconnect and became 2 after Stop/reload.
Recovery timestamps are marked `resynchronized`; they describe observation time,
not measured historical load latency.

### Ownership mechanism and deletion policy

No player-wide generation counter or event-sourcing system was introduced.
[mpv's playlist documentation](https://mpv.io/manual/stable/#property-list)
specifies entry IDs unique within a core lifetime;
[its allocator](https://github.com/mpv-player/mpv/blob/master/common/playlist.c)
assigns increasing IDs. The controller retains a native-ID retirement boundary,
a pending-load latch and a reconnect-observation flag. This relies on MeowPlayer's
existing replace/forward-reservation usage; it does not implement arbitrary
external mpv playlist rewinding or replacement of the mpv process behind the socket.

The gapless reservation additionally remembers the outgoing native entry ID.
A new occurrence of the same path can therefore commit once; repeat-current's
same-entry seek does not look like a new occurrence. Existing path-based history
semantics are retained: replaying A records a listen, but does not add A to its
own Previous history.

For a reserved B already audible when rescan removes B, Round 1's established
**deleted-current stops** policy is retained. Reconcile the audible handoff,
consume its queue occurrence, retain departed A in history, then stop and clear
current because B has no library index. Do not teleport to another file or create
a phantom library row. A deleted B cannot receive a new catalog listen row; a
surviving B is recorded exactly once. Explicit-sequence stop-at-end remains intact.

## BA-CMUS-027 — Reopening transport must not restore historical playback

- **cmus reference:** [7e232cd](https://github.com/cmus/cmus/commit/7e232cdaf20895f4120fb11dee0bcf7a53e31e24).
- **cmus failure:** Output write failure lacked reopening recovery; the patch also checks whether ALSA prepare succeeded before retrying.
- **Relevant MeowPlayer subsystem:** Persistent mpv IPC reconnection and cached playback observations.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE. Audio-device reopening is not JSON IPC reconnection; recovery authority is the transferable invariant.
- **Equivalent scenario:** Disconnect A; reconnect without replayed start events; select B before recovery; reconnect one fade deck; recover while the live entry changes.
- **Invariant:** A reconnect observes current engine ownership and never replays an old load or invents completion.
- **Regression:** `test_disconnect_discards_cached_completion_timestamps`, `test_replaced_socket_cannot_publish_or_close_new_connection`, `test_reconnect_during_load_recovers_from_live_entry_not_old_events`, `test_reconnect_cannot_confirm_same_path_retired_entry`, `test_reconnect_active_fade_keeps_deck_and_single_commit`, `test_ipc_reconnect_cannot_restore_old_track_after_manual_selection`, `test_reconnect_online_observation_cannot_duplicate_playlist_advance`, `test_reconnect_recovery_does_not_mix_two_native_entries`, `test_reconnect_recovery_drops_completion_from_departed_native_entry`.
- **Pre-fix result:** Cached completion survives disconnect; stale start replaces entry 2 with 1; missing notifications have no live recovery. Replaced-socket rejection and fade commit-once already pass. During implementation an extra regression caught recovery retaining the departed entry's cached completion; it failed before correction too.
- **Fix:** Clear connection-local playback observations on disconnect; preserve native retirement state; recover readiness only from a stable live entry and decoder position. Drop observations when that native owner changes. No reconnect load replay.
- **Post-fix result:** PASS, plus real mpv reconnect/same-path reload smoke. Existing socket-level resubscription/no-command-replay tests also pass.
- **Status:** PROVEN EVENT-BOUNDARY WEAKNESSES corrected; synthetic stale-event ordering is not presented as an observed mpv emitter race.

## BA-CMUS-028 — Stop/reload must retire state belonging to the old stream

- **cmus reference:** [f0f3f07](https://github.com/cmus/cmus/commit/f0f3f0773f3652d228cefc18c94c9081c446570b).
- **cmus failure:** Incomplete input-plugin reset on stream stop/restart mixed PCM data with Shoutcast metadata.
- **Relevant MeowPlayer subsystem:** Native event ownership, pending local load, logical Stop and explicit Play.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE. Decoder buffers stay in mpv; Python owns load/Stop lifecycle state.
- **Equivalent scenario:** A is replaced by A; delayed old start/EOF arrives; Stop receives late position/restart; immediate explicit Play arrives before idle observation.
- **Invariant:** Path equality and late timestamps do not establish load ownership; stale work cannot override Stop, but newer explicit Play can.
- **Regression:** `test_late_same_path_start_cannot_reclaim_previous_load`, `test_unlabelled_end_is_not_proof_of_current_load`, `test_stop_rejects_late_position_and_restart`, `test_same_path_reload_cannot_advance_before_new_file_loaded`, `test_stop_rescan_cannot_prime_or_consume_stale_handoff`, `test_explicit_play_after_stop_wins_even_before_idle_observation`, `test_online_explicit_play_after_stop_bypasses_duplicate_guard`, `test_stop_blocks_stale_crossfade_completion`, `test_stop_during_online_resolution_rejects_late_future`.
- **Pre-fix result:** Old entry 10 overwrites 11; unlabelled EOF is accepted; pending same-path EOF advances; explicit Play leaves `_playback_stopped=True`; stopped rescan primes again. Stop's fade cancellation and resolver detachment already pass.
- **Fix:** Reject retired/regressed native starts and unidentified ends; gate event timing after Stop; require pending-load confirmation, including in `current_path`; suppress stopped priming; let explicit Play reload independent of delayed idle status and online duplicate guard.
- **Post-fix result:** PASS, including positive new-load EOF and explicit Play controls.
- **Status:** Explicit Play defect is PROVEN and reachable. Synthetic event acceptance and post-Stop priming are proven boundary weaknesses; additional audible resurrection is unproven.

## BA-CMUS-029 — Preserve the resource while distinguishing its playback occurrences

- **cmus reference:** [f74298c](https://github.com/cmus/cmus/commit/f74298c7a51de65e65a5705a43f8101c4b05a62f).
- **cmus failure:** Input close initialization erased the filename needed for reopening; the fix preserves resource identity across close.
- **Relevant MeowPlayer subsystem:** Same-path gapless occurrence, same-URL online loads and Stop/replay.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE. Preserving the resource must not preserve authority of its old playback occurrence.
- **Equivalent scenario:** Queue A while A plays; mpv naturally loads the second A, with or without rescan. Also resolved/fallback loads use the same URL; Stop then A again.
- **Invariant:** Same resource can have distinct load ownership; queue/listen consumption happens once for each new occurrence.
- **Regression:** `test_same_track_gapless_occurrence_consumes_queue_once` (normal and rescan variants), `test_same_url_new_entry_ignores_old_eof`, `test_stop_then_same_track_load_accepts_only_new_entry`.
- **Pre-fix result:** Same-track handoff returns False or retains `[A,C]` instead of `[C]`. Native-ID old EOF rejection for resolved/fallback URLs and Stop/replay already passes.
- **Fix:** Capture outgoing native entry ID with a gapless reservation; compare it when path equality would otherwise hide a handoff, including rescan reconciliation.
- **Post-fix result:** PASS; repeated sync cannot consume C or append self-history. Path-only legacy fakes keep their existing behavior.
- **Status:** PROVEN reachable logical-ownership bug fixed; old labelled EOF was already protected.

## BA-CMUS-030 — Library refresh must reconcile the actual playing identity

- **cmus reference:** [654225f](https://github.com/cmus/cmus/commit/654225f459fe15eefbb386c69c675cc71ddc1531).
- **cmus failure:** Cache refresh updated other references but omitted current player information.
- **Relevant MeowPlayer subsystem:** Rescan, natural gapless handoff, catalog statistics, Stash and explicit sequence.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE.
- **Equivalent scenario:** A → B happens inside enumeration or metadata loading while C is removed; B itself disappears; clear the remaining queue after handoff.
- **Invariant:** Reconcile audible B before replacing its reservation; commit history, queue and surviving catalog listen once; preserve explicit stop-at-end.
- **Regression:** `test_rescan_during_natural_gapless_handoff_does_not_double_commit`, `test_rescan_removed_audible_incoming_stops_without_teleport`, `test_handoff_rescan_preserves_explicit_end_after_queue_clear`.
- **Pre-fix result:** Current remains `/music/0.flac` instead of `/music/1.flac`; removed audible B leaves current 0 rather than stopped/None.
- **Fix:** Snapshot reserved path, observe engine after slow scan/metadata work, reconcile path lists before index remapping and reprime only after committing. Preserve the deletion policy described above.
- **Post-fix result:** PASS for both scan phases, no reload, one new prime, one surviving listen, one queue consumption and one history entry.
- **Status:** PROVEN reachable rescan/handoff bug fixed. This does not claim a transaction spanning every mpv command and filesystem operation.

## BA-CMUS-031 — Cancellation must remain authoritative when active work finishes

- **cmus reference:** [04f4e6c](https://github.com/cmus/cmus/commit/04f4e6c67e07acc252c8c67994a1a5b676f1e344).
- **cmus failure/change:** Historical cancellation enhancement replaces coarse job types with matching callbacks and waits until active cancellation completes; the old wait lacked the explicit cancellation-completion loop. No separate user crash is asserted from this patch alone.
- **Relevant MeowPlayer subsystem:** Active YouTube extraction and owner-thread resolver/Creator result processing.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE.
- **Equivalent scenario:** Extraction returns successfully after close signals cancellation; resolver failure or Creator result becomes ready after player shutdown.
- **Invariant:** Producers may finish, but cancellation/teardown removes their authority over caches and playback/UI.
- **Regression:** `test_active_resolver_close_does_not_publish_late_success`, `test_resolver_completion_after_shutdown_cannot_load_mpv`, `test_creator_completion_after_shutdown_cannot_update_ui`.
- **Pre-fix result:** Closed resolver caches successful late extraction; explicit post-shutdown polling loads fallback or appends Creator items.
- **Fix:** Recheck closed/cancelled under resolver's existing condition before publishing success; establish player shutdown barrier before closing workers, detach its future, and reject later result polling.
- **Post-fix result:** PASS; real resolver worker exits under Event-controlled release, future terminates with cancellation error, closed requests remain cancelled, no mpv load/UI result application.
- **Status:** PROVEN worker publication weakness and INTERNAL ROBUSTNESS weaknesses fixed. Normal UI-loop reachability of post-shutdown polling is not proven.

## BA-CMUS-032 — Worker/UI lock inversion and result ownership

- **cmus reference:** [8235a28](https://github.com/cmus/cmus/commit/8235a2867c845d61dd7bef11aafdd6c3e3640d8a), later [reverted](https://github.com/cmus/cmus/commit/5ac26dd4c3968bb5c95825ebdd36e7049f21a326).
- **cmus failure:** UI waited for player lock while player waited for UI; delegation attempted to break the inversion but explicitly did not solve exit deadlocks. Its later revert is relevant evidence against copying that architecture.
- **Relevant MeowPlayer subsystem:** Metadata, LRCLIB, catalog and UI-thread polling.
- **Classification:** C — ALREADY PROTECTED for the translated worker-to-UI/catalog boundary.
- **Equivalent scenario:** An active metadata fetch completes after stop while catalog/player lifetime ends.
- **Invariant:** Worker publishes detached data, never mutates SQLite/playback or calls curses; UI does not wait for a worker which waits for UI.
- **Regression:** `test_active_metadata_worker_only_publishes_data_not_catalog_writes`; post-teardown consumer extension in `test_shutdown_rejects_metadata_watch_and_lyrics_polling` belongs to BA-033.
- **Pre-fix result:** Active-worker test PASS. Source confirms only owner-thread `process_online_metadata` writes catalog. LRCLIB's daemon updates manager-owned pending records under its lock; persistent writes happen when the UI polls. Album art is synchronous. There is no worker-held player lock or UI callback in these paths.
- **Fix:** None for the existing worker architecture. Teardown polling guard is separately attributed to BA-033.
- **Post-fix result:** PASS with deterministic Event rendezvous and completed worker join; no sleeps, network or SQLite worker access.
- **Status:** PROTECTED for this invariant, not proof that every network operation terminates immediately. LRCLIB cancellation/join was not redesigned.

## BA-CMUS-033 — Teardown must have one owner and a terminal boundary

- **cmus reference:** [2caa838](https://github.com/cmus/cmus/commit/2caa838c64dac8ac657c8bff14f8188eb1cac8eb).
- **cmus failure:** Both MAD callback and input close could close the same fd because the callback did not invalidate it; a Termux fdsan failure was suspected, not conclusively attributed.
- **Relevant MeowPlayer subsystem:** Player shutdown, watcher batches, external action/result consumers and deck teardown.
- **Classification:** B — CONCEPTUALLY TRANSFERABLE. Python lifecycle reentry is not cmus's raw-fd mechanism.
- **Equivalent scenario:** Repeat shutdown; Watchdog callback during observer stop; queued MPRIS action or metadata/lyrics/watch polling after shutdown.
- **Invariant:** Establish teardown authority first; closing again or receiving an old result cannot reopen playback or mutate torn-down state.
- **Regression:** `test_shutdown_is_idempotent_and_stale_fade_cannot_commit`, `test_watchdog_event_during_stop_cannot_resurrect_batch`, `test_late_mpris_action_after_shutdown_cannot_play`, `test_shutdown_rejects_metadata_watch_and_lyrics_polling`; old-socket close rejection is also covered in BA-027.
- **Pre-fix result:** Two mpv quits; pending watcher batch survives stop; MPRIS Next changes current from 0 to 1; post-shutdown polling rescans.
- **Fix:** Idempotent player barrier before producer shutdown; invalidate transition/future authority; guard owner-thread consumers; set watcher's closed flag and discard pending batch under its existing lock before stopping observer.
- **Post-fix result:** PASS. No new broad exception handling, sleeps, or worker/UI locking architecture.
- **Status:** PROVEN INTERNAL ROBUSTNESS weaknesses corrected. Normal loop does not dispatch playback commands after shutdown; callbacks merely enqueue, so user-reachable teardown resurrection is not asserted.

## BA-CMUS-034 — PulseAudio activation flags can make connection wait forever

- **cmus reference:** [2386273](https://github.com/cmus/cmus/commit/2386273e8a22838af82e0f9df3acbef98cea782d).
- **cmus failure:** `PA_CONTEXT_NOFAIL` could hang when socket activation started a PulseAudio server which then failed.
- **Relevant MeowPlayer subsystem:** None owning PulseAudio contexts; decoding/output is mpv's responsibility.
- **Classification:** D — NOT APPLICABLE.
- **Equivalent scenario:** No Python PulseAudio activation flag or libpulse wait loop exists to patch.
- **Invariant:** Keep output/backend recovery in mpv; do not import cmus's output plugin implementation into Python.
- **Regression:** None for backend-specific flags. IPC reconnection is tested separately in BA-027.
- **Pre-fix result:** NOT APPLICABLE.
- **Fix:** None.
- **Post-fix result:** NOT APPLICABLE.
- **Status:** Documented exclusion, not a guarantee about mpv/libpulse internals.

## Round 3 proof, validation and limits

Test-first sequence:

1. After correcting two fixture mistakes (import name and frozen metadata setup),
   the first 23 methods produced **19 failing assertions, zero errors** before
   production edits. These are not 19 distinct user bugs.
2. Reconnect liveness and changed-owner recovery were added with failing checks
   before their corrections. The real top-level smoke exposed early path
   confirmation; `current_path` now respects pending native-load ownership.
3. The final same-track queued-occurrence method failed in **both** normal and
   rescan variants before the native reservation-ID correction.
4. All **32 final methods** were replayed against the saved Round 2 modules from
   their own working directory (not current repository modules): **24 failing
   assertions, zero errors**. No missing-method shim or production revert was
   needed. Representative assertions: `10 != 11` (old start wins),
   `True is not false` (Stop remains after Play), `[0, 2] != [2]` (same-track queue),
   and `/music/0.flac != /music/1.flac` (rescan handoff).
5. Final fixed archaeology suite: **77 tests, PASS** (17 + 28 + 32).
   Round 1/2 regression files and the document prefix remain byte-for-byte intact.

Remaining **UNPROVEN / deliberately bounded** cases:

- Arbitrary reordering of unlabelled file-loaded/restart/property messages on the
  *same* socket cannot be assigned an invented generation after arrival. Native
  starts/ends are checked; unidentified end events are rejected. Supported mpv's
  ordered IPC and native IDs remain assumptions, not path-based proof. Very old
  engines without useful IDs may lose automatic online completion rather than
  guess ownership; that compatibility path was not validated.
- A prior load whose start was never observed cannot be retired by the native-ID
  high-water mark alone. Rapid same-path replacements with such unseen starts
  are not proved safe under arbitrary reordered delivery. The ordered real-mpv
  reload smoke passes; this is a protocol-boundary limit, not a reproduced
  user-reachable race or a reason to claim a universal generation guarantee.
- Natural handoff can occur between the final engine observation and subsequent
  playlist commands. The scan/enrichment blocking window and same-file occurrence
  are covered; a cross-process atomic rescan/playlist transaction is not claimed.
- Same native-entry seek/repeat can have delayed observations. Fresh EOF checks
  remain in place; real audible seek/fade quality under load is outside this pass.
- Socket recreation for the same live mpv process is covered; an unrelated mpv
  process replacing the socket with restarted IDs is outside controller lifetime.
- Resolver/Creator joins remain bounded; metadata and LRCLIB network work may
  finish after shutdown. Result authority is guarded; universal prompt termination,
  process-tree cleanup and every third-party blocking call are not proved.
- MPRIS's thread can enqueue after teardown, but the player consumer refuses it.
  No direct producer-to-player mutation path was found. Direct arbitrary calls to
  public `play` after teardown are outside the worker callback model.

**Recommendation: MOVE TO MPD.** The specific Round 2 ownership boundaries have
now been attacked with failing and passing controls, including the distinct
same-file occurrence bug. Remaining caveats are explicit protocol/liveness and
cross-process transaction limits, not evidence of a new major cmus ownership
class requiring Round 4. This is not a claim that no bugs remain.

Final local validation for Round 3:

- **77 archaeology tests PASS**; **332 complete-suite tests PASS, zero skips**
  with `MEOW_REAL_MPV=1`, Python 3.14. Earlier sandbox runs could not bind local
  sockets; the successful full run used permitted local IPC/loopback access.
- Real mpv HTTP/header/local-isolation test: **PASS**. Existing CI gapless/manual
  advancement and top-level construction/playback/persistence/shutdown smokes:
  **PASS**, temporary WAV fixtures and null audio.
- Additional real mpv reconnect/same-path reload: **PASS**. Real natural A → A
  gapless handoff consumed the queued A exactly once: **PASS**.
- Isolated D-Bus MPRIS registration/read via `busctl`: **PASS**. Existing metadata
  wire-marshalling tests, including malformed Unicode, also pass in the suite.
- First-party compilation and `git diff --check`: **PASS**. Round 1/2 test files
  and document prefix verified against the saved initial tree. Version stays
  **0.20.0**; existing packaging artifacts were not edited.
- Wheel and sdist built offline with `python -m build --no-isolation`; all listed
  first-party modules compared byte-for-byte with archive contents: **PASS**.
- Built wheel installed offline into `/tmp/round3-install` venv using local
  system-site dependencies (`--no-index --no-deps --ignore-installed`): **PASS**.
  Installed `--version` and `--help`: **PASS**, with module origin verified inside
  that venv from `/tmp`, outside the source tree. This tests the wheel, not a fresh
  dependency resolver/network installation.
- Remote CI, Twine and a full Arch chroot build: **not run**. No branch was pushed
  and no remote workflow dispatched; local workflows supplied the smoke scripts.
