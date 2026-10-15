"""Capture nearby microphone speech or Windows speaker loopback as PCM WAV clips."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
import warnings
import wave
from typing import Callable

import numpy as np

from .config import (AUDIO_SOURCE, CHUNK_SECONDS, MICROPHONE_LONG_CHUNK_SECONDS,
                     MIN_LAST_CHUNK_SECONDS, SAMPLE_RATE, SILENCE_RMS, UPLOAD_SAMPLE_RATE)


@dataclass(frozen=True)
class AudioChunk:
    index: int
    path: Path
    started_at: datetime
    duration_seconds: float


def save_wav(samples: np.ndarray, destination: Path, sample_rate: int = SAMPLE_RATE,
             output_rate: int | None = None) -> None:
    """Write 32-bit float mono/stereo samples as 16-bit PCM mono WAV."""
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if samples.ndim != 1 or not len(samples):
        raise ValueError("Audio recording is empty or has invalid dimensions")
    if output_rate is not None:
        if output_rate > sample_rate or sample_rate % output_rate:
            raise ValueError("Output sample rate must divide the capture rate")
        factor = sample_rate // output_rate
        if factor > 1:
            usable = len(samples) // factor * factor
            samples = samples[:usable].reshape(-1, factor).mean(axis=1)
        sample_rate = output_rate
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


class MeetingCapture:
    def __init__(
        self,
        output_dir: Path,
        stop: threading.Event,
        on_chunk: Callable[[AudioChunk], None],
        on_status: Callable[[str], None],
        on_error: Callable[[str], None],
        source: str = AUDIO_SOURCE,
    ) -> None:
        self.output_dir = output_dir
        self.stop = stop
        self.on_chunk = on_chunk
        self.on_status = on_status
        self.on_error = on_error
        if source not in ("microphone", "speakers"):
            raise ValueError(f"Unsupported audio source: {source}")
        self.source = source

    def run(self) -> None:
        try:
            import soundcard as sc

            if self.source == "microphone":
                device = sc.default_microphone()
                if device is None:
                    raise RuntimeError("Không tìm thấy micro thu âm mặc định trên Windows")
                self.on_status(f"Đang thu micro trong phòng: {device.name}")
            else:
                speaker = sc.default_speaker()
                if speaker is None:
                    raise RuntimeError("Không tìm thấy thiết bị phát âm thanh mặc định trên Windows")
                device = sc.get_microphone(id=speaker.name, include_loopback=True)
                if device is None:
                    raise RuntimeError("Thiết bị phát âm thanh không hỗ trợ WASAPI loopback")
                self.on_status(f"Đang thu âm từ loa: {speaker.name}")
            buffered: list[np.ndarray] = []
            total_frames = 0
            chunk_index = 0
            chunk_start = datetime.now()
            discontinuities = 0

            def flush(min_seconds: float) -> None:
                nonlocal buffered, total_frames, chunk_index, chunk_start, discontinuities
                if total_frames < int(min_seconds * SAMPLE_RATE):
                    return
                samples = np.concatenate(buffered)
                buffered = []
                total_frames = 0
                started = chunk_start
                chunk_start = datetime.now()
                if discontinuities:
                    self.on_status(f"Cảnh báo gián đoạn dữ liệu thu micro: {discontinuities} tín hiệu từ driver")
                    discontinuities = 0
                duration = len(samples) / SAMPLE_RATE
                rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
                if self.source == "speakers" and rms < SILENCE_RMS:
                    self.on_status("Bỏ qua đoạn yên lặng từ loa")
                    return
                # Physical microphones can have very low gain. Do not throw away
                # captured room speech based on the speaker loopback threshold.
                # Normalize quiet clips, but cap the boost to avoid amplifying noise.
                if self.source == "microphone":
                    peak = float(np.max(np.abs(samples)))
                    if peak < 0.00001:
                        self.on_status("Micro gần như không có tín hiệu; kiểm tra mic mute/quyền truy cập")
                    elif rms < 0.001:
                        self.on_status(f"Tín hiệu micro nhỏ (RMS {rms:.6f}), đang tăng âm lượng")
                    if peak > 0.0:
                        gain = min(32.0, 0.65 / peak)
                        if gain > 1:
                            samples = samples * gain
                chunk_index += 1
                destination = self.output_dir / f"segment-{chunk_index:05d}.wav"
                save_wav(samples, destination, output_rate=UPLOAD_SAMPLE_RATE)
                self.on_chunk(AudioChunk(chunk_index, destination, started, duration))

            # Record in one-second blocks so Stop is responsive.
            with device.recorder(samplerate=SAMPLE_RATE) as recorder:
                while not self.stop.is_set():
                    with warnings.catch_warnings(record=True) as audio_warnings:
                        warnings.simplefilter("always")
                        block = np.asarray(recorder.record(numframes=SAMPLE_RATE), dtype=np.float32)
                    discontinuities += sum(
                        "data discontinuity in recording" in str(notice.message)
                        for notice in audio_warnings
                    )
                    if block.size == 0:
                        continue
                    buffered.append(block)
                    total_frames += len(block)
                    # First room clip is short for early feedback. Later clips
                    # are larger to match Chrome Web's much slower throughput.
                    chunk_seconds = (MICROPHONE_LONG_CHUNK_SECONDS
                                     if self.source == "microphone" and chunk_index > 0
                                     else CHUNK_SECONDS)
                    if total_frames >= chunk_seconds * SAMPLE_RATE:
                        flush(chunk_seconds)
            flush(MIN_LAST_CHUNK_SECONDS)
        except Exception as error:
            self.on_error(f"Không thu được âm thanh từ {self.source}: {error}")
            self.stop.set()
