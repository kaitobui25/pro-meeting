import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from queue import Queue

from meeting.capture import AudioChunk
from meeting.pipeline import MeetingPipeline


class PipelineTests(unittest.TestCase):
    def test_queue_overflow_deletes_only_unsent_audio(self):
        messages = []
        pipeline = MeetingPipeline(lambda kind, text: messages.append((kind, text)))
        pipeline.pending = Queue(maxsize=1)
        with tempfile.TemporaryDirectory() as folder:
            first_path = Path(folder) / "first.wav"
            second_path = Path(folder) / "second.wav"
            first_path.write_bytes(b"first")
            second_path.write_bytes(b"second")
            pipeline._queue_chunk(AudioChunk(1, first_path, datetime.now(), 20))
            pipeline._queue_chunk(AudioChunk(2, second_path, datetime.now(), 20))
            self.assertTrue(first_path.exists())
            self.assertFalse(second_path.exists())
            self.assertEqual(pipeline.pending.qsize(), 1)
            self.assertTrue(any(kind == "warning" and "hàng đợi đầy" in text for kind, text in messages))
            pipeline.close()
            self.assertFalse(first_path.exists())


if __name__ == "__main__":
    unittest.main()
