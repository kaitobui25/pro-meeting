import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from meeting.capture import MeetingCapture, save_wav


class SaveWavTests(unittest.TestCase):
    def test_downsamples_wav_for_long_room_meetings(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "compact.wav"
            save_wav(np.ones(48_000, dtype=np.float32) * 0.1,
                     dest, sample_rate=48_000, output_rate=16_000)
            with wave.open(str(dest), "rb") as clip:
                self.assertEqual(clip.getframerate(), 16_000)
                self.assertEqual(clip.getnframes(), 16_000)
                self.assertLess(dest.stat().st_size, 35_000)
    def test_writes_valid_mono_pcm_from_stereo(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "clip.wav"
            stereo = np.array([[0.5, -0.5], [1.0, 1.0], [-1.0, -1.0]], dtype=np.float32)
            save_wav(stereo, destination, sample_rate=16_000)
            with wave.open(str(destination), "rb") as audio:
                self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 16_000))
                self.assertEqual(audio.getnframes(), 3)
                samples = np.frombuffer(audio.readframes(3), dtype="<i2")
                self.assertEqual(samples.tolist(), [0, 32767, -32767])

    def test_rejects_empty_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                save_wav(np.array([], dtype=np.float32), Path(folder) / "invalid.wav")

    def test_room_microphone_is_default_and_never_drops_quiet_speech(self):
        stop = threading.Event()
        received = []
        messages = []

        class FakeRecorder:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def record(self, numframes):
                return np.full((numframes, 2), 0.00008, dtype=np.float32)

        device = SimpleNamespace(name="Room microphone", recorder=lambda **_kwargs: FakeRecorder())
        audio_api = SimpleNamespace(
            default_microphone=lambda: device,
            default_speaker=lambda: self.fail("Should not use speakers in microphone mode"),
        )

        with tempfile.TemporaryDirectory() as folder:
            def on_chunk(chunk):
                received.append(chunk)
                stop.set()

            capture = MeetingCapture(Path(folder), stop, on_chunk, messages.append,
                                     lambda error: self.fail(error), source="microphone")
            with patch.dict("sys.modules", {"soundcard": audio_api}), patch("meeting.capture.CHUNK_SECONDS", 1):
                capture.run()
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0].path.is_file())
            self.assertTrue(any("micro" in message.lower() for message in messages))
            with wave.open(str(received[0].path), "rb") as wav:
                self.assertEqual(wav.getframerate(), 16_000)
                self.assertEqual(wav.getnframes(), 16_000)

    def test_room_microphone_switches_to_longer_segments_after_first_clip(self):
        stop = threading.Event()
        chunks = []

        class FakeRecorder:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def record(self, numframes):
                return np.full((numframes, 1), 0.015, dtype=np.float32)

        device = SimpleNamespace(name="Room mic", recorder=lambda **_args: FakeRecorder())
        with tempfile.TemporaryDirectory() as folder:
            def on_chunk(chunk):
                chunks.append(chunk)
                if len(chunks) == 2:
                    stop.set()

            audio_api = SimpleNamespace(default_microphone=lambda: device)
            capture = MeetingCapture(Path(folder), stop, on_chunk, lambda _msg: None,
                                     lambda error: self.fail(error), source="microphone")
            with patch.dict("sys.modules", {"soundcard": audio_api}), \
                 patch("meeting.capture.CHUNK_SECONDS", 1), \
                 patch("meeting.capture.MICROPHONE_LONG_CHUNK_SECONDS", 3):
                capture.run()
            self.assertEqual([chunk.duration_seconds for chunk in chunks], [1.0, 3.0])
            with wave.open(str(chunks[1].path), "rb") as wav:
                self.assertEqual(wav.getframerate(), 16_000)
                self.assertEqual(wav.getnframes(), 48_000)


if __name__ == "__main__":
    unittest.main()
