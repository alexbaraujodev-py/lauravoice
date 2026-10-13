#!/usr/bin/env python3
"""Exemplo de conversa por voz no Linux, sem dependências Python externas."""
import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid

from personality import PERSONALITY
from audio_io import record, play


class ApiError(Exception):
    pass


class OpenAIClient:
    def __init__(self, key):
        self.key = key

    def request(self, endpoint, data, content_type='application/json'):
        request = urllib.request.Request(
            'https://api.openai.com/v1/' + endpoint,
            data=data,
            headers={'Authorization': 'Bearer ' + self.key,
                     'Content-Type': content_type},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            # Do not print server payloads, which may contain submitted content.
            hints = {401: 'Chave inválida.', 403: 'Acesso ao modelo negado.',
                     429: 'Limite da API ou saldo insuficiente.'}
            raise ApiError(hints.get(exc.code, f'Erro HTTP {exc.code} na API.')) from None
        except (urllib.error.URLError, TimeoutError):
            raise ApiError('Falha de conexão com a API. Verifique a rede.') from None

    def json_request(self, endpoint, payload):
        return json.loads(self.request(endpoint, json.dumps(payload).encode()))

    def transcribe(self, path, model):
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in [('model', model), ('language', 'pt')]:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voz.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
        parts.extend([path.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
        result = json.loads(self.request('audio/transcriptions', b''.join(parts),
                                        'multipart/form-data; boundary=' + boundary))
        return result.get('text', '').strip()

    def reply(self, history, model):
        result = self.json_request('responses', {
            'model': model, 'instructions': PERSONALITY, 'input': history,
            'max_output_tokens': 400, 'store': False,
        })
        answer = '\n'.join(
            part.get('text', '')
            for item in result.get('output', []) if item.get('type') == 'message'
            for part in item.get('content', []) if part.get('type') == 'output_text'
        ).strip()
        if not answer:
            raise ApiError('A API não retornou uma resposta em texto.')
        return answer

    def speak(self, text, path, voice):
        payload = {'model': 'gpt-4o-mini-tts', 'voice': voice,
                   'input': text, 'response_format': 'wav',
                   'instructions': 'Fale em português brasileiro, de forma doce, natural e bem-humorada.'}
        path.write_bytes(self.request('audio/speech', json.dumps(payload).encode()))




def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=6, help='Segundos por gravação (1–30).')
    parser.add_argument('--voice', default='coral', help='Voz TTS; por exemplo coral, nova ou shimmer.')
    parser.add_argument('--model', default='gpt-4.1-mini', help='Modelo de resposta disponível na sua API.')
    parser.add_argument('--transcription-model', default='gpt-4o-mini-transcribe')
    parser.add_argument('--input-device', default='default')
    parser.add_argument('--output-device', default='default')
    parser.add_argument('--check', action='store_true', help='Verifica requisitos sem gravar ou chamar a API.')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30:
        parser.error('--seconds deve estar entre 1 e 30.')
    missing = [name for name in ('arecord', 'aplay') if not shutil.which(name)]
    if missing:
        parser.exit(1, 'Instale alsa-utils: faltam ' + ', '.join(missing) + '\n')
    if args.check:
        print('Python e ferramentas de áudio encontrados.')
        print('OPENAI_API_KEY: ' + ('configurada' if os.getenv('OPENAI_API_KEY') else 'não configurada; será solicitada ao iniciar'))
        print('Microfone, reprodução e API ainda não foram testados.')
        return
    key = os.getenv('OPENAI_API_KEY') or getpass.getpass('Chave da API OpenAI (entrada oculta): ')
    if not key.strip():
        parser.exit(1, 'Uma chave da API é necessária.\n')
    client = OpenAIClient(key.strip())
    history = []
    print('LauraVoice — voz gerada por IA. Áudio e texto são enviados à OpenAI.')
    print('Cada rodada usa transcrição, resposta e síntese de voz, cobradas pela API.')
    print('Enter: gravar | q: sair | /limpar: esquecer o histórico desta sessão')
    with tempfile.TemporaryDirectory(prefix='lauravoice-') as directory:
        folder = Path(directory)
        while True:
            command = input('\nVocê > ').strip()
            if command.lower() in ('q', 'sair'):
                break
            if command == '/limpar':
                history.clear()
                print('Histórico apagado.')
                continue
            try:
                print(f'Ouvindo por {args.seconds} segundos...')
                record(folder / 'entrada.wav', args.seconds, args.input_device)
                print('Transcrevendo...')
                text = client.transcribe(folder / 'entrada.wav', args.transcription_model)
                if not text:
                    print('Não entendi nenhuma fala. Tente novamente.')
                    continue
                print('Você:', text)
                candidate = history + [{'role': 'user', 'content': text}]
                answer = client.reply(candidate, args.model)
                history = (candidate + [{'role': 'assistant', 'content': answer}])[-12:]
                print('Laura:', answer)
                print('Preparando áudio...')
                client.speak(answer, folder / 'resposta.wav', args.voice)
                play(folder / 'resposta.wav', args.output_device)
            except subprocess.CalledProcessError:
                print('Falha no áudio. Confira os dispositivos com arecord -L e aplay -L.')
            except (ApiError, ValueError) as exc:
                print('Não foi possível completar a rodada:', exc)
            finally:
                for path in folder.glob('*.wav'):
                    path.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\nLauraVoice encerrado.')
