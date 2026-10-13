#!/usr/bin/env python3
"""LauraVoice local: Whisper + servidor local de IA + Piper (ou eSpeak)."""
import argparse
import array
import math
import selectors
import time
import wave
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from personality import PERSONALITY
from audio_io import record, play

ROOT = Path(__file__).resolve().parent


class LocalError(RuntimeError):
    pass


class LocalModel:
    def __init__(self, url, model=None, max_tokens=1024):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username or parsed.password:
            raise LocalError('Use um servidor HTTP local (localhost ou 127.0.0.1).')
        self.url = url.rstrip('/')
        self.model = model
        self.max_tokens = max_tokens
        # Local traffic must not be sent through an HTTP proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, endpoint, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.url + endpoint, data=data,
                                         headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=180) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise LocalError(f'IA local em {self.url}: erro HTTP {exc.code}. Verifique o modelo e a configuração do servidor.') from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LocalError(f'Não foi possível acessar a IA local em {self.url}. Inicie o servidor Ollama ou LM Studio e confira --server.') from exc
        except ValueError as exc:
            raise LocalError(f'O servidor em {self.url} retornou JSON inválido.') from exc

    def check(self):
        models = self.request('/models').get('data', [])
        if not models:
            raise LocalError(f'Nenhum modelo disponível em {self.url}. Baixe um modelo no Ollama ou carregue um no LM Studio.')
        if not self.model:
            self.model = models[0]['id']
        return self.model

    def reply(self, history):
        if not self.model:
            self.check()
        result = self.request('/chat/completions', {
            'model': self.model,
            'messages': [{'role': 'system', 'content': PERSONALITY}] + history,
            'temperature': 0.7, 'max_tokens': self.max_tokens, 'stream': False,
        })
        try:
            choice = result['choices'][0]
            message = choice['message']
            text = (message.get('content') or '').strip()
        except (KeyError, IndexError, AttributeError, TypeError) as exc:
            raise LocalError('Resposta inválida do modelo local.') from exc
        if not text:
            if choice.get('finish_reason') == 'length':
                raise LocalError('O modelo atingiu o limite antes de responder. Tente --max-tokens 4096.')
            if message.get('tool_calls'):
                raise LocalError('O modelo solicitou ferramentas, mas este assistente só aceita respostas em texto. Use um modelo de conversa sem ferramentas.')
            if message.get('reasoning') or message.get('reasoning_content'):
                raise LocalError('O modelo retornou raciocínio sem resposta final. Tente --max-tokens 4096.')
            raise LocalError('O modelo local respondeu com texto vazio.')
        return text


class SilenceDetector:
    """Detecta atividade por volume em PCM mono, 16 bits, 16 kHz."""
    def __init__(self, silence_seconds=1.2, threshold=500):
        self.silence_seconds = silence_seconds
        self.threshold = threshold
        self.started = False
        self.active_seconds = 0.0
        self.quiet_seconds = 0.0

    def feed(self, pcm):
        samples = array.array('h')
        samples.frombytes(pcm)
        if sys.byteorder != 'little':
            samples.byteswap()
        duration = len(samples) / 16000
        rms = math.sqrt(sum(value * value for value in samples) / len(samples)) if samples else 0
        if rms >= self.threshold:
            self.active_seconds += duration
            self.quiet_seconds = 0.0
            if self.active_seconds >= 0.2:
                self.started = True
        else:
            self.quiet_seconds += duration
            if not self.started:
                self.active_seconds = 0.0
        return self.started and self.quiet_seconds >= self.silence_seconds


def record_until_silence(path, device, max_seconds=30, silence_seconds=1.2,
                         threshold=500, start_timeout=5):
    detector = SilenceDetector(silence_seconds, threshold)
    command = ['arecord', '-q', '-D', device, '-t', 'raw', '-f', 'S16_LE',
               '-r', '16000', '-c', '1', '-d', str(max_seconds)]
    deadline = time.monotonic() + max_seconds + 2
    try:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            try:
                with selectors.DefaultSelector() as selector, wave.open(str(path), 'wb') as output:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(16000)
                    pending = b''
                    captured_seconds = 0.0
                    while time.monotonic() < deadline:
                        if not selector.select(timeout=0.2):
                            continue
                        chunk = os.read(process.stdout.fileno(), 4096)
                        if not chunk:
                            break
                        pending += chunk
                        stop = False
                        while len(pending) >= 640:
                            frame, pending = pending[:640], pending[640:]
                            output.writeframesraw(frame)
                            captured_seconds += 0.02
                            if detector.feed(frame):
                                stop = True
                                break
                            if not detector.started and captured_seconds >= start_timeout:
                                raise LocalError('Não detectei fala. Pressione Enter e tente novamente.')
                        if stop:
                            break
                    if process.poll() not in (None, 0):
                        raise LocalError('Falha ao gravar. Verifique o microfone e --input-device.')
                    if not detector.started:
                        raise LocalError('Não detectei fala. Verifique o microfone ou reduza --silence-threshold.')
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                process.stdout.close()
    except OSError as exc:
        raise LocalError('Não foi possível gravar. Verifique arecord e o dispositivo de áudio.') from exc


class Transcriber:
    def __init__(self, model):
        self.name = model
        self.model = None

    def transcribe(self, path):
        try:
            from faster_whisper import WhisperModel
            if self.model is None:
                self.model = WhisperModel(self.name, device='cpu', compute_type='int8',
                                          cpu_threads=4, local_files_only=True)
            segments, _ = self.model.transcribe(str(path), language='pt', beam_size=3,
                                                vad_filter=True)
            text = ' '.join(segment.text.strip() for segment in segments).strip()
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            raise LocalError('Whisper local indisponível. Execute bash instalar_local.sh para instalar e baixar o modelo.') from exc
        if not text:
            raise LocalError('Não detectei fala. Grave novamente.')
        return text


def synthesize(text, path, engine, voice):
    if engine == 'piper':
        if not Path(voice).is_file() or not Path(voice + '.json').is_file():
            raise LocalError('Voz Piper não encontrada. Execute bash instalar_local.sh.')
        subprocess.run([sys.executable, '-m', 'piper', '-m', voice, '-f', str(path)],
                       input=text, text=True, check=True, timeout=90)
    else:
        executable = shutil.which('espeak-ng')
        if not executable:
            raise LocalError('eSpeak não instalado. Use Piper ou instale espeak-ng.')
        subprocess.run([executable, '-v', 'pt-br+f3', '-s', '165', '-w', str(path), '--stdin'],
                       input=text, text=True, check=True, timeout=30)


def run_turn(text, history, model, audio, args):
    candidate = history + [{'role': 'user', 'content': text}]
    answer = model.reply(candidate)
    print('Laura:', answer, flush=True)
    synthesize(answer, audio, args.tts, args.voice)
    if not args.no_play:
        play(audio, args.output_device)
    return (candidate + [{'role': 'assistant', 'content': answer}])[-12:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=6, help='Duração no modo --fixed-recording.')
    parser.add_argument('--fixed-recording', action='store_true', help='Usa gravação com duração fixa.')
    parser.add_argument('--max-record-seconds', type=int, default=30)
    parser.add_argument('--silence-seconds', type=float, default=1.2)
    parser.add_argument('--silence-threshold', type=int, default=500, help='Volume RMS mínimo (1–32767).')
    parser.add_argument('--server', default='http://127.0.0.1:1234/v1')
    parser.add_argument('--model', help='Identificador do modelo no Ollama ou LM Studio.')
    parser.add_argument('--max-tokens', type=int, default=1024, help='Limite de tokens de geração (padrão: 1024).')
    parser.add_argument('--whisper-model', default='base')
    parser.add_argument('--tts', choices=['piper', 'espeak'], default='piper')
    parser.add_argument('--voice', default=str(ROOT / 'models' / 'pt_BR-cadu-medium.onnx'))
    parser.add_argument('--input-device', default='default')
    parser.add_argument('--output-device', default='default')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--text', help='Testa resposta e síntese sem gravar o microfone.')
    parser.add_argument('--audio-file', type=Path, help='Testa um áudio existente no lugar do microfone.')
    parser.add_argument('--no-play', action='store_true', help='Gera WAV sem reproduzir.')
    parser.add_argument('--output', type=Path, help='Salva o WAV da resposta no teste com --text/--audio-file.')
    args = parser.parse_args()
    if not 1 <= args.max_record_seconds <= 120:
        parser.error('--max-record-seconds deve estar entre 1 e 120.')
    if not 0.2 <= args.silence_seconds <= 5:
        parser.error('--silence-seconds deve estar entre 0.2 e 5.')
    if not 1 <= args.silence_threshold <= 32767:
        parser.error('--silence-threshold deve estar entre 1 e 32767.')
    if args.max_tokens < 1:
        parser.error('--max-tokens deve ser positivo.')
    if not 1 <= args.seconds <= 30:
        parser.error('--seconds deve estar entre 1 e 30.')
    if args.text and args.audio_file:
        parser.error('Escolha --text ou --audio-file.')
    if args.output and not (args.text or args.audio_file):
        parser.error('--output exige --text ou --audio-file.')
    model = LocalModel(args.server, args.model, args.max_tokens)
    if args.check:
        print('Transcrição:', 'instalada' if importlib.util.find_spec('faster_whisper') else 'falta faster-whisper')
        print('Piper:', 'instalado' if importlib.util.find_spec('piper') else 'não instalado')
        print('Voz Piper:', 'encontrada' if Path(args.voice).is_file() else 'não baixada')
        print('eSpeak:', shutil.which('espeak-ng') or 'não instalado')
        print('Microfone:', shutil.which('arecord') or 'não instalado')
        print('Modelo:', model.check())
        return
    model.check()
    transcriber = Transcriber(args.whisper_model)
    print('LauraVoice local — sem API paga. Voz sintética gerada por IA.', flush=True)
    if args.tts == 'espeak':
        print('Usando eSpeak: voz mais robótica; selecione Piper para voz neural.')
    with tempfile.TemporaryDirectory(prefix='lauravoice-local-') as directory:
        folder = Path(directory)
        if args.text or args.audio_file:
            text = args.text or transcriber.transcribe(args.audio_file)
            print('Você:', text)
            output = args.output or folder / 'resposta.wav'
            run_turn(text, [], model, output, args)
            if args.output:
                print('Áudio salvo em:', output)
            return
        history = []
        print('Enter: gravar | q: sair | /limpar: apagar histórico')
        while True:
            command = input('\nVocê > ').strip()
            if command.lower() in ('q', 'sair'):
                break
            if command == '/limpar':
                history.clear()
                continue
            try:
                if args.fixed_recording:
                    print(f'Ouvindo por {args.seconds} segundos...', flush=True)
                    record(folder / 'entrada.wav', args.seconds, args.input_device)
                else:
                    print('Ouvindo... fale agora; uma pausa encerra a gravação.', flush=True)
                    record_until_silence(folder / 'entrada.wav', args.input_device,
                                         args.max_record_seconds, args.silence_seconds,
                                         args.silence_threshold)
                print('Transcrevendo...', flush=True)
                text = transcriber.transcribe(folder / 'entrada.wav')
                print('Você:', text, flush=True)
                history = run_turn(text, history, model, folder / 'resposta.wav', args)
            except (LocalError, subprocess.SubprocessError) as exc:
                print('Falha:', exc)
            finally:
                for path in folder.glob('*.wav'):
                    path.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\nEncerrado.')
    except (LocalError, subprocess.SubprocessError) as exc:
        print('Falha:', exc, file=sys.stderr)
        sys.exit(1)
