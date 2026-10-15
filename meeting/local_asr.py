"""Fast CPU transcription of PCM WAV clips without uploading the audio."""

from __future__ import annotations

import os
from pathlib import Path
import re
import wave

import numpy as np


_REPEATED_SPEECH = re.compile(
    r'(?P<term>[\u3040-\u30ff\u3400-\u9fff]{1,10})'
    r'(?:[、，,\s]*(?P=term)){4,}'
)


def reduce_decoder_loops(text: str) -> str:
    """Mark obvious Whisper token loops as unintelligible, never invent speech."""
    return _REPEATED_SPEECH.sub(lambda found: found.group('term') + ' ....', text)


class LocalSpeechRecognizer:
    """Keep Whisper Small warm across consecutive meeting clips."""

    def __init__(self) -> None:
        from faster_whisper import WhisperModel

        self.engine = WhisperModel(
            os.getenv('PRO_MEETING_WHISPER_MODEL', 'small'),
            device='cpu', compute_type='int8',
            cpu_threads=int(os.getenv('PRO_MEETING_WHISPER_THREADS', '6')),
        )
        self.language = os.getenv('PRO_MEETING_SPEECH_LANGUAGE', 'ja')
        self.vocabulary = os.getenv(
            'PRO_MEETING_WHISPER_VOCABULARY',
            'トレーシング、トレーニング、シーメンス、ライブラリ、機材、装置、工程、実装',
        )

    def transcribe(self, audio_file: Path) -> str:
        with wave.open(str(audio_file), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                raise ValueError('Local ASR yêu cầu WAV mono PCM 16 kHz')
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2')
        if samples.size == 0:
            raise ValueError('Không có dữ liệu giọng nói')
        floating = samples.astype(np.float32) / 32768.0
        segments, _info = self.engine.transcribe(
            floating,
            language=None if self.language == 'auto' else self.language,
            beam_size=2,
            # Disable automatic nonzero-temperature retries. In the fifth
            # meeting clip, fallback retries increased CPU time from 13s to
            # 44s and made the transcript less coherent.
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=self.vocabulary,
            vad_filter=False,
            no_repeat_ngram_size=3,
        )
        text = '\n'.join(reduce_decoder_loops(segment.text.strip()) for segment in segments)
        return text.strip() or '....'
