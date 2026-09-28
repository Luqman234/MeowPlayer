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
