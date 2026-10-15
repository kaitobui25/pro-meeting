"""Measure faster-whisper on a user-supplied clip; no upload or files persisted."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import tempfile
import time
import wave

from faster_whisper import WhisperModel
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('audio', type=Path)
    parser.add_argument('--seconds', type=int, default=10)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--model', default='base')
    parser.add_argument('--beam', type=int, default=1)
    parser.add_argument('--temperature', type=float, default=0.0)
    parser.add_argument('--vocab', action='store_true')
    parser.add_argument('--vad', action='store_true')
    parser.add_argument('--no-repeat-ngram', type=int, default=0)
    args = parser.parse_args()

    started = time.perf_counter()
    engine = WhisperModel(args.model, device='cpu', compute_type='int8',
                          cpu_threads=args.threads)
    print(f'LOAD_SECONDS={time.perf_counter() - started:.2f}', flush=True)
    with tempfile.TemporaryDirectory() as temp:
        wav = Path(temp) / 'sample.wav'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-i', str(args.audio), '-t', str(args.seconds),
                        '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)], check=True)
        started = time.perf_counter()
        with wave.open(str(wav), 'rb') as stream:
            samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype=np.int16)
            audio = samples.astype(np.float32) / 32768.0
        segments, info = engine.transcribe(
            audio, language='ja', beam_size=args.beam,
            condition_on_previous_text=False, temperature=args.temperature,
            initial_prompt='トレーシング、トレーニング、シーメンス、ライブラリ、機材、装置、工程、実装'
            if args.vocab else None,
            no_repeat_ngram_size=args.no_repeat_ngram,
            vad_filter=args.vad)
        text = ' '.join(s.text.strip() for s in segments).strip()
        print(f'ASR_SECONDS={time.perf_counter() - started:.2f}', flush=True)
        print(f'LANGUAGE={info.language} WORDS={len(text)} TEXT={text}', flush=True)


if __name__ == '__main__':
    main()
