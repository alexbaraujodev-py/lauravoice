"""Gravação e reprodução ALSA compartilhadas."""
import subprocess


def record(path, seconds, device):
    subprocess.run(['arecord', '-q', '-D', device, '-t', 'wav', '-f', 'S16_LE',
                    '-r', '16000', '-c', '1', '-d', str(seconds), str(path)],
                   check=True)


def play(path, device):
    subprocess.run(['aplay', '-q', '-D', device, str(path)], check=True)

