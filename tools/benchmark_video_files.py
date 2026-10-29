"""Test actual C3CAST video-file commands offline; never opens an RF device."""
from pathlib import Path
import json
import argparse
import math
import sys
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'webapp'),str(ROOT/'host'),str(ROOT/'tools')]
import qo100_enc as enc
import stream_tx
import benchmark_vvc as bench

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--final',action='store_true',help='Test installed profiles and full-file loop boundaries')
args=parser.parse_args()
OUT=ROOT/('captures/video-release-check/final' if args.final else 'captures/video-release-check/results')
OUT.mkdir(parents=True,exist_ok=True)
results=[]

def trial(path,sr,fec,codec,encoder=None,size=None,fps=None,cap=None,loop=False):
    original_encoder=enc.video_encoder
    if encoder: enc.video_encoder=lambda:encoder
    try:
        s,command=stream_tx.build('video','',sr,fec,'C3CAST TEST','JN00aa',5,0,codec=codec,video=str(path))
        # Build candidate settings only in this experiment, without touching app defaults.
        if size:
            s['size']=size
            w,h=size.split('x')
            command[command.index('-vf')+1]=f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1'
        if fps:
            s['fps']=fps
            command[command.index('-r')+1]=str(fps)
        if cap and s['video_bps']>cap:
            s['video_bps']=cap
            s['bufsize']=round(cap/4+180000)
            command[command.index('-b:v')+1]=str(cap)
            command[command.index('-maxrate')+1]=str((3*cap+1)//2)
            command[command.index('-bufsize')+1]=str(s['bufsize'])
        if not loop or args.final:command.remove('-re')
        if loop:
            info=json.loads(subprocess.check_output([str(enc.FFMPEG.with_name('ffprobe.exe')),'-v','error','-show_entries','format=duration','-of','json',str(path)],text=True))
            seek=0 if args.final else max(0,float(info['format']['duration'])-3)
        else:seek=15
        command[command.index('-i'):command.index('-i')]=['-ss',str(seek)]
        label=path.stem+'_'+codec+'_'+s['encoder']+('_loop' if loop else '_candidate' if size else '_baseline')
        seconds=math.ceil(float(info['format']['duration']))+5 if loop and args.final else 12
        r=bench.run(path,OUT,sr,fec,fps=s['fps'],seconds=seconds,timeout=240,size=s['size'] if size else None,
                    codec=codec,settings_override=s,command_override=command,label=label)
        r.update(file=path.name,codec=codec,encoder=s['encoder'],loop_boundary=loop,input_seek_seconds=seek,
                 input_paced=loop and not args.final,video_cap_bps=cap)
        if loop and not args.final:r['first_output_seconds_paced']=r.pop('first_output_seconds_offline',None)
        r['preset']=command[command.index('-preset:v')+1] if '-preset:v' in command else command[command.index('-preset')+1]
        r['encoder_timing_warnings']=[line for line in (OUT/(r['profile']+'.log')).read_text(errors='replace').splitlines() if any(word in line.lower() for word in ('non-monoton','dts < pcr','buffer underflow'))][:20]
        results.append(r)
        (OUT/'results.json').write_text(json.dumps(results,indent=2))
    finally:enc.video_encoder=original_encoder

for path in (ROOT/'webapp/videos/Bunny.mp4',ROOT/'webapp/videos/sintel_trailer.mp4'):
    for sr in (125,333,1000):
        for encoder in ('hevc_nvenc','libx265'):
            trial(path,sr,'3/4','h265',encoder=encoder)
    for sr in (125,250,333,500,1000):
        for fec in ('3/4','4/5'):
            trial(path,sr,fec,'h266',size=None if args.final else '640x360',fps=None if args.final else 24,cap=None if args.final else 300000)
    for codec in ('h265','h266'):
        trial(path,125,'3/4',codec,encoder='hevc_nvenc' if codec=='h265' else None,
              size='640x360' if codec=='h266' and not args.final else None,fps=24 if codec=='h266' and not args.final else None,cap=300000 if codec=='h266' and not args.final else None,loop=True)
