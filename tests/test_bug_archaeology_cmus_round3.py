"""Focused ownership/lifecycle regressions; provenance in BUG_ARCHAEOLOGY.md."""
from dataclasses import replace
import queue
import threading
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest import mock

import test_bug_archaeology_cmus_round2 as round2
from meowplayer import MPVController, TrackMetadata
from library_watcher import LibraryWatcher
from youtube_online import YouTubeTrack, YouTubeStreamResolver
from online_metadata import OnlineMetadataManager, OnlineMetadataResult
from test_rescan import metadata_for


class Round3Tests(unittest.TestCase):
    player = round2.Round2Tests.player
    controller = round2.Round2Tests.controller
    events = round2.Round2Tests.events
    fade = round2.Round2Tests.fade

    def track(self):
        return YouTubeTrack('same', 'Same', 'Cat', 120, 'https://example.test/same')

    def shutdown_player(self, p):
        p.persist_state = mock.Mock()
        p.playback_saboteur = mock.Mock()
        for name in ('youtube_search_session', 'youtube_download_session', 'creator_session'):
            if not hasattr(p, name):
                setattr(p, name, None)
        for name in ('youtube', 'online_metadata', 'library_watcher', 'album_art', 'visualizer'):
            setattr(p, name, mock.Mock())
        if not hasattr(p, 'stream_resolver'):
            p.stream_resolver = mock.Mock()
        p.shutdown()

    def scanning_handoff(self, *, remove=2, phase='scan'):
        p = self.player()
        p.catnip_stash = [1, 3]
        p.playback_sequence = [0, 1]
        p.prime_gapless_next()
        paths = [s for i, s in enumerate(p.songs) if i != remove]
        incoming = p.songs[1]
        def scan():
            if phase == 'scan':
                p.mpv.path = str(incoming)
            return paths
        def metadata(**kwargs):
            if phase == 'metadata':
                p.mpv.path = str(incoming)
            p.catalog = mock.Mock()
            p.catalog.play_stats.return_value = {}
            return [TrackMetadata(**vars(metadata_for(s))) for s in paths]
        p.find_songs = scan
        p.load_library_metadata = metadata
        p.ordered_library_indices = lambda: list(range(len(p.songs)))
        p.queue_missing_metadata_enrichment = lambda: None
        return p, incoming

    def test_disconnect_discards_cached_completion_timestamps(self):
        c = self.controller()
        c.playback_events = {k: 999 for k in ('start-file', 'file-loaded', 'playback-restart', 'end-file', 'audio-reconfig', 'first-nonzero-time-pos')}
        c.playback_events['end-reason'] = 'eof'
        MPVController._close_ipc(c)
        self.assertEqual(c.playback_snapshot(), {})

    def test_replaced_socket_cannot_publish_or_close_new_connection(self):
        c = self.controller()
        old, new = mock.Mock(), mock.Mock()
        c._ipc_socket = new
        old.recv.return_value = b'{"event":"start-file","playlist_entry_id":1}\n'
        c._read_ipc(old)
        self.assertEqual(c.playback_snapshot(), {})
        MPVController._close_ipc(c, expected=old)
        self.assertIs(c._ipc_socket, new)
        new.close.assert_not_called()

    def test_late_same_path_start_cannot_reclaim_previous_load(self):
        c = self.controller()
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 10})
        c.load('/music/same.flac')
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 11},
                    {'event': 'file-loaded'})
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 10},
                    {'event': 'end-file', 'playlist_entry_id': 10, 'reason': 'eof'})
        self.assertEqual(c.playback_snapshot().get('entry-id'), 11)
        self.assertNotIn('end-file', c.playback_snapshot())

    def test_unlabelled_end_is_not_proof_of_current_load(self):
        c = self.controller()
        self.events(c, {'event': 'start-file'}, {'event': 'end-file', 'reason': 'eof'})
        self.assertNotIn('end-file', c.playback_snapshot())

    def test_stop_rejects_late_position_and_restart(self):
        c = self.controller()
        c.stop()
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 10},
                    {'event': 'playback-restart'},
                    {'event': 'property-change', 'name': 'time-pos', 'data': 40})
        self.assertEqual(c.playback_snapshot(), {})

    def test_same_path_reload_cannot_advance_before_new_file_loaded(self):
        p = self.player()
        c = self.controller()
        p.mpv = c
        p.gapless_mode = 'no'
        c.current_path = lambda: str(p.songs[0])
        c.get_property = lambda name: name == 'eof-reached'
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 10})
        c.load(p.songs[0])
        self.assertFalse(p.process_local_eof())
        self.assertEqual(p.current, 0)
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 11}, {'event': 'file-loaded'})
        self.assertTrue(p.process_local_eof())
        self.assertEqual(p.current, 1)

    def test_same_url_new_entry_ignores_old_eof(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback):
                c = self.controller()
                self.events(c, {'event': 'start-file', 'playlist_entry_id': 1})
                if fallback:
                    c.load(self.track().url)
                else:
                    c.load_stream(SimpleNamespace(url=self.track().url, headers={}))
                self.events(c, {'event': 'start-file', 'playlist_entry_id': 2},
                            {'event': 'end-file', 'playlist_entry_id': 1, 'reason': 'eof'})
                self.assertNotIn('end-file', c.playback_snapshot())

    def test_stop_then_same_track_load_accepts_only_new_entry(self):
        c = self.controller()
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 1})
        c.stop()
        c.load('/music/same.flac')
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 2},
                    {'event': 'end-file', 'playlist_entry_id': 1, 'reason': 'eof'},
                    {'event': 'file-loaded'})
        self.assertNotIn('end-file', c.playback_snapshot())
        self.assertIn('file-loaded', c.playback_snapshot())

    def test_rescan_during_natural_gapless_handoff_does_not_double_commit(self):
        for phase in ('scan', 'metadata'):
            with self.subTest(phase=phase):
                p, incoming = self.scanning_handoff(phase=phase)
                primed = len(p.mpv.primed)
                p.rescan_library()
                self.assertEqual(p.songs[p.current], incoming)
                self.assertFalse(p.sync_gapless_transition())
                self.assertEqual(p.history, [0])
                self.assertEqual(p.catnip_stash, [2])
                self.assertEqual(p.mpv.loaded, [])
                p.catalog.record_play.assert_called_once_with(incoming)
                self.assertEqual(len(p.mpv.primed), primed + 1)

    def test_rescan_removed_audible_incoming_stops_without_teleport(self):
        p, incoming = self.scanning_handoff(remove=1)
        p.rescan_library()
        self.assertIsNone(p.current)
        self.assertEqual(p.mpv.stop_calls, 1)
        self.assertEqual(p.mpv.loaded, [])
        self.assertEqual(p.history, [0])

    def test_handoff_rescan_preserves_explicit_end_after_queue_clear(self):
        p, incoming = self.scanning_handoff()
        p.rescan_library()
        p.clear_stash()
        self.assertEqual(p.songs[p.current], incoming)
        self.assertIsNone(p.peek_next_index())
        self.assertEqual(p.history, [0])

    def test_stop_rescan_cannot_prime_or_consume_stale_handoff(self):
        p, incoming = self.scanning_handoff()
        p.external_actions.put(('stop', ()))
        p.process_external_actions()
        primed = list(p.mpv.primed)
        p.rescan_library()
        self.assertEqual(p.mpv.primed, primed)
        self.assertFalse(p.sync_gapless_transition())
        self.assertEqual(p.current, 0)
        self.assertEqual(p.history, [])

    def test_explicit_play_after_stop_wins_even_before_idle_observation(self):
        p = self.player()
        p.external_actions.put(('stop', ()))
        p.process_external_actions()
        p.external_actions.put(('play', ()))
        p.process_external_actions()
        self.assertFalse(p._playback_stopped)
        self.assertEqual(p.mpv.loaded, [p.songs[0]])

    def test_online_explicit_play_after_stop_bypasses_duplicate_guard(self):
        p = self.player(current=None)
        p.online_current = self.track()
        p.online_load_state = 'streaming'
        p.online_load_started_at = 100
        p.stream_resolver = None
        p.external_actions.put(('stop', ()))
        p.process_external_actions()
        with mock.patch('meowplayer.time.monotonic', return_value=100.1):
            p.external_actions.put(('play', ()))
            p.process_external_actions()
        self.assertFalse(p._playback_stopped)
        self.assertEqual(len(p.mpv.loaded), 1)

    def test_stop_blocks_stale_crossfade_completion(self):
        p = self.fade()
        p.external_actions.put(('stop', ()))
        p.process_external_actions()
        self.assertFalse(p._finish_crossfade())
        self.assertFalse(p.process_crossfade_transition(now=30))
        self.assertEqual(p.current, 0)
        self.assertEqual(p.history, [])

    def test_resolver_completion_after_shutdown_cannot_load_mpv(self):
        p = self.player(current=None)
        p.online_current = self.track()
        p.online_load_state = 'resolving'
        p.online_load_started_at = 1
        p._online_resolver_path = 'fresh'
        future = p._online_future = Future()
        self.shutdown_player(p)
        future.set_exception(ValueError('late extraction failure'))
        self.assertFalse(p._finish_online_resolve())
        self.assertEqual(p.mpv.loaded, [])

    def test_creator_completion_after_shutdown_cannot_update_ui(self):
        p = self.player()
        p.creator_session = mock.Mock(results=queue.SimpleQueue())
        session = p.creator_session
        p.creator_items = []
        p.creator_level = 'menu'
        self.shutdown_player(p)
        session.results.put(('track', self.track()))
        self.assertFalse(p.process_creator_browse())
        self.assertEqual(p.creator_items, [])

    def test_late_mpris_action_after_shutdown_cannot_play(self):
        p = self.player()
        self.shutdown_player(p)
        p.external_actions.put(('next', ()))
        p.process_external_actions()
        self.assertEqual(p.current, 0)
        self.assertEqual(p.mpv.loaded, [])

    def test_shutdown_rejects_metadata_watch_and_lyrics_polling(self):
        p = self.player()
        self.shutdown_player(p)
        p.rescan_library = mock.Mock()
        p.lyrics = mock.Mock()
        p.library_watcher.poll.return_value = {'paths': ('/music/1.flac',)}
        p.online_metadata.poll.return_value = [OnlineMetadataResult(path='/music/0.flac', status='not-found', query='')]
        self.assertFalse(p.process_filesystem_watch())
        self.assertFalse(p.process_online_metadata())
        self.assertFalse(p.refresh_current_lyrics())
        p.rescan_library.assert_not_called()
        p.online_metadata.poll.assert_not_called()
        p.lyrics.poll.assert_not_called()

    def test_shutdown_is_idempotent_and_stale_fade_cannot_commit(self):
        p = self.fade()
        self.shutdown_player(p)
        self.assertFalse(p._finish_crossfade())
        p.shutdown()
        self.assertEqual(p.mpv.quit_calls, 1)
        self.assertEqual(p.current, 0)

    def test_watchdog_event_during_stop_cannot_resurrect_batch(self):
        watcher = LibraryWatcher('/music', {'.flac'}, enabled=False)
        watcher.record_event(['/music/a.flac'], now=1)
        watcher._observer = mock.Mock()
        watcher._observer.stop.side_effect = lambda: watcher.record_event(['/music/b.flac'], now=2)
        watcher.stop()
        self.assertIsNone(watcher.poll(now=10))
        self.assertFalse(watcher.record_event(['/music/c.flac'], now=11))

    def test_active_resolver_close_does_not_publish_late_success(self):
        entered, release = threading.Event(), threading.Event()
        stream = SimpleNamespace(valid=lambda: True)
        def extract(*args):
            entered.set()
            self.assertTrue(release.wait(3))
            return stream
        with mock.patch.object(YouTubeStreamResolver, '_extract', side_effect=extract):
            resolver = YouTubeStreamResolver('fake')
            future = resolver.request(self.track())
            try:
                self.assertTrue(entered.wait(3))
                # Release extraction only once close has set the cancellation barrier.
                with mock.patch.object(resolver._thread, 'join', side_effect=lambda **kw: release.set()):
                    resolver.close()
                resolver._thread.join(3)
                self.assertFalse(resolver._thread.is_alive())
                self.assertIsNone(resolver.cached(self.track()))
                self.assertIsNotNone(future.exception(timeout=1))
                self.assertTrue(resolver.request(self.track()).cancelled())
            finally:
                release.set()
                resolver.close()

    def test_active_metadata_worker_only_publishes_data_not_catalog_writes(self):
        entered, release = threading.Event(), threading.Event()
        p = self.player()
        def fetch(snapshot):
            entered.set()
            self.assertTrue(release.wait(3))
            return OnlineMetadataResult(path=snapshot['path'], status='not-found', query='')
        worker = OnlineMetadataManager(client=SimpleNamespace(fetch=fetch))
        metadata = replace(p.metadata[0], artist='Unknown Artist')
        try:
            self.assertTrue(worker.enqueue(metadata))
            self.assertTrue(entered.wait(3))
            worker.stop()
            release.set()
            worker._thread.join(3)
            self.assertFalse(worker._thread.is_alive())
            self.assertEqual(p.mpv.loaded, [])
            self.assertEqual(p.current, 0)
        finally:
            release.set()
            worker.stop()

    def test_reconnect_during_load_recovers_from_live_entry_not_old_events(self):
        c = self.controller()
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 1})
        c.load('/music/same.flac')
        MPVController._close_ipc(c)
        # Start/file-loaded happened while disconnected. Reconnection has no
        # replay of those events, but mpv exposes the current native entry.
        def reply(*args):
            data = ([{'id': 2, 'current': True, 'filename': '/music/same.flac'}]
                    if args[-1] == 'playlist' else 1.25)
            return {'error': 'success', 'data': data}
        c.command.side_effect = reply
        self.assertIn('playback-restart', c.playback_snapshot())
        self.assertEqual(c.playback_snapshot().get('entry-id'), 2)
        self.assertNotIn('end-file', c.playback_snapshot())

    def test_reconnect_cannot_confirm_same_path_retired_entry(self):
        c = self.controller()
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 1})
        c.load('/music/same.flac')
        MPVController._close_ipc(c)
        c.command.side_effect = lambda *args: {'error': 'success', 'data':
            [{'id': 1, 'current': True}] if args[-1] == 'playlist' else 1.25}
        self.assertNotIn('playback-restart', c.playback_snapshot())

    def test_reconnect_active_fade_keeps_deck_and_single_commit(self):
        p = self.fade()
        c = self.controller()
        incoming = p.crossfade_mpv = c
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 1})
        MPVController._close_ipc(c)
        self.assertTrue(p._finish_crossfade())
        self.assertFalse(p._finish_crossfade())
        self.assertIs(p.mpv, incoming)
        self.assertEqual(p.current, 1)
        self.assertEqual(p.history, [0])
        self.assertEqual(p.catnip_stash, [2, 3])

    def test_stop_during_online_resolution_rejects_late_future(self):
        p = self.player(current=None)
        p.online_current = self.track()
        p.online_load_state = 'resolving'
        future = p._online_future = Future()
        p.external_actions.put(('stop', ()))
        p.process_external_actions()
        future.set_result(SimpleNamespace(valid=lambda: True))
        self.assertFalse(p.refresh_online_playback_state())
        self.assertFalse(p._finish_online_resolve())
        self.assertEqual(p.mpv.loaded, [])
        self.assertEqual(p.mpris_snapshot()['playback_status'], 'Stopped')

    def test_ipc_reconnect_cannot_restore_old_track_after_manual_selection(self):
        p = self.player()
        c = self.controller()
        p.mpv = c
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 1})
        MPVController._close_ipc(c)
        p.play(2, sequence=[2, 3])
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 2},
                    {'event': 'file-loaded'},
                    {'event': 'start-file', 'playlist_entry_id': 1},
                    {'event': 'end-file', 'playlist_entry_id': 1, 'reason': 'eof'})
        c.current_path = lambda: str(p.songs[2])
        self.assertFalse(p.sync_gapless_transition())
        self.assertEqual(p.current, 2)
        self.assertEqual(p.history, [0])
        self.assertEqual(c.playback_snapshot().get('entry-id'), 2)
        self.assertNotIn('end-file', c.playback_snapshot())

    def test_reconnect_online_observation_cannot_duplicate_playlist_advance(self):
        p = self.player(current=None)
        c = self.controller()
        p.mpv = c
        p.online_current = self.track()
        p.online_load_state = 'streaming'
        p._online_load_sent = 1
        p.stream_resolver = None
        p.set_online_playlist_context([self.track(), self.track()], 0)
        p.advance_online_playlist = mock.Mock(return_value=True)
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 1},
                    {'event': 'end-file', 'playlist_entry_id': 1, 'reason': 'eof'})
        MPVController._close_ipc(c)
        c.command.side_effect = lambda *args: {'error': 'success', 'data':
            [{'id': 1, 'current': True}] if args[-1] == 'playlist' else False}
        self.assertFalse(p.process_online_playlist_streaming())
        p.advance_online_playlist.assert_not_called()
        self.assertEqual(p.online_current, p.online_playlist_tracks[0])

    def test_reconnect_recovery_does_not_mix_two_native_entries(self):
        c = self.controller()
        MPVController._close_ipc(c)
        responses = iter(([{'id': 1, 'current': True}], 2.0,
                          [{'id': 2, 'current': True}]))
        c.command.side_effect = lambda *args: {'error': 'success', 'data': next(responses)}
        self.assertNotIn('playback-restart', c.playback_snapshot())

    def test_reconnect_recovery_drops_completion_from_departed_native_entry(self):
        c = self.controller()
        MPVController._close_ipc(c)
        self.events(c, {'event': 'start-file', 'playlist_entry_id': 1},
                    {'event': 'end-file', 'playlist_entry_id': 1, 'reason': 'eof'})
        c.command.side_effect = lambda *args: {'error': 'success', 'data':
            [{'id': 2, 'current': True}] if args[-1] == 'playlist' else 0.5}
        snapshot = c.playback_snapshot()
        self.assertEqual(snapshot.get('entry-id'), 2)
        self.assertNotIn('end-file', snapshot)

    def test_same_track_gapless_occurrence_consumes_queue_once(self):
        for rescan in (False, True):
            with self.subTest(rescan=rescan):
                p = self.player()
                p.catnip_stash = [0, 2]
                p.mpv.playback_snapshot = lambda: {'entry-id': p.mpv.entry_id}
                p.mpv.entry_id = 1
                p.prime_gapless_next()
                if rescan:
                    paths = list(p.songs)
                    def scan():
                        p.mpv.entry_id = 2
                        return paths
                    p.find_songs = scan
                    p.load_library_metadata = lambda **kw: p.metadata
                    p.queue_missing_metadata_enrichment = lambda: None
                    p.rescan_library()
                else:
                    p.mpv.entry_id = 2
                    self.assertTrue(p.sync_gapless_transition())
                self.assertEqual(p.current, 0)
                self.assertEqual(p.catnip_stash, [2])
                self.assertEqual(p.history, [])
                self.assertFalse(p.sync_gapless_transition())
                self.assertEqual(p.catnip_stash, [2])
