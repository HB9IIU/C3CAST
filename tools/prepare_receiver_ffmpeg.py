"""Install the pinned GPL receive-only FFmpeg, checking its archive before extracting.

The transmit FFmpeg in tools/ffmpeg is never changed. Standard library only.
"""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip'
SHA256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'


def main():
    cache = ROOT / 'output' / 'ffmpeg-essentials.zip'
    cache.parent.mkdir(exist_ok=True)
    if not cache.is_file():
        print('Downloading the pinned receive FFmpeg...', flush=True)
        urllib.request.urlretrieve(URL, cache)
    if hashlib.sha256(cache.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('Receiver FFmpeg archive checksum mismatch; no files installed')
    receiver = ROOT / 'webapp' / 'receiver'
    prefix = 'ffmpeg-9.0.2-essentials_build/'
    with zipfile.ZipFile(cache) as archive:
        for source, target in [('bin/ffmpeg.exe', 'bin/ffmpeg.exe'), ('LICENSE', 'licenses/FFmpeg-GPL.txt'),
                               ('README.txt', 'licenses/FFmpeg-build.txt')]:
            destination = receiver / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(prefix + source))
    print('Receiver FFmpeg 9.0.2 installed. Transmit FFmpeg unchanged.')


if __name__ == '__main__':
    main()
