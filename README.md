# LauraVoice — voz com IA local

Microfone → Whisper local → Ollama ou LM Studio → Piper → alto-falante.

Conversa por turnos no terminal Linux, sem chave de API nem cobrança por chamadas no fluxo local. Enter inicia a gravação; uma pausa de 1,2 segundo encerra a captura após detectar atividade. Não há interrupção da resposta por fala nem interface web.

## Instalação

Requisitos: Linux com ALSA, Python 3.10+, `alsa-utils` (`arecord` e `aplay`) e Ollama ou LM Studio. No Ubuntu/Debian, instale as ferramentas de áudio com `sudo apt install alsa-utils`. O instalador usa `uv` se disponível; caso contrário, usa `venv` e `pip` (pode ser necessário instalar `python3-venv`).

Abra um terminal na pasta do projeto, onde está este README:

```bash
bash instalar_local.sh
```

O instalador cria `.venv`, instala as dependências e baixa Whisper base e a voz Piper `pt_BR-cadu-medium`. A restrição `av<19` evita a incompatibilidade com o parâmetro `metadata_errors` do faster-whisper instalado. Internet é necessária para instalar e baixar modelos. Use um modelo de resposta já baixado e executado localmente para funcionar offline.

A voz Cadu é um ponto de partida, sem garantia de timbre feminino. Para outra voz, passe `--voice CAMINHO.onnx`; seu arquivo `.onnx.json` precisa estar junto. Verifique a licença de cada voz antes de redistribuí-la.

## Usar Ollama

Instale o Ollama separadamente. Se o serviço não estiver rodando, execute em outro terminal:

```bash
ollama serve
```

Veja os modelos instalados:

```bash
ollama list
```

Se necessário, baixe um modelo com `ollama pull NOME_DO_MODELO`. Substitua `NOME_DO_MODELO` nos comandos pelo identificador exato listado pelo Ollama. Modelos maiores exigem mais memória e podem demorar mais.

```bash
bash iniciar_local.sh --server http://127.0.0.1:11434/v1 --model NOME_DO_MODELO --check
bash iniciar_local.sh --server http://127.0.0.1:11434/v1 --model NOME_DO_MODELO --max-tokens 4096
```

Por exemplo, se você já tem o modelo personalizado `gemma4-tools:latest`, use esse nome. O projeto não distribui esse modelo nem implementa execução de ferramentas solicitadas por ele.

## Usar LM Studio

Instale o LM Studio separadamente, baixe e carregue um modelo e inicie seu servidor de desenvolvimento na porta 1234, apenas em localhost.

```bash
bash iniciar_local.sh --server http://127.0.0.1:1234/v1 --check
bash iniciar_local.sh --server http://127.0.0.1:1234/v1
```

Esse é o endereço padrão. Use `--model IDENTIFICADOR` para selecionar um modelo específico; sem essa opção, o programa escolhe o primeiro listado pelo servidor.

## Conversar e ajustar a gravação

Enter grava; `q` encerra; `/limpar` apaga o histórico. A personalidade compartilhada fica em `personality.py`.

- `--silence-seconds 2`: permite uma pausa de dois segundos antes de encerrar (intervalo: 0,2–5).
- `--silence-threshold 500`: volume RMS mínimo (1–32767). Reduza se sua fala não for detectada; aumente se ruído mantiver a gravação aberta.
- `--max-record-seconds 30`: limite da gravação automática (1–120 segundos).
- `--fixed-recording --seconds 6`: gravação fixa, sem detecção de silêncio (1–30 segundos).
- `--input-device NOME` e `--output-device NOME`: dispositivos ALSA; consulte `arecord -L` e `aplay -L`.
- `--max-tokens 4096`: limite de geração; padrão 1024. Limites maiores podem aumentar a demora.
- `--whisper-model base`: modelo de transcrição, obrigatoriamente já baixado.
- `--tts espeak`: alternativa mais robótica ao Piper; exige `espeak-ng` instalado.

A detecção usa volume e pode confundir ruídos com fala. Sem atividade detectada, encerra em cerca de cinco segundos. Feche outros programas que estejam ocupando o microfone.

## Validar o fluxo real com Ollama

Primeiro teste a resposta e a síntese sem microfone:

```bash
bash iniciar_local.sh --server http://127.0.0.1:11434/v1 --model NOME_DO_MODELO --max-tokens 4096 --text 'Oi, Laura! Se apresente em uma frase.'
```

Depois execute o modo interativo, pressione Enter e fale:

```bash
bash iniciar_local.sh --server http://127.0.0.1:11434/v1 --model NOME_DO_MODELO --max-tokens 4096
```

Verifique: a captura encerra após sua pausa, o texto após `Você:` corresponde à fala, aparece uma resposta após `Laura:` e ela é reproduzida no alto-falante. Faça uma segunda rodada para verificar o histórico. `--check` verifica ferramentas e consulta a lista de modelos; não valida o microfone, a transcrição ou a geração de respostas.

Para testar um áudio existente e salvar a resposta sem reproduzir:

```bash
bash iniciar_local.sh --server http://127.0.0.1:11434/v1 --model NOME_DO_MODELO --audio-file exemplo.wav --no-play --output resposta.wav
```

## Testes e estado da validação

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Os 16 testes automatizados passaram nesta revisão. Também foi gerado um áudio real com eSpeak, transcrito com Whisper base, e gerado um WAV válido com Piper. Esses testes parciais não usam o Ollama nem o microfone.

Os testes automatizados usam respostas e captura simuladas para verificar payloads, histórico, falhas, detecção de pausas e geração de WAV. Eles não substituem a conversa real. Nesta revisão, o ambiente do assistente não tem `/dev/snd` e a conexão com localhost:11434 falhou; portanto, o fluxo completo com microfone, Ollama e reprodução permanece pendente de validação no computador do usuário.

## Privacidade e versão com API

O histórico local fica em memória, com até seis pares de mensagens. WAV temporários são apagados ao fim de cada rodada; arquivos salvos com `--output` permanecem. Endereços externos são rejeitados pelo cliente local. A política de logs e o processamento efetivo dependem do servidor/modelo escolhido; não use modelos de nuvem do Ollama se quiser processamento inteiramente local.

`laura_voice_api.py` é uma alternativa separada com API paga. Ela envia áudio e texto à OpenAI e recebe a chave de `OPENAI_API_KEY` ou de uma entrada oculta. Não coloque chaves no código nem em arquivos versionados. A versão local compartilha apenas a personalidade e as funções ALSA, sem importar o módulo da API.

`.gitignore` exclui ambientes, modelos, gravações, caches e padrões comuns de credenciais. Isso não remove arquivos já rastreados pelo Git: confira os arquivos preparados para commit antes de publicar.

## Fontes

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Piper](https://github.com/OHF-Voice/piper1-gpl)
- [Ollama: compatibilidade OpenAI](https://docs.ollama.com/api/openai-compatibility)
- [LM Studio: chat completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)

# conversa_comigo
