import base64
import json
from threading import Thread
import unittest
from urllib.request import Request, urlopen

from meeting.browser_bridge import ChromeBridge
from meeting.config import CHUNKS_DIR


class BrowserBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = ChromeBridge(port=0)
        self.bridge.start()
        self.base = f"http://127.0.0.1:{self.bridge.server.server_address[1]}"
        self.headers = {"X-Pro-Meeting-Extension-Id": "a" * 32}
        CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.bridge.close()

    def request(self, route, data=None, headers=None):
        payload = None if data is None else json.dumps(data).encode()
        with urlopen(Request(self.base + route, data=payload,
                             headers=headers if headers is not None else self.headers), timeout=20) as response:
            return json.loads(response.read())

    def test_rejects_unidentified_extension(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as rejected:
            self.request("/poll", headers={"X-Pro-Meeting-Extension-Id": "invalid"})
        self.assertEqual(rejected.exception.code, 403)
        rejected.exception.close()

    def test_prepare_audio_chunks_reply_and_no_implicit_retries(self):
        import uuid
        audio = CHUNKS_DIR / f"test-{uuid.uuid4().hex}.wav"
        audio.write_bytes(b"RIFF" + b"audio-sample" * 100)
        try:
            def simulate_extension():
                prepared = self.request("/poll")["command"]
                self.assertEqual(prepared["type"], "prepare")
                self.request("/result", {"id": prepared["id"], "ok": True, "text": "ready"})
                command = self.request("/poll")["command"]
                self.assertEqual(command["type"], "transcribe")
                self.assertEqual(command["filename"], audio.name)
                offset = 0
                received = bytearray()
                while True:
                    part = self.request(f"/file?id={command['id']}&offset={offset}")
                    received.extend(base64.b64decode(part["base64"]))
                    offset = part["nextOffset"]
                    if part["done"]:
                        break
                self.assertEqual(bytes(received), audio.read_bytes())
                self.request("/result", {"id": command["id"], "ok": True, "text": "BẢN DỊCH TIẾNG VIỆT: Chào mọi người"})

            extension = Thread(target=simulate_extension)
            extension.start()
            self.assertTrue(self.bridge.wait_connected(lambda: False))
            self.bridge.prepare_chat()
            text = self.bridge.send_audio(audio, "Translate this clip", timeout=10)
            self.assertIn("Chào mọi người", text)
            extension.join(timeout=5)
            self.assertFalse(extension.is_alive())
            self.assertIsNone(self.bridge.current)
        finally:
            audio.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
