"""Round 2: deterministic ownership attacks; BA-CMUS-014 onward in the document."""
import json
import queue
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import test_audio
from lyrics_support import LyricsManager
from album_art import AlbumArtManager
import test_bug_archaeology_cmus as round1
from meowplayer import MPVController, MeowPlayer, TrackMetadata
from meow_catalog import LibraryCatalog
from library_watcher import LibraryWatcher
from test_rescan import metadata_for
from youtube_online import YouTubeTrack, YouTubeStreamResolver


class Round2Tests(unittest.TestCase):
    def player(self, current=0):
        p = round1.CmusArchaeologyTests().player(current=current)
        p.album_art = SimpleNamespace(enabled=False)
        p.youtube_results = []
        p.external_actions = queue.SimpleQueue()
        p.mpris = mock.Mock()
        return p

    def fade(self):
        p = self.player()
        p.playback_sequence = [0, 1, 2, 3]
        p.catnip_stash = [1, 2, 3]
        p.crossfade_seconds = 5
        p.crossfade_mpv = test_audio.FakeMPV()
        p.prime_crossfade_next()
        self.assertTrue(p._begin_crossfade(5, now=10))
        return p

    def rescan(self, p, paths):
        round1.CmusArchaeologyTests().rescan(p, paths)

    def controller(self):
        c = MPVController.__new__(MPVController)
        c._init_ipc()
        c._close_ipc = mock.Mock()
        c.command = mock.Mock(return_value={'error': 'success', 'data': False})
        c._ensure_ipc = mock.Mock()
        return c

    def events(self, c, *messages):
        sock = mock.Mock()
        sock.recv.side_effect = [b''.join(json.dumps(m).encode() + b'\n' for m in messages), b'']
        c._ipc_socket = sock
        c._read_ipc(sock)

    def test_queue_head_mutation_cancels_uncommitted_crossfade(self):
        for action in ('remove', 'clear', 'reorder'):
            with self.subTest(action=action):
                p = self.fade()
                outgoing = p.mpv
                if action == 'remove':
                    p.remove_from_stash()
                elif action == 'clear':
                    p.clear_stash()
                else:
                    p.move_stash_item(1)
                self.assertFalse(p._crossfade_active)
                self.assertFalse(p._finish_crossfade())
                self.assertIs(p.mpv, outgoing)
                self.assertEqual(p.current, 0)
                self.assertEqual(p.history, [])
                self.assertEqual(p.mpris_snapshot()['metadata']['title'], p.meta(0).title)

    def test_deleting_later_queue_item_preserves_active_fade(self):
        p = self.fade()
        incoming = p.crossfade_mpv
        p.stash_selected = 1
        p.remove_from_stash()
        self.assertTrue(p._crossfade_active)
        self.assertTrue(p._finish_crossfade())
        self.assertIs(p.mpv, incoming)
        self.assertEqual(p.current, 1)
        self.assertEqual(p.catnip_stash, [3])
        self.assertEqual(p.history, [0])

    def test_rescan_deleting_later_file_preserves_active_decks(self):
        p = self.fade()
        incoming, outgoing = p.crossfade_mpv, p.mpv
        starts = incoming.stop_calls
        self.rescan(p, [p.songs[0], p.songs[1], p.songs[3]])
        self.assertTrue(p._crossfade_active)
        self.assertEqual(incoming.stop_calls, starts)
        self.assertIs(p.mpv, outgoing)
        self.assertTrue(p._finish_crossfade())
        self.assertIs(p.mpv, incoming)
        self.assertEqual(p.catnip_stash, [2])

    def test_active_deck_identity_survives_raw_index_reorder(self):
        p = self.fade()
        a, b, c, d = p.songs
        self.rescan(p, [d, c, b, a])
        self.assertTrue(p._crossfade_active)
        self.assertEqual(p.songs[p.current], a)
        self.assertTrue(p._finish_crossfade())
        self.assertEqual(p.songs[p.current], b)
        self.assertEqual(p.mpv.path, str(b))
        self.assertEqual([p.songs[i] for i in p.history], [a])
        self.assertEqual(p.mpris_snapshot()['metadata']['url'], b.as_uri())

    def test_manual_navigation_cannot_be_overruled_by_old_fade(self):
        # BA-026: Previous at the first album/sequence track with repeat enabled.
        p = self.player(current=3)
        p.playback_sequence = [3, 0]
        p.repeat = True
        p.previous_song()
        self.assertEqual(p.current, 0)
        for direction in ('next', 'previous'):
            with self.subTest(direction=direction):
                p = self.fade()
                p.history = [3]
                getattr(p, direction + '_song')()
                expected = 1 if direction == 'next' else 3
                self.assertEqual(p.current, expected)
                history, stash = list(p.history), list(p.catnip_stash)
                self.assertFalse(p._finish_crossfade())
                self.assertEqual(p.current, expected)
                self.assertEqual(p.history, history)
                self.assertEqual(p.catnip_stash, stash)

    def test_crossfade_completion_consumes_queue_once(self):
        p = self.fade()
        self.assertTrue(p._finish_crossfade())
        self.assertFalse(p._finish_crossfade())
        self.assertEqual(p.current, 1)
        self.assertEqual(p.catnip_stash, [2, 3])
        self.assertEqual(p.history, [0])

    def test_removed_incoming_file_cannot_commit_after_rescan(self):
        p = self.fade()
        self.rescan(p, [p.songs[0], p.songs[2], p.songs[3]])
        self.assertFalse(p._crossfade_active)
        self.assertFalse(p._finish_crossfade())
        self.assertEqual(p.current, 0)
        self.assertEqual(p.history, [])

    def test_explicit_sequence_end_stops_all_next_paths(self):
        for mode in ('manual', 'automatic', 'gapless', 'crossfade'):
            with self.subTest(mode=mode):
                p = self.player(current=2)
                p.playback_sequence = [3, 0, 2]
                if mode == 'crossfade':
                    p.crossfade_seconds = 5
                    p.crossfade_mpv = test_audio.FakeMPV()
                self.assertIsNone(p.peek_next_index())
                p.prime_gapless_next()
                self.assertIsNone(p.gapless_next_index)
                self.assertIsNone(p.crossfade_next_index)
                p.next_song(automatic=mode != 'manual')
                self.assertEqual(p.current, 2)
                self.assertEqual(p.mpv.loaded, [])
                self.assertGreater(p.mpv.stop_calls, 0)

    def test_repeat_at_sequence_end_keeps_current_without_consuming_queue(self):
        p = self.player(current=2)
        p.playback_sequence = [3, 2]
        p.repeat = True
        p.catnip_stash = [1]
        self.assertIsNone(p.peek_next_index())
        p.next_song(automatic=True)
        self.assertEqual(p.current, 2)
        self.assertEqual(p.mpv.stop_calls, 0)

    def test_pounce_cycles_only_inside_explicit_sequence(self):
        p = self.player(current=2)
        p.playback_sequence = [3, 2]
        p.shuffle = True
        p.shuffle_bag = []
        for _ in range(4):
            target = p.peek_next_index()
            p.next_song(automatic=True)
            self.assertEqual(p.current, target)
            self.assertIn(p.current, [3, 2])

    def test_entire_sequence_deleted_does_not_become_unrestricted(self):
        p = self.player(current=0)
        p.playback_sequence = [1, 2]
        self.rescan(p, [p.songs[0], p.songs[3]])
        self.assertEqual(p.playback_sequence, [])
        self.assertIsNone(p.peek_next_index())
        p.next_song()
        self.assertEqual(p.current, 0)
        self.assertEqual(p.mpv.loaded, [])
        p.last_state_save = 0
        state = p.state_snapshot()
        self.assertTrue(state['playback_sequence_active'])

    def test_invalid_final_sequence_entry_never_loads_modulo_index(self):
        p = self.player(current=2)
        p.playback_sequence = [0, 2, 99]
        self.assertIsNone(p.peek_next_index())
        p.next_song()
        self.assertEqual(p.current, 2)
        self.assertEqual(p.mpv.loaded, [])

    def test_current_outside_ordered_sequence_stops_instead_of_restarting(self):
        p = self.player(current=2)
        p.playback_sequence = [3, 1]
        self.assertIsNone(p.peek_next_index())
        p.next_song()
        self.assertEqual(p.current, 2)

    def test_stash_only_playback_stops_when_last_entry_is_consumed(self):
        p = self.player()
        p.catnip_stash = [2]
        p.play_stash_position(0)
        loads = list(p.mpv.loaded)
        p.next_song(automatic=True)
        self.assertEqual(p.current, 2)
        self.assertEqual(p.mpv.loaded, loads)
        self.assertGreater(p.mpv.stop_calls, 0)

    def test_late_end_file_cannot_replace_current_entry_events(self):
        for reason in ('eof', 'error', 'stop'):
            with self.subTest(reason=reason):
                c = self.controller()
                self.events(c, {'event': 'start-file', 'playlist_entry_id': 10},
                            {'event': 'start-file', 'playlist_entry_id': 11},
                            {'event': 'end-file', 'playlist_entry_id': 10, 'reason': reason})
                self.assertNotIn('end-file', c.playback_snapshot())
                p = self.player(current=None)
                p.mpv = c
                tracks = [YouTubeTrack(str(i), str(i), 'Cat', 200, f'https://example.test/{i}')
                          for i in range(2)]
                p.online_current = tracks[0]
                p.online_load_state = 'streaming'
                p.set_online_playlist_context(tracks, 0)
                p._online_load_sent = 1.0
                p.stream_resolver = None
                p.advance_online_playlist = mock.Mock(return_value=True)
                self.assertFalse(p.process_online_playlist_streaming())
                p.advance_online_playlist.assert_not_called()
                self.events(c, {'event': 'end-file', 'playlist_entry_id': 11, 'reason': 'eof'})
                self.assertEqual(c.playback_snapshot()['end-reason'], 'eof')
                c.command.return_value = {'error': 'success', 'data': True}
                self.assertTrue(p.process_online_playlist_streaming())
                p.advance_online_playlist.assert_called_once()

    def test_load_and_stop_invalidate_old_entry_events(self):
        for action in ('begin_load', 'stop'):
            with self.subTest(action=action):
                c = self.controller()
                self.events(c, {'event': 'start-file', 'playlist_entry_id': 4})
                getattr(c, action)()
                self.events(c, {'event': 'end-file', 'playlist_entry_id': 4, 'reason': 'eof'},
                            {'event': 'playback-restart'})
                self.assertNotIn('end-file', c.playback_snapshot())
                self.assertNotIn('playback-restart', c.playback_snapshot())

    def test_cached_eof_is_confirmed_live_after_seek_or_replacement(self):
        c = self.controller()
        c._properties['eof-reached'] = True
        c.command.return_value = {'error': 'success', 'data': False}
        self.assertFalse(c.get_property('eof-reached'))
        c.command.assert_called_with('get_property', 'eof-reached')

    def test_gapless_rejects_unreserved_old_path(self):
        p = self.player(current=1)
        p.gapless_next_index = 2
        p.mpv.path = str(p.songs[0])
        self.assertFalse(p.sync_gapless_transition())
        self.assertEqual(p.current, 1)
        self.assertEqual(p.history, [])

    def test_late_online_resolution_cannot_replace_local_selection(self):
        p = self.player()
        future = Future()
        p._online_future = future
        p.online_current = YouTubeTrack('old', 'Old', 'Cat', 20, 'https://example.test/old')
        p.online_load_state = 'resolving'
        p.play(2, sequence=[2, 3])
        future.set_result(SimpleNamespace(valid=lambda: True, url='https://example.test/stale'))
        self.assertFalse(p.refresh_online_playback_state())
        self.assertFalse(p._finish_online_resolve())
        self.assertEqual(p.current, 2)
        self.assertEqual(p.mpv.loaded[-1], p.songs[2])

    def test_unusual_paths_round_trip_catalog_load_uri_and_watcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = [' space\tquote\'"\\;[]()& 猫🐈e\u0301.flac', 'x' * 240 + '.flac']
            nested = root / 'dir with spaces ' / '日本語' / 'nested'
            nested.mkdir(parents=True)
            paths = [nested / name for name in names]
            for path in paths:
                path.write_bytes(b'audio placeholder')
            p = self.player()
            p.music_dir = root
            self.assertEqual(set(p.find_songs()), set(paths))
            catalog = LibraryCatalog(root, root / 'catalog.sqlite')
            self.addCleanup(catalog.close)
            for path in paths:
                meta = TrackMetadata(**vars(metadata_for(path)))
                catalog.put(path, path.stat(), meta)
                self.assertEqual(catalog.get(path, path.stat())['filename'], path.name)
                self.rescan(p, [path])
                p.play(0, sequence=[0])
                self.assertEqual(p.mpv.loaded[-1], path)
                path.with_suffix('.lrc').write_text('[00:01.00]猫 lyric', encoding='utf-8')
                lyrics = LyricsManager(online_enabled=False, cache_dir=root / 'lyrics-cache')
                self.assertIsNotNone(lyrics.load(path))
                cover = path.parent / 'cover.png'
                cover.write_bytes(b'invalid image')
                with mock.patch.dict('os.environ', {'XDG_CACHE_HOME': str(root)}):
                    art = AlbumArtManager(enabled=False)
                self.assertEqual(art._folder_cover(path), cover)
                self.assertIsNone(art.cover_for(path))
                self.assertEqual(p.mpris_snapshot()['metadata']['url'], path.as_uri())
                watcher = LibraryWatcher(root, {'.flac'}, enabled=False)
                watcher.record_event([path], now=1)
                self.assertEqual(watcher.poll(now=2)['paths'], (str(path.resolve()),))

    def test_renamed_future_path_is_removed_without_wrong_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f'{n}.flac' for n in 'abc']
            for path in paths:
                path.touch()
            p = self.player()
            self.rescan(p, paths)
            p.play(0, sequence=[0, 1, 2])
            p.catnip_stash = [1]
            renamed = paths[1].with_name('renamed.flac')
            paths[1].rename(renamed)
            self.rescan(p, [paths[0], renamed, paths[2]])
            self.assertEqual(p.catnip_stash, [])
            self.assertEqual(p.peek_next_index(), 2)
            self.assertEqual(p.current, 0)

    def test_current_rename_stops_gracefully_without_selecting_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.flac'
            path.touch()
            p = self.player()
            self.rescan(p, [path])
            p.play(0, sequence=[0])
            renamed = path.with_name('new.flac')
            path.rename(renamed)
            self.rescan(p, [renamed])
            self.assertIsNone(p.current)
            self.assertIsNone(p.gapless_next_index)
            self.assertGreater(p.mpv.stop_calls, 0)

    def test_broken_symlink_is_ignored_without_changing_surviving_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hidden = root / '.content'
            hidden.mkdir()
            track = hidden / '猫.flac'
            track.touch()
            link = root / 'alias.flac'
            link.symlink_to(track)
            p = self.player()
            p.music_dir = root
            self.assertIn(track, p.find_songs())
            track.unlink()
            self.assertEqual(p.find_songs(), [])

    def test_playlist_preserves_whitespace_in_real_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / ' leading.flac '
            path.touch()
            p = self.player()
            self.rescan(p, [path])
            p.catnip_stash = [0]
            playlist = root / 'queue.m3u'
            p.save_stash(playlist)
            p.clear_stash()
            p.load_stash(playlist)
            self.assertEqual(p.catnip_stash, [0])
            # A relative leading-space filename is also discoverable normally.
            relative = root / ' leading.flac'
            relative.touch()
            p.music_dir = root
            self.assertIn(relative, MeowPlayer.find_songs(p))
            self.rescan(p, [relative])
            playlist.write_text(relative.name + '\n', encoding='utf-8')
            p.load_stash(playlist)
            self.assertEqual(p.catnip_stash, [0])

    def test_closed_resolver_cannot_accept_new_background_work(self):
        resolver = YouTubeStreamResolver(None)
        resolver.close()
        track = YouTubeTrack('x', 'X', 'Cat', 2, 'https://example.test/x')
        self.assertTrue(resolver.request(track).cancelled())

    def test_pending_local_replacement_cannot_advance_on_old_eof(self):
        for gapless in ('no', 'weak', 'yes'):
            with self.subTest(gapless=gapless):
                p = self.player(current=1)
                p.gapless_mode = gapless
                p.playback_sequence = [0, 1, 2]
                p._awaiting_mpv_path = True
                p.mpv.path = str(p.songs[0])
                p.mpv.properties['eof-reached'] = True
                self.assertFalse(p.process_local_eof())
                self.assertEqual(p.current, 1)
                p.mpv.path = str(p.songs[1])
                p.mpv.properties['eof-reached'] = False
                self.assertFalse(p.process_local_eof())
                p.mpv.properties['eof-reached'] = True
                self.assertTrue(p.process_local_eof())
                self.assertEqual(p.current, 2)

    def test_remote_stop_cannot_restart_crossfade_on_late_eof(self):
        p = self.fade()
        p.external_actions.put(('stop', ()))
        p.process_external_actions()
        loads = list(p.mpv.loaded)
        p.mpv.properties.update({'time-pos': 119, 'duration': 120, 'eof-reached': True})
        p.process_crossfade_transition(now=20)
        p.process_local_eof()
        self.assertFalse(p._crossfade_active)
        self.assertEqual(p.current, 0)
        self.assertEqual(p.mpv.loaded, loads)
        self.assertEqual(p.catnip_stash, [1, 2, 3])
        self.assertEqual(p.mpris_snapshot()['playback_status'], 'Stopped')

    def test_repeat_eof_does_not_consume_queued_track(self):
        p = self.player()
        p.repeat = True
        p.catnip_stash = [1]
        p.next_song(automatic=True)
        self.assertEqual(p.current, 0)
        self.assertEqual(p.catnip_stash, [1])


if __name__ == '__main__':
    unittest.main()
