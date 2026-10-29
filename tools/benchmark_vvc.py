"""Offline VVC benchmark using one local camera recording. Never opens RF/USB serial.
Usage: python tools/benchmark_vvc.py --input captures/.../camera-original.mkv
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'webapp'), str(ROOT / 'host')]
import qo100_enc as enc


def ts_checks(path):
    previous, errors, packets = {}, 0, 0
    pcrs = {}
    with path.open('rb') as stream:
        while packet := stream.read(188):
            if len(packet) != 188 or packet[0] != 0x47:
                return {'sync_errors': 1, 'continuity_errors': errors}
            packets += 1
            pid = ((packet[1] & 31) << 8) | packet[2]
            afc, cc = (packet[3] >> 4) & 3, packet[3] & 15
            discontinuity = afc in (2, 3) and packet[4] > 0 and packet[5] & 128
            if afc in (2, 3) and packet[4] >= 7 and packet[5] & 16:
                base = (packet[6] << 25) | (packet[7] << 17) | (packet[8] << 9) | (packet[9] << 1) | (packet[10] >> 7)
                ticks = base * 300 + ((packet[10] & 1) << 8) + packet[11]
                pcrs.setdefault(pid, []).append((packets, ticks))
            if discontinuity:
                previous.pop(pid, None)
            if pid != 8191 and afc in (1, 3):
                if pid in previous and cc != (previous[pid] + 1) % 16:
                    errors += 1
                previous[pid] = cc
    result = {'sync_errors': 0, 'continuity_errors': errors, 'ts_packets': packets}
    if pcrs:
        samples = max(pcrs.values(), key=len)
        elapsed = (samples[-1][1] - samples[0][1]) % ((1 << 33) * 300) / 27000000
        if elapsed:
            result['pcr_mux_kbps'] = round((samples[-1][0] - samples[0][0]) * 188 * 8 / elapsed / 1000, 3)
            result['max_pcr_gap_ms'] = round(max((b[1] - a[1]) % ((1 << 33) * 300) / 27000 for a,b in zip(samples,samples[1:])), 3)
    return result


def run(source, out, sr, fec, preset='faster', fps=30, seconds=30, timeout=120, size=None, threads=None,
        audio_filter='lowpass=20000', inputs=None, video_filter=None, label=None,
        codec='h266', settings_override=None, command_override=None):
    settings = enc.settings(sr, fec, codec=codec)
    settings.update(settings_override or {})
    settings['fps'] = fps
    if size:
        settings['size'] = size
    tag = f'{sr}_{fec.replace("/", "-")}_{preset}_{fps}fps'
    if size:
        tag += '_' + size
    if threads:
        tag += f'_{threads}threads'
    if label:
        tag += '_' + label
    target = out / (tag + '.ts')
    command = command_override or enc.ffmpeg_command(settings, inputs or ['-i', str(source)], 'C3CAST TEST', 'C3CAST offline benchmark',
                                 video_filter=video_filter, audio_filter=audio_filter)
    if settings['encoder'] == 'libvvenc':
        command[command.index('-preset') + 1] = preset
    command[-1:-1] = ['-t', str(seconds)]
    if threads:
        command[-1:-1] = ['-threads:v', str(threads)]
    (out / (tag + '-command.json')).write_text(json.dumps(command, indent=2))
    start, first = time.perf_counter(), []
    result = {'profile': tag, 'sr_ks': sr, 'fec': fec, 'preset': preset, 'fps': fps,
              'size': settings['size'], 'video_target_kbps': settings['video_bps']/1000,
              'mux_target_kbps': settings['muxrate']/1000}
    with (out / (tag + '.log')).open('wb') as log, target.open('wb') as stream:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True) if os.name == 'nt' else None
        handle = None
        if kernel:
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            handle = kernel.OpenProcess(0x1000, False, proc.pid)
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)]*4
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        def drain():
            while block := proc.stdout.read(188*16):
                if not first: first.append(time.perf_counter()-start)
                stream.write(block)
        reader = threading.Thread(target=drain)
        reader.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            result['timeout'] = True
        reader.join()
        result['wall_seconds'] = round(time.perf_counter()-start, 3)
        result['exit_code'] = proc.returncode
        result['first_output_seconds_offline'] = round(first[0], 3) if first else None
        if handle:
            values = [wintypes.FILETIME() for _ in range(4)]
            if kernel.GetProcessTimes(handle, *(ctypes.byref(x) for x in values)):
                cpu = sum((x.dwHighDateTime << 32) + x.dwLowDateTime for x in values[2:])/1e7
                result['cpu_seconds'] = round(cpu, 3)
                result['average_cpu_percent_machine'] = round(cpu/result['wall_seconds']/os.cpu_count()*100, 1)
            kernel.CloseHandle(handle)
    proc.stdout.close()
    result.update(ts_checks(target))
    if proc.returncode == 0:
        probe = subprocess.run([str(enc.FFMPEG.with_name('ffprobe.exe')), '-v', 'error', '-show_streams', '-show_format',
                                '-show_packets', '-of', 'json', str(target)], capture_output=True, text=True, timeout=30)
        data = json.loads(probe.stdout)
        duration = float(data['format']['duration'])
        result['duration_seconds'] = round(duration, 3)
        result['speed_x'] = round(seconds/result['wall_seconds'], 3)
        result['ts_kbps'] = round(target.stat().st_size*8/duration/1000, 2)
        video = [p for p in data['packets'] if p['codec_type'] == 'video']
        result['video_actual_kbps'] = round(sum(int(p['size']) for p in video)*8/duration/1000, 2)
        buckets = {}
        for packet in video:
            stamp = int(float(packet.get('dts_time', packet.get('pts_time', 0))))
            buckets[stamp] = buckets.get(stamp, 0) + int(packet['size'])*8/1000
        result['video_peak_1s_kbits'] = round(max(buckets.values(), default=0), 2)
        decode = subprocess.run([str(enc.FFMPEG), '-v', 'error', '-i', str(target), '-f', 'null', '-'],
                                capture_output=True, timeout=120)
        result['decode_exit'] = decode.returncode
        result['decode_errors'] = decode.stderr.decode(errors='replace')[-2000:]
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'captures/vvc-camera-benchmark/results')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    enc.require_vvc()
    results = []
    cases = [(sr, fec, 'faster', 30) for sr in (125, 250, 333, 500, 1000) for fec in ('3/4','4/5')]
    for sr, fec, preset, fps in cases:
        results.append(run(args.input.resolve(), args.output, sr, fec, preset, fps))
        (args.output/'results.json').write_text(json.dumps(results, indent=2))
    # A slower preset is not a live candidate at larger sizes if it already
    # misses real time at the smallest size. Preserve time for useful trials.
    for sr in (125, 250, 500):
        result = run(args.input.resolve(), args.output, sr, '3/4', preset='fast')
        results.append(result)
        (args.output/'results.json').write_text(json.dumps(results, indent=2))
        if result.get('speed_x', 0) < 1.3:
            break
    for sr in (125,250,333,500,1000):
        baseline = next(r for r in results if r['sr_ks']==sr and r['fec']=='3/4' and r['preset']=='faster')
        if baseline.get('speed_x',0) < 1.3:
            results.append(run(args.input.resolve(), args.output, sr, '3/4', 'faster', 15))
            (args.output/'results.json').write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
