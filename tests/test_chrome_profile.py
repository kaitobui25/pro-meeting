import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from meeting.browser_bridge import chrome_extension_profile, launch_installed_chrome


class ChromeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.user_data = Path(self.temp.name) / "Google" / "Chrome" / "User Data"
        self.user_data.mkdir(parents=True)
        env = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.override = patch.dict(os.environ, {"PRO_MEETING_CHROME_PROFILE": ""}, clear=False)
        self.override.start()
        self.addCleanup(self.override.stop)

    def install(self, name):
        profile = self.user_data / name
        profile.mkdir()
        extension = Path(__file__).resolve().parent.parent / "extension"
        preferences = {"extensions": {"settings": {"a" * 32: {"path": str(extension)}}}}
        (profile / "Secure Preferences").write_text(json.dumps(preferences), encoding="utf-8")

    def test_finds_profile_with_unpacked_extension(self):
        self.install("Profile 3")
        (self.user_data / "Default").mkdir()
        self.assertEqual(chrome_extension_profile(), "Profile 3")

    def test_uses_last_active_profile_if_extension_in_multiple(self):
        self.install("Default")
        self.install("Profile 3")
        (self.user_data / "Local State").write_text(
            json.dumps({"profile": {"last_used": "Profile 3"}}), encoding="utf-8"
        )
        self.assertEqual(chrome_extension_profile(), "Profile 3")

    def test_never_opens_profile_picker_when_extension_missing(self):
        with patch("meeting.browser_bridge.chrome_executable", return_value=Path("chrome.exe")):
            with patch("meeting.browser_bridge.subprocess.Popen") as popen:
                with self.assertRaisesRegex(RuntimeError, "Không tìm thấy Chrome profile"):
                    launch_installed_chrome()
                popen.assert_not_called()

    def test_chrome_launch_uses_installed_profile(self):
        self.install("Profile 3")
        with patch("meeting.browser_bridge.chrome_executable", return_value=Path("chrome.exe")):
            with patch("meeting.browser_bridge.subprocess.Popen") as popen:
                launch_installed_chrome()
                args = popen.call_args.args[0]
                self.assertIn("--profile-directory=Profile 3", args)

    def test_manual_profile_override(self):
        with patch.dict(os.environ, {"PRO_MEETING_CHROME_PROFILE": "Profile 2"}):
            self.assertEqual(chrome_extension_profile(), "Profile 2")


if __name__ == "__main__":
    unittest.main()
