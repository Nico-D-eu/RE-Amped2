"""The movie pack: higher-resolution copies of the game's movies.

    python tools/mods/movie_pack.py [Name ...] [--upscale ai|lanczos]
                                    [--height 1080] [--deinterlace] [--force]

Game data is never committed, so the movie pack is a recipe. It reads the
player's own game/Movies/<Name>.xmv and writes mods/movie_pack/<Name>.mp4,
which the runtime (src/movie_pack.c) draws in place of the movie's
640x480 picture. The game's own decoder keeps running underneath for the
timing, the sound and Start to skip, so only the picture is needed: the
copies have no audio track. With no names, every movie is converted.

Steps per movie:
  1. FFmpeg decodes the XMV (WMV2 video) to PNG frames and lists each
     frame's time. XMV frames are not evenly spaced (Intro.xmv: 1801
     frames in 60.86 s), and the runtime matches frames by time, so the
     copy keeps the original times.
  2. --upscale ai (the default): Real-ESRGAN (realesrgan-ncnn-vulkan, on
     the GPU through Vulkan) upscales 3x with its fast video model
     realesr-animevideov3, about 9 frames/s on an RTX 2070: 3 minutes for
     the intro, about 2 hours for all movies. --model realesrgan-x4plus
     keeps more texture but takes about 2 s a frame.
     --upscale lanczos: a plain resize, minutes for everything.
  3. FFmpeg scales to --height (4:3, so 1440x1080 by default) and encodes
     H.264 with OpenH264, which Windows' own Media Foundation plays.

--deinterlace runs bwdif first. The career movies show interlacing combs,
which the AI model otherwise sharpens.

Tools: tools/bin/ffmpeg/bin/ffmpeg.exe (an LGPL build, BtbN's
FFmpeg-Builds) and tools/bin/realesrgan/ (xinntao/Real-ESRGAN's
ncnn-vulkan release), or the same programs on PATH. Work files go to
mods/cache/movie_pack/ and are removed after each movie.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MOVIES = os.path.join(ROOT, 'game', 'Movies')
OUT = os.path.join(ROOT, 'mods', 'movie_pack')
WORK = os.path.join(ROOT, 'mods', 'cache', 'movie_pack')
EXE = '.exe' if os.name == 'nt' else ''


def tool(name, *bundled):
    """A bundled tool under tools/bin, else the one on PATH."""
    p = os.path.join(ROOT, 'tools', 'bin', *bundled, name + EXE)
    if os.path.isfile(p):
        return p
    found = shutil.which(name)
    if not found:
        sys.exit(f'{name} not found: put it in {os.path.dirname(p)} or on PATH')
    return found


def frame_times(ffprobe, src):
    """Each video frame's time in seconds, in order."""
    out = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0',
                          '-show_entries', 'frame=pts_time', '-of', 'csv=p=0', src],
                         capture_output=True, text=True, check=True).stdout
    return [float(line.split(',')[0]) for line in out.split() if line.strip()]


def convert(name, args, ffmpeg, ffprobe, esrgan):
    src = os.path.join(MOVIES, name + '.xmv')
    dst = os.path.join(OUT, name + '.mp4')
    if os.path.exists(dst) and not args.force:
        print(f'{name}: already there (--force to redo)')
        return
    work = os.path.join(WORK, name)
    shutil.rmtree(work, ignore_errors=True)
    raw, big = os.path.join(work, 'raw'), os.path.join(work, 'big')
    os.makedirs(raw)
    os.makedirs(big)
    t0 = time.time()

    times = frame_times(ffprobe, src)
    vf = ['bwdif=mode=send_frame'] if args.deinterlace else []
    cmd = [ffmpeg, '-v', 'error', '-y', '-i', src, '-map', '0:v:0', '-fps_mode', 'passthrough']
    if vf:
        cmd += ['-vf', ','.join(vf)]
    subprocess.run(cmd + [os.path.join(raw, '%06d.png')], check=True)
    frames = sorted(os.listdir(raw))
    if len(frames) != len(times):
        print(f'{name}: {len(frames)} frames but {len(times)} times; spacing them evenly')
        span = times[-1] - times[0] if len(times) > 1 else len(frames) / 30.0
        times = [i * span / max(1, len(frames) - 1) for i in range(len(frames))]

    if args.upscale == 'ai':
        subprocess.run([esrgan, '-i', raw, '-o', big, '-n', args.model, '-s', str(args.scale),
                        '-f', 'png'], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        pics, folder = sorted(os.listdir(big)), big
        if len(pics) != len(frames):
            sys.exit(f'{name}: Real-ESRGAN wrote {len(pics)} of {len(frames)} frames')
    else:
        pics, folder = frames, raw

    # The concat demuxer carries each frame's own duration into the copy.
    script = os.path.join(work, 'frames.txt')
    with open(script, 'w', encoding='utf-8') as f:
        for i, pic in enumerate(pics):
            nxt = times[i + 1] if i + 1 < len(times) else times[i] + 1001 / 30000
            f.write(f"file '{os.path.join(folder, pic)}'\nduration {nxt - times[i]:.6f}\n")
    os.makedirs(OUT, exist_ok=True)
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', script,
                    '-vf', f'scale=-2:{args.height}:flags=lanczos,format=yuv420p',
                    # Millisecond timestamps: in the concat input's default
                    # 1/25 s ones, frames 33 ms apart share a slot and vfr
                    # drops one (1510 of Intro's 1801 frames survived).
                    '-fps_mode', 'passthrough', '-enc_time_base', '1/1000',
                    '-video_track_timescale', '1000',
                    '-c:v', 'libopenh264', '-b:v', args.bitrate,
                    '-an', dst], check=True)
    shutil.rmtree(work, ignore_errors=True)
    print(f'{name}: {len(pics)} frames -> {os.path.relpath(dst, ROOT)}'
          f' ({os.path.getsize(dst) / 1e6:.0f} MB, {time.time() - t0:.0f} s)')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('names', nargs='*', help='movies to convert (default: all)')
    ap.add_argument('--upscale', choices=['ai', 'lanczos'], default='ai')
    ap.add_argument('--model', default='realesr-animevideov3')
    ap.add_argument('--scale', type=int, default=3, help='Real-ESRGAN factor (2-4)')
    ap.add_argument('--height', type=int, default=1080)
    ap.add_argument('--bitrate', default='12M')
    ap.add_argument('--deinterlace', action='store_true')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    ffmpeg = tool('ffmpeg', 'ffmpeg', 'bin')
    ffprobe = tool('ffprobe', 'ffmpeg', 'bin')
    esrgan = tool('realesrgan-ncnn-vulkan', 'realesrgan') if args.upscale == 'ai' else None
    names = args.names or sorted(os.path.splitext(n)[0] for n in os.listdir(MOVIES)
                                 if n.lower().endswith('.xmv'))
    for name in names:
        convert(name, args, ffmpeg, ffprobe, esrgan)


if __name__ == '__main__':
    main()
