#!/usr/bin/env bash
# Installs the two local Russian TTS engines (CPU only) into separate venvs + downloads the models.
#   silero : torch CPU (v5_ru, 145 MB, RTF ~0.03, more natural, puts stress marks) -> default voices aidar xenia baya kseniya eugene
#   piper  : onnxruntime, no torch (64 MB models, RTF ~0.02)                      -> fallback voices irina denis dmitri ruslan
set -euo pipefail
M=${ASSEMBLEE_TTS_MODELS:-$HOME/.cache/assemblee-tts-models}
mkdir -p "$M"; cd "$M"
python3 -m venv ~/.cache/assemblee-tts && ~/.cache/assemblee-tts/bin/pip install -q piper-tts numpy
python3 -m venv ~/.cache/assemblee-silero && ~/.cache/assemblee-silero/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cpu \
  && ~/.cache/assemblee-silero/bin/pip install -q numpy scipy
for v in irina denis dmitri ruslan; do for e in onnx onnx.json; do
  [ -s ru_RU-$v-medium.$e ] || curl -sL -o ru_RU-$v-medium.$e https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/$v/medium/ru_RU-$v-medium.$e
done; done
[ -s silero_v5_ru.pt ] || curl -sL -o silero_v5_ru.pt https://models.silero.ai/models/tts/ru/v5_ru.pt
echo ok
