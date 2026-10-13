import argparse
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import Mock, patch
import laura_voice


class LocalTests(unittest.TestCase):
    def test_external_server_rejected(self):
        with self.assertRaises(laura_voice.LocalError):
            laura_voice.LocalModel('https://api.openai.com/v1')

    def test_local_reply_payload_and_history(self):
        model = laura_voice.LocalModel('http://127.0.0.1:1234/v1', 'local')
        model.request = Mock(return_value={'choices': [{'message': {'content': 'Olá!'}}]})
        history = [{'role': 'user', 'content': 'Oi'}]
        self.assertEqual(model.reply(history), 'Olá!')
        payload = model.request.call_args.args[1]
        self.assertEqual(payload['messages'][1:], history)
        self.assertFalse(payload['stream'])
        self.assertEqual(history, [{'role': 'user', 'content': 'Oi'}])

    @patch('laura_voice.play')
    @patch('laura_voice.synthesize')
    def test_turn_generates_and_plays_reply(self, synthesize, play):
        model = Mock()
        model.reply.return_value = 'Oi, Alexandre!'
        args = argparse.Namespace(tts='piper', voice='voice.onnx', no_play=False, output_device='default')
        history = laura_voice.run_turn('Oi', [], model, Path('out.wav'), args)
        synthesize.assert_called_once_with('Oi, Alexandre!', Path('out.wav'), 'piper', 'voice.onnx')
        play.assert_called_once()
        self.assertEqual(history[-1]['content'], 'Oi, Alexandre!')

    def test_empty_reply_error(self):
        model = laura_voice.LocalModel('http://localhost:1234/v1', 'local')
        model.request = Mock(return_value={'choices': []})
        with self.assertRaises(laura_voice.LocalError):
            model.reply([])

    def test_reasoning_exhausts_generation_budget(self):
        model = laura_voice.LocalModel('http://localhost:11434/v1', 'local', 4096)
        model.request = Mock(return_value={'choices': [{
            'message': {'content': None, 'reasoning': 'Pensando...'},
            'finish_reason': 'length',
        }]})
        with self.assertRaisesRegex(laura_voice.LocalError, 'limite'):
            model.reply([])
        self.assertEqual(model.request.call_args.args[1]['max_tokens'], 4096)

    def test_tool_only_reply_has_actionable_error(self):
        model = laura_voice.LocalModel('http://localhost:11434/v1', 'local')
        model.request = Mock(return_value={'choices': [{
            'message': {'content': '', 'tool_calls': [{'id': 'call1'}]},
            'finish_reason': 'tool_calls',
        }]})
        with self.assertRaisesRegex(laura_voice.LocalError, 'ferramentas'):
            model.reply([])


class ServerErrorTests(unittest.TestCase):
    def test_connection_error_identifies_configured_server(self):
        model = laura_voice.LocalModel('http://localhost:11434/v1', 'local')
        model.opener = Mock()
        model.opener.open.side_effect = urllib.error.URLError('offline')
        with self.assertRaisesRegex(laura_voice.LocalError, 'localhost:11434/v1'):
            model.check()

    def test_empty_models_identifies_configured_server(self):
        model = laura_voice.LocalModel('http://localhost:11434/v1')
        model.request = Mock(return_value={'data': []})
        with self.assertRaisesRegex(laura_voice.LocalError, 'localhost:11434/v1'):
            model.check()
