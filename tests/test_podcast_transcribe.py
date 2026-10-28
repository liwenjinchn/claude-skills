"""Run with: python3 -m unittest discover -s tests -v (no Whisper required)."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'podcast-transcribe/scripts/transcribe.py'
spec = importlib.util.spec_from_file_location('podcast_transcribe', SCRIPT)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


class LongAudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'episode.md'
        self.chunks = self.root / 'episode.work/chunks'

    def fake_ffmpeg(self, cmd, **kwargs):
        for i in range(2):
            Path(cmd[-1] % i).write_bytes(b'audio')

    def run_long(self, ext='.mp3'):
        return t.transcribe_long('episode' + ext, 'Episode', 'source',
                                 'mlx/model', self.out, 4000, 30)

    def status(self):
        return json.loads((self.out.with_suffix('.work') / 'status.json').read_text())

    def test_first_run_and_completed_resume(self):
        for ext in ('.mp3', '.m4a'):
            with self.subTest(ext=ext), tempfile.TemporaryDirectory() as tmp:
                self.out = Path(tmp) / 'episode.md'
                with patch.object(t.subprocess, 'run', side_effect=self.fake_ffmpeg) as ffmpeg, \
                     patch.object(t, 'transcribe', side_effect=lambda audio, model, offset: ([(offset, '正文')], 'test')) as whisper:
                    segs, _ = self.run_long(ext)
                    self.assertEqual(segs, [(0, '正文'), (1800, '正文')])
                    self.assertEqual(whisper.call_count, 2)
                    self.assertTrue(all(call.args[0].endswith(ext) for call in whisper.call_args_list))
                    self.assertIn('[00:30:00] 正文', self.out.read_text())
                    self.assertEqual(self.status()['state'], 'done')
                    ffmpeg.reset_mock()
                    whisper.reset_mock()
                    self.assertEqual(self.run_long(ext)[0], segs)
                    ffmpeg.assert_not_called()
                    whisper.assert_not_called()

    def test_resume_after_transcription_failure(self):
        for ext in ('.mp3', '.m4a'):
            with self.subTest(ext=ext), tempfile.TemporaryDirectory() as tmp:
                self.out = Path(tmp) / 'episode.md'
                with patch.object(t.subprocess, 'run', side_effect=self.fake_ffmpeg), \
                     patch.object(t, 'transcribe', side_effect=[([(0, '已完成')], 'test'), RuntimeError('interrupted')]):
                    with self.assertRaises(RuntimeError):
                        self.run_long(ext)
                self.assertFalse(self.out.exists())
                self.assertIn('已完成', self.out.with_suffix('.partial.md').read_text())
                with patch.object(t.subprocess, 'run') as ffmpeg, \
                     patch.object(t, 'transcribe', return_value=([(1800, '续跑')], 'test')) as whisper:
                    self.assertEqual(self.run_long(ext)[0], [(0, '已完成'), (1800, '续跑')])
                    ffmpeg.assert_not_called()
                    whisper.assert_called_once()
                    self.assertEqual(whisper.call_args.kwargs['offset'], 1800)

    def test_empty_split_never_finishes(self):
        for target in ('ffmpeg', 'split_audio'):
            with self.subTest(target=target):
                mock = patch.object(t.subprocess, 'run') if target == 'ffmpeg' else patch.object(t, 'split_audio', return_value=[])
                with mock, patch.object(t, 'transcribe') as whisper:
                    with self.assertRaisesRegex(RuntimeError, '分段失败'):
                        self.run_long()
                    whisper.assert_not_called()
                self.assertFalse(self.out.exists())
                self.assertFalse(self.out.with_suffix('.partial.md').exists())
                self.assertNotEqual(self.status()['state'], 'done')

    def test_failed_split_leftovers_are_rebuilt(self):
        def fail(cmd, **kwargs):
            Path(cmd[-1] % 0).write_bytes(b'incomplete')
            Path(cmd[-1] % 9).write_bytes(b'stale')
            raise subprocess.CalledProcessError(1, cmd)
        with patch.object(t.subprocess, 'run', side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_long()
        self.assertFalse(self.out.exists())
        self.assertNotEqual(self.status()['state'], 'done')
        with patch.object(t.subprocess, 'run', side_effect=self.fake_ffmpeg) as ffmpeg, \
             patch.object(t, 'transcribe', return_value=([(0, '正文')], 'test')) as whisper:
            self.run_long()
            ffmpeg.assert_called_once()
            self.assertEqual(whisper.call_count, 2)
            self.assertFalse((self.chunks / 'chunk-00009.mp3').exists())

    def test_old_zero_chunk_done_and_mixed_cache(self):
        self.chunks.mkdir(parents=True)
        (self.chunks / 'chunk-00000.mp3').write_bytes(b'old')
        (self.chunks / 'chunk-00000.m4a').write_bytes(b'foreign')
        t.write_status(self.out.with_suffix('.work'), state='done', total_chunks=0)
        with patch.object(t.subprocess, 'run', side_effect=self.fake_ffmpeg) as ffmpeg, \
             patch.object(t, 'transcribe', return_value=([(0, '正文')], 'test')) as whisper:
            self.run_long()
            ffmpeg.assert_called_once()
            self.assertEqual(whisper.call_count, 2)
            self.assertTrue(all(c.args[0].endswith('.mp3') for c in whisper.call_args_list))

    def test_missing_cached_chunk_forces_resplit(self):
        self.chunks.mkdir(parents=True)
        (self.chunks / 'chunk-00000.mp3').write_bytes(b'old')
        t.write_status(self.out.with_suffix('.work'), state='transcribing', total_chunks=2)
        with patch.object(t.subprocess, 'run', side_effect=self.fake_ffmpeg) as ffmpeg, \
             patch.object(t, 'transcribe', return_value=([(0, '正文')], 'test')):
            self.run_long()
            ffmpeg.assert_called_once()
            self.assertEqual(self.status()['total_chunks'], 2)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg not installed')
    def test_real_ffmpeg_split_and_reuse(self):
        # Real synthetic short audio + mocked Whisper, not a macOS long-audio test.
        for ext, codec in (('.mp3', 'libmp3lame'), ('.m4a', 'aac')):
            with self.subTest(ext=ext):
                audio = self.root / ('input' + ext)
                subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2.5',
                                '-c:a', codec, str(audio)], check=True)
                out = self.root / (codec + '.md')
                with patch.object(t, 'transcribe', side_effect=lambda audio, model, offset: ([(offset, 'test')], 'test')):
                    segs, _ = t.transcribe_long(str(audio), 'Test', str(audio), 'mlx/model', out, 2.5, 1 / 60)
                self.assertGreaterEqual(len(segs), 2)
                self.assertIn('[00:00:01] test', out.read_text())
                with patch.object(t, 'split_audio') as split, patch.object(t, 'transcribe') as whisper:
                    resumed, _ = t.transcribe_long(str(audio), 'Test', str(audio), 'mlx/model', out, 2.5, 1 / 60)
                    self.assertEqual(resumed, segs)
                    split.assert_not_called()
                    whisper.assert_not_called()


if __name__ == '__main__':
    unittest.main()
