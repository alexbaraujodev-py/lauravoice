import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import laura_voice_api as laura_voice


class FakeResponse:
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self):
        return self.data


class VoiceFlowTests(unittest.TestCase):
    @patch('urllib.request.urlopen')
    def test_audio_to_reply_to_speech(self, mock):
        mock.side_effect = [
            FakeResponse(json.dumps({'text': 'Olá, Laura'}).encode()),
            FakeResponse(json.dumps({'output': [{'type': 'message', 'content': [
                {'type': 'output_text', 'text': 'Oi, Alexandre!'}]}]}).encode()),
            FakeResponse(b'RIFF-audio'),
        ]
        client = laura_voice.OpenAIClient('fake-key')
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.wav'
            source.write_bytes(b'RIFF-input')
            text = client.transcribe(source, 'gpt-4o-mini-transcribe')
            answer = client.reply([{'role': 'user', 'content': text}], 'gpt-4.1-mini')
            target = Path(folder) / 'output.wav'
            client.speak(answer, target, 'coral')
            self.assertEqual(answer, 'Oi, Alexandre!')
            self.assertEqual(target.read_bytes(), b'RIFF-audio')
        requests = [call.args[0] for call in mock.call_args_list]
        self.assertIn(b'RIFF-input', requests[0].data)
        self.assertEqual(json.loads(requests[1].data)['input'][0]['content'], 'Olá, Laura')
        self.assertFalse(json.loads(requests[1].data)['store'])
        self.assertEqual(json.loads(requests[2].data)['input'], answer)

    @patch('urllib.request.urlopen')
    def test_quota_failure_has_actionable_message(self, mock):
        mock.side_effect = urllib.error.HTTPError('url', 429, 'quota', {}, None)
        with self.assertRaisesRegex(laura_voice.ApiError, 'saldo insuficiente'):
            laura_voice.OpenAIClient('fake-key').reply([], 'test')

    @patch('urllib.request.urlopen', return_value=FakeResponse(b'{"output": []}'))
    def test_empty_reply_is_rejected(self, mock):
        with self.assertRaisesRegex(laura_voice.ApiError, 'texto'):
            laura_voice.OpenAIClient('fake-key').reply([], 'test')


if __name__ == '__main__':
    unittest.main()
