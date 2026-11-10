"""F1JMJ: OBS Virtual Camera + a VB-Audio cable gave no picture. A camera and a microphone from DIFFERENT devices need one shared clock;
a camera with its own microphone must stay exactly as it was (its tuned lip-sync must not move)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "webapp"), str(ROOT / "host")]
import app as web
import camera
import clap_test
import qo100_enc as enc
import stream_tx

OPTION = ["-use_wallclock_as_timestamps", "1"]


def has_option(command):
    return any(command[i:i + 2] == OPTION for i in range(len(command) - 1))


class SharedClock(unittest.TestCase):
    def setUp(self):                                           # never read the developer's own config.json
        for name, value in (("load_config", {}), ("write_config", None)):      # never read or write the developer's own config.json
            patcher = patch.object(web, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_which_sound_counts_as_separate(self):
        self.assertTrue(camera.uses_separate_audio("Microphone (HD Pro Webcam C920)", "CABLE Output (VB-Audio Virtual Cable)"))
        self.assertTrue(camera.uses_separate_audio(None, "CABLE Output (VB-Audio Virtual Cable)"))   # OBS Virtual Camera has no own microphone
        self.assertFalse(camera.uses_separate_audio("Microphone (HD Pro Webcam C920)", "Microphone (HD Pro Webcam C920)"))
        self.assertFalse(camera.uses_separate_audio("Microphone (HD Pro Webcam C920)", ""))             # silence: no second device at all
        self.assertFalse(camera.uses_separate_audio(None, ""))

    def test_the_shared_clock_is_an_input_option_and_only_for_separate_audio(self):
        with patch.object(camera, "capture_options", return_value=["-vcodec", "mjpeg"]):
            separate, _, _ = camera.inputs_and_filter("OBS Virtual Camera", "CABLE Output", "1600x900", 30, "HB9IIU", 0, True)
            own, _, _ = camera.inputs_and_filter("HD Pro Webcam C920", "Microphone (C920)", "1600x900", 30, "HB9IIU", 0, False)
            silent, _, _ = camera.inputs_and_filter("OBS Virtual Camera", "", "1600x900", 30, "HB9IIU", 0, True)
        self.assertTrue(has_option(separate))
        self.assertLess(separate.index("-use_wallclock_as_timestamps"), separate.index("-i"))       # an input option: before the device
        self.assertEqual(separate[separate.index("-i") + 1], "video=OBS Virtual Camera:audio=CABLE Output")
        self.assertFalse(has_option(own))                       # a camera with its own microphone is untouched
        self.assertFalse(has_option(silent))                    # no microphone: nothing to align

    def test_the_transmit_command_carries_it(self):
        with patch.object(camera, "capture_options", return_value=[]), patch.object(enc, "video_encoder", return_value="libx265"):
            _, separate = stream_tx.build("camera", "", 500, "3/4", "HB9IIU", "JN36kl", 5, 0, "OBS Virtual Camera", "CABLE Output", 0, "h265", "", True)
            _, own = stream_tx.build("camera", "", 500, "3/4", "HB9IIU", "JN36kl", 5, 0, "C920", "Microphone (C920)", 0, "h265", "", False)
        self.assertTrue(has_option(separate))
        self.assertFalse(has_option(own))

    def test_the_clap_test_records_the_transmit_command_to_a_file(self):
        with patch.object(camera, "capture_options", return_value=[]), patch.object(enc, "video_encoder", return_value="libx265"):
            _, transmit = stream_tx.build("camera", "", 500, "3/4", "HB9IIU", "JN36kl", 5, 0, "OBS Virtual Camera", "CABLE Output", 0, "h265", "", True)
        command = clap_test._command(transmit, "tmp")
        self.assertTrue(has_option(command))                              # the shared clock comes with it
        self.assertEqual(command[:len(transmit) - 1], transmit[:-1])      # the very same inputs, filters and encoder
        self.assertNotIn("-", command[len(transmit) - 1:])                # nothing goes to the transmitter
        self.assertEqual(command.count("-t"), 3)                          # the file, the picture and the level stop together
        self.assertTrue(any(str(x).endswith("claps.ts") for x in command))
        self.assertIn("pipe:1", command)

    def test_detect_records_what_start_would_transmit(self):
        cam = {"name": "Cam", "mic": "Microphone (Cam)", "usb": True}
        started = []
        with patch.object(camera, "cameras", return_value=[cam]), patch.object(camera, "capture_options", return_value=[]), \
             patch.object(enc, "video_encoder", return_value="libx265"), patch.object(camera, "stop_previews"), patch.object(web.time, "sleep"), \
             patch.object(clap_test, "start", side_effect=lambda command, mic: started.append(command) or True):
            reply = web.app.test_client().post("/api/audio/detect", json={"camera": "Cam", "audio": "auto", "sr": 500000, "fec": "3/4", "codec": "h265"})
        self.assertEqual(reply.status_code, 200, reply.get_json())
        self.assertIn("video=Cam:audio=Microphone (Cam)", started[0])
        self.assertFalse(has_option(started[0]))                          # its own microphone: device timestamps, as on air

    def test_start_passes_the_flag_only_for_another_device(self):
        cam = {"name": "Cam", "mic": "Microphone (Cam)", "usb": True}
        obs = {"name": "OBS Virtual Camera", "mic": None, "usb": False}
        cases = [(cam, "auto", False),                          # its own microphone
                 (cam, "Headset (Other)", True),                # another microphone
                 (cam, "none", False),                          # silence
                 (obs, "CABLE Output", True),                   # a camera without microphone and a cable: F1JMJ's case
                 (obs, "auto", False)]                          # no microphone found: silence
        for chosen, audio, expected in cases:
            popen = MagicMock()
            popen.return_value.stdout = iter(())
            with patch.object(camera, "cameras", return_value=[cam, obs]), \
                 patch.object(camera, "audio_devices", return_value=["Microphone (Cam)", "Headset (Other)", "CABLE Output"]), \
                 patch.object(camera, "stop_previews"), patch.object(web.time, "sleep"), \
                 patch.object(web, "setup_ready", return_value=True), patch.dict(web.conn, {"connected": True, "port": "COM_TEST"}), \
                 patch.object(web.subprocess, "Popen", popen):
                reply = web.app.test_client().post("/api/start", json={"source": "camera", "camera": chosen["name"], "audio": audio, "delay": 0,
                                                                       "sr": 500000, "fec": "3/4", "level": 50, "freq": "2405.250"})
                self.assertEqual(reply.status_code, 200, (audio, reply.get_json()))
                self.assertEqual("--separate-audio" in popen.call_args.args[0], expected, (chosen["name"], audio))
            web.tx.update(state="idle", proc=None)


if __name__ == "__main__":
    unittest.main()
