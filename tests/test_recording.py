import array
import sys
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import wave
import laura_voice


def pcm(volume):
    values = array.array('h', [volume] * 320)
    if sys.byteorder != 'little':
        values.byteswap()
    return values.tobytes()


class RecordingTests(unittest.TestCase):
    def test_initial_silence_does_not_finish(self):
        detector = laura_voice.SilenceDetector()
        self.assertFalse(any(detector.feed(pcm(0)) for _ in range(100)))
        self.assertFalse(detector.started)

    def test_brief_noise_does_not_start_speech(self):
        detector = laura_voice.SilenceDetector()
        detector.feed(pcm(1000))
        detector.feed(pcm(0))
        self.assertFalse(detector.started)

    def test_pause_resets_when_speech_resumes(self):
        detector = laura_voice.SilenceDetector(silence_seconds=0.4)
        for _ in range(15):
            detector.feed(pcm(1000))
        for _ in range(15):
            self.assertFalse(detector.feed(pcm(0)))
        detector.feed(pcm(1000))
        for _ in range(19):
            self.assertFalse(detector.feed(pcm(0)))
        self.assertTrue(detector.feed(pcm(0)))

    @patch('laura_voice.os.read')
    @patch('laura_voice.selectors.DefaultSelector')
    @patch('laura_voice.subprocess.Popen')
    def test_records_valid_wav_and_stops_capture(self, popen, selectors, read):
        process = popen.return_value
        process.poll.return_value = None
        selector = selectors.return_value.__enter__.return_value
        selector.select.return_value = [(Mock(), 1)]
        read.return_value = pcm(1000) * 15 + pcm(0) * 25
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'voice.wav'
            laura_voice.record_until_silence(output, 'default', silence_seconds=0.4)
            with wave.open(str(output)) as audio:
                self.assertEqual(audio.getframerate(), 16000)
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertGreater(audio.getnframes(), 0)
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        process.stdout.close.assert_called_once()

    @patch('laura_voice.os.read', return_value=pcm(0) * 100)
    @patch('laura_voice.selectors.DefaultSelector')
    @patch('laura_voice.subprocess.Popen')
    def test_no_speech_cleans_up_capture(self, popen, selectors, read):
        process = popen.return_value
        process.poll.return_value = None
        selectors.return_value.__enter__.return_value.select.return_value = [(Mock(), 1)]
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(laura_voice.LocalError, 'Não detectei fala'):
                laura_voice.record_until_silence(Path(folder) / 'voice.wav', 'default', start_timeout=1)
        process.terminate.assert_called_once()
        process.stdout.close.assert_called_once()
