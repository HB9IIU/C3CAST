import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'webapp'), str(ROOT / 'host')]
import app as web
import qo100_enc as enc
import stream_tx


class VideoSource(unittest.TestCase):
    def test_listing_empty_filtering_and_range_requests(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, 'VIDEOS', Path(tmp)):
            client = web.app.test_client()
            self.assertEqual(client.get('/api/videos').json, [])
            (Path(tmp)/'sample & clip.MP4').write_bytes(b'0123456789')
            (Path(tmp)/'notes.txt').write_text('not a video')
            (Path(tmp)/'folder.mp4').mkdir()
            self.assertEqual(client.get('/api/videos').json, ['sample & clip.MP4'])
            response = client.get('/videos/sample%20%26%20clip.MP4', headers={'Range':'bytes=2-4'})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.data, b'234')
            response.close()
            self.assertEqual(client.get('/videos/notes.txt').status_code, 404)
            self.assertEqual(client.get('/videos/../app.py').status_code, 404)

    def test_looping_command_audio_mapping_and_preserved_transport(self):
        for codec in ('h265','h266'):
            for audio in (False,True):
                with patch.object(stream_tx, 'video_has_audio', return_value=audio), \
                     patch.object(enc, 'video_encoder', return_value='libx265'):
                    settings, command = stream_tx.build('video','',125,'3/4','TEST','JN00aa',5,0,
                                                         codec=codec,video='clip with spaces.mp4')
                    self.assertEqual(command[command.index('-stream_loop')+1], '-1')
                    self.assertIn('-re',command)
                    self.assertIn('clip with spaces.mp4',command)
                    self.assertIn('0:a:0' if audio else '1:a:0',command)
                    self.assertEqual('anullsrc=r=48000:cl=mono' in command, not audio)
                    self.assertIn('aac',command)
                    self.assertIn(f"fps={settings['fps']},setpts=N/({settings['fps']}*TB)",command[command.index('-vf')+1])
                    self.assertIn('-fps_mode',command)
                    base=enc.ffmpeg_command(settings,[], 'TEST','C3CAST @ JN00aa',
                                            audio_filter='asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0,lowpass=20000')
                    self.assertEqual(command[command.index('-c:a'):],base[base.index('-c:a'):])

    def test_vvc_movie_profile_and_readout_match_without_changing_h265(self):
        with patch.object(enc,'video_encoder',return_value='libx265'):
            for sr in (125,250,333,500,1000):
                for fec in ('3/4','4/5'):
                    movie=enc.source_settings('video',sr,fec,'h266')
                    self.assertEqual((movie['size'],movie['fps']),('640x360',24))
                    self.assertLessEqual(movie['video_bps'],300000)
                    plan=enc.plan(sr,fec,'video','h266')
                    self.assertEqual((plan['size'],plan['fps']),('640x360',24))
                    self.assertEqual(enc.source_settings('video',sr,fec,'h265'),enc.settings(sr,fec))
                    for key in ('capacity','muxrate','audio_k','channels','pat_s','pcr_ms'):
                        self.assertEqual(movie[key],enc.settings(sr,fec)[key])

    def test_probe_rejects_non_video_and_reports_audio(self):
        # ffmpeg itself lists the streams on stderr (the packaged app has no ffprobe)
        video = "  Stream #0:0[0x1](und): Video: h264 (High), yuv420p, 1280x720, 25 fps"
        audio = "  Stream #0:1[0x2](und): Audio: aac (LC), 48000 Hz, stereo, fltp"
        cover = "  Stream #0:1: Video: mjpeg, yuvj420p, 600x600 (attached pic)"
        for lines, expected in (([video, audio],True),([video],False),([audio],None),([cover, audio],None)):
            result = subprocess.CompletedProcess([],0,'',"\n".join(["Input #0, mov,mp4", *lines, ""]))
            with patch.object(stream_tx.subprocess,'run',return_value=result):
                if expected is None:
                    with self.assertRaises(ValueError):stream_tx.video_has_audio('clip.mp4')
                else:
                    self.assertIs(stream_tx.video_has_audio('clip.mp4'),expected)
        failed = subprocess.CompletedProcess([],1,'',"clip.mp4: Invalid data found when processing input")
        with patch.object(stream_tx.subprocess,'run',return_value=failed):
            with self.assertRaises(ValueError):stream_tx.video_has_audio('clip.mp4')

    def test_empty_video_is_rejected_before_worker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web,'VIDEOS',Path(tmp)), \
             patch.object(web,'setup_ready',return_value=True), patch.object(web.subprocess,'Popen') as worker:
            response=web.app.test_client().post('/api/start',json={'source':'video','video':'missing.mp4',
                                                                 'sr':125000,'fec':'3/4','level':10})
            self.assertEqual(response.status_code,400)
            self.assertIn('unknown video',response.json['error'])
            worker.assert_not_called()

    def test_plan_and_second_row(self):
        with patch.object(enc,'video_encoder',return_value='libx265'):
            client=web.app.test_client()
            self.assertEqual(client.get('/api/plan?sr=125000&fec=3/4&source=video').status_code,200)
            page=client.get('/').data
            self.assertIn(b'id="srcVideo" value="video"',page)
            self.assertNotIn(b'Coming soon',page)


if __name__ == '__main__':
    unittest.main()
