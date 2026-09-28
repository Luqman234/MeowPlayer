"""Behavioral translations; provenance and limits live in docs/BUG_ARCHAEOLOGY.md.

No cmus implementation is used. Helpers reuse MeowPlayer's existing fake deck.
"""
import curses
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import meow_persistence
import mpris_support
from meowplayer import TrackMetadata
import test_audio
from test_rescan import metadata_for
from youtube_online import YouTubeTrack


class CmusArchaeologyTests(unittest.TestCase):
    def player(self, count=4, current=0):
        player = test_audio.AudioEngineTests().make_player(count, current)
        player.selected = 0
        player.search_query = ""
        player.search_active = False
        player.library_view = "songs"
        player.drill_artist = player.drill_album = None
        player.smart_playlist_key = None
        player.music_dir = Path('/music')
        player.metadata = [TrackMetadata(**vars(metadata_for(path))) for path in player.songs]
        player.meta = lambda index: player.metadata[index]
        return player

    def rescan(self, player, paths):
        player.find_songs = lambda: list(paths)
        player.load_library_metadata = lambda **kw: [TrackMetadata(**vars(metadata_for(p))) for p in paths]
        player.ordered_library_indices = lambda: list(range(len(player.songs)))
        player.queue_missing_metadata_enrichment = lambda: None
        player.rescan_library()

    def test_001_deleted_future_reservation_is_rebuilt_by_identity(self):
        for crossfade in (False, True):
            with self.subTest(crossfade=crossfade):
                p = self.player()
                p.playback_sequence = [0, 1, 2, 3]
                if crossfade:
                    p.crossfade_seconds = 5
                    p.crossfade_mpv = test_audio.FakeMPV()
                p.prime_gapless_next()
                current, deleted, successor, last = p.songs
                self.rescan(p, [current, successor, last])
                self.assertEqual(p.songs[p.current], current)
                self.assertEqual(p.mpv.loaded, [])
                self.assertEqual(p.mpv.stop_calls, 0)
                if crossfade:
                    self.assertEqual(p.crossfade_mpv.path, str(successor))
                    self.assertEqual(p.songs[p.crossfade_next_index], successor)
                else:
                    self.assertEqual(p.mpv.primed[-1], successor)
                    self.assertEqual(p.songs[p.gapless_next_index], successor)

    def test_001_deleted_current_stops_and_discards_incoming_deck(self):
        p = self.player()
        p.crossfade_seconds = 5
        p.crossfade_mpv = test_audio.FakeMPV()
        p.prime_gapless_next()
        self.rescan(p, p.songs[1:])
        self.assertIsNone(p.current)
        self.assertEqual(p.mpv.stop_calls, 1)
        self.assertIsNone(p.crossfade_next_index)
        self.assertGreater(p.crossfade_mpv.stop_calls, 1)

    def test_002_clear_queue_preserves_current_and_sequence(self):
        p = self.player(current=2)
        p.playback_sequence = [2, 0, 3]
        p.catnip_stash = [1, 1]
        p.prime_gapless_next()
        p.clear_stash()
        self.assertEqual(p.current, 2)
        self.assertEqual(p.mpv.loaded, [])
        self.assertEqual(p.mpv.primed[-1], p.songs[0])
        p.next_song()
        self.assertEqual(p.current, 0)

    def test_003_rescan_clamps_queue_selection_before_remove(self):
        p = self.player()
        p.catnip_stash = [1, 2, 3]
        p.stash_selected = 2
        self.rescan(p, p.songs[:3])
        self.assertEqual(p.stash_selected, 1)
        p.remove_from_stash()
        self.assertEqual(p.catnip_stash, [1])
        self.assertEqual(p.current, 0)

    def test_003_reordering_queue_replaces_gapless_reservation(self):
        p = self.player()
        p.catnip_stash = [1, 2, 3]
        p.prime_gapless_next()
        p.move_stash_item(1)
        self.assertEqual(p.mpv.primed[-1], p.songs[2])
        p.mpv.path = str(p.songs[2])
        self.assertTrue(p.sync_gapless_transition())
        self.assertEqual(p.current, 2)
        self.assertEqual(p.catnip_stash, [1, 3])
        self.assertEqual(p.history, [0])

    def test_004_shuffle_outside_sequence_never_uses_scan_order(self):
        p = self.player(current=0)
        p.shuffle = True
        p.playback_sequence = [3, 1]
        p.shuffle_bag = [0, 2, 99, 3, 3, 1]
        expected = p.peek_next_index()
        self.assertIn(expected, [3, 1])
        p.next_song(automatic=True)
        self.assertEqual(p.current, expected)
        self.assertTrue(set(p.shuffle_bag) <= {3, 1})

    def test_005_no_match_search_visits_each_track_at_most_once(self):
        p = self.player()
        p.search_query = '////missing'
        original = p.search_haystack
        seen = set()
        def bounded(index):
            self.assertNotIn(index, seen, 'search wrapped')
            seen.add(index)
            return original(index)
        p.search_haystack = bounded
        self.assertEqual(p.filtered_song_indices(), [])
        self.assertEqual(seen, set(range(4)))

    def test_006_restricted_search_with_stale_selection_and_empty_library(self):
        p = self.player()
        p.selected = 999
        p.drill_artist = 'Artist'
        p.drill_album = ('Artist', 'Album')
        p.search_query = 'no matching album'
        self.assertEqual(p.filtered_song_indices(), [])
        p.songs = []
        self.assertEqual(p.filtered_song_indices(), [])
        p.handle_search_key('\n')
        self.assertFalse(p.search_active)
        p.handle_search_key('\x1b')
        self.assertEqual(p.selected, 0)

    def test_007_mpris_text_is_utf8_without_nul_and_preserves_valid_unicode(self):
        def variant(signature, value):
            return SimpleNamespace(signature=signature, value=value)
        good = '猫 🐈 Cafe\u0301'
        with mock.patch.object(mpris_support, 'Variant', side_effect=variant):
            for field in ('title', 'artist', 'album', 'album_artist', 'genre', 'url', 'art_url'):
                with self.subTest(field=field):
                    result = mpris_support._metadata_variants({field: good + '\udcff\x00'})
                    values = [v.value for k, v in result.items() if k != 'mpris:trackid']
                    self.assertEqual(len(values), 1)
                    text = values[0][0] if isinstance(values[0], list) else values[0]
                    text.encode('utf-8', errors='strict')
                    self.assertNotIn('\x00', text)
                    self.assertTrue(text.startswith(good))

    def test_008_explicit_selection_wins_over_current_during_shuffle(self):
        p = self.player(current=0)
        p.shuffle = True
        p.selected = 1
        p.ordered_library_indices = lambda: [3, 2, 0, 1]
        p.play_selected_library_song()
        self.assertEqual(p.current, 2)
        self.assertEqual(p.playback_sequence, [3, 2, 0, 1])
        self.assertEqual(p.history, [0])

    def test_009_restore_uses_paths_and_keeps_next_order(self):
        p = self.player(current=None)
        sequence = [str(p.songs[3]), '/deleted.flac', str(p.songs[1])]
        p.playback_sequence = p.restore_saved_index_list(sequence, unique=True)
        p.restore_session({'current_track': str(p.songs[3]), 'position': 0})
        self.assertEqual(p.current, 3)
        self.assertTrue(p.mpv.properties['pause'])
        self.assertEqual(p.peek_next_index(), 1)
        self.assertEqual(p.mpv.loaded, [p.songs[3]])

    def test_009_corrupt_state_encoding_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_bytes(b'{"current_track": "\xff"}')
            with mock.patch.object(meow_persistence, 'state_path', return_value=path):
                self.assertEqual(meow_persistence.load_state(), meow_persistence.DEFAULT_STATE)

    def test_009_invalid_saved_track_does_not_load(self):
        for value in (17, {}, ['track'], '/deleted.flac'):
            with self.subTest(value=value):
                p = self.player(current=None)
                p.restore_session({'current_track': value})
                self.assertIsNone(p.current)
                self.assertEqual(p.mpv.loaded, [])

    def test_010_prompt_resize_preserves_input_and_restores_terminal(self):
        p = self.player()
        screen = mock.Mock()
        screen.getmaxyx.side_effect = [(24, 80), (1, 1), (0, 0), (24, 200)]
        screen.get_wch.side_effect = ['猫', curses.KEY_RESIZE, 'a', '\n']
        screen.addstr.side_effect = curses.error('resized')
        with mock.patch('meowplayer.curses.noecho'), mock.patch('meowplayer.curses.curs_set'):
            self.assertEqual(p.prompt_text(screen, 'Search'), '猫a')
        screen.nodelay.assert_called_with(True)
        screen.timeout.assert_called_with(100)

    def test_012_activate_empty_view_does_not_load(self):
        p = self.player()
        p.selected = 500
        p.ordered_library_indices = lambda: []
        p.activate_library_selection()
        self.assertEqual(p.current, 0)
        self.assertEqual(p.mpv.loaded, [])

    @unittest.skipUnless(mpris_support.MPRIS_AVAILABLE, 'dbus-next unavailable')
    def test_007_metadata_marshals_on_real_dbus_wire(self):
        from dbus_next import Message
        metadata = mpris_support._metadata_variants({
            'title': '猫\udcff\x00', 'artist': 'Cafe\u0301 🐈',
        })
        message = Message(
            path='/org/mpris/MediaPlayer2',
            member='Metadata', signature='a{sv}', body=[metadata],
        )
        self.assertTrue(message._marshall())

    def test_013_old_eof_and_current_error_do_not_advance_online_playlist(self):
        p = self.player()
        tracks = [YouTubeTrack(str(i), str(i), 'Cat', 200, f'https://example.test/{i}')
                  for i in range(2)]
        p.online_current = tracks[0]
        p.online_load_state = 'streaming'
        p.set_online_playlist_context(tracks, 0)
        p._online_load_sent = 10.0
        p.stream_resolver = None
        p.advance_online_playlist = mock.Mock(return_value=True)
        for timestamp, reason in ((9.0, 'eof'), (11.0, 'error'), (11.0, 'stop')):
            with self.subTest(timestamp=timestamp, reason=reason):
                p.mpv.playback_events = {'end-file': timestamp, 'end-reason': reason}
                self.assertFalse(p.process_online_playlist_streaming(now=12.0))
                p.advance_online_playlist.assert_not_called()
                self.assertIs(p.online_current, tracks[0])
        p.mpv.playback_events = {'end-file': 11.0, 'end-reason': 'eof'}
        self.assertTrue(p.process_online_playlist_streaming(now=12.0))
        p.advance_online_playlist.assert_called_once_with(now=12.0)


if __name__ == '__main__':
    unittest.main()
