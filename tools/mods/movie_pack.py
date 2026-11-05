"""The movie pack: higher-resolution copies of the game's movies.

    python tools/mods/movie_pack.py [Name ...] [--upscale auto|ai|lanczos]
                                    [--height 1080] [--deinterlace [auto|on|off]]
                                    [--force]

Game data is never committed, so the movie pack is a recipe. It reads the
player's own game/Movies/<Name>.xmv and writes mods/movie_pack/<Name>.mp4,
which the runtime (src/movie_pack.c) draws in place of the movie's
640x480 picture. The game's own decoder keeps running underneath for the
timing, the sound and Start to skip, so only the picture is needed: the
copies have no audio track. With no names, every movie is converted, the
ones shown at start-up first. A movie that already has a copy is skipped,
so a stopped run picks up where it left off.

Steps per movie:
  1. FFmpeg decodes the XMV (WMV2 video) to PNG frames and lists each
     frame's time. XMV frames are not evenly spaced (Intro.xmv: 1801
     frames in 60.86 s), and the runtime matches frames by time, so the
     copy keeps the original times.
  2. --upscale ai: Real-ESRGAN (realesrgan-ncnn-vulkan, on the GPU through
     Vulkan) upscales 3x with its fast video model realesr-animevideov3,
     about 9 frames/s on an RTX 2070. With decode and encode, 6 minutes
     for the 61 s intro and 4 h 48 min for all 50 movies (53.5 minutes).
     --model realesrgan-x4plus keeps more texture but takes about 2 s a
     frame.
     --upscale lanczos: a plain resize, minutes for everything.
     --upscale auto (the default): ai, and lanczos from then on if
     Real-ESRGAN fails (no Vulkan graphics card, for example).
  3. FFmpeg scales to --height (4:3, so 1440x1080 by default) and encodes
     H.264 with OpenH264, which Windows' own Media Foundation plays; with
     libx264 where the FFmpeg has no OpenH264 (most Linux builds). On Linux
     the game decodes the copies with the system's FFmpeg.

Steps 2 and 3 run --batch frames at a time, and the pieces are joined at
the end. Upscaled frames are about 1.7 MB each, so the longest movie
(Port_Career_legend, 7100 frames) would otherwise need 13 GB of work space;
batches of 500 keep it near 2 GB. The copy is written as <Name>.mp4.part
and renamed when complete, so a game running meanwhile never opens half a
file.

--deinterlace runs bwdif first. The live-action Port_* movies show
interlacing combs, which the AI model otherwise sharpens, so auto (the
default) deinterlaces those.

Tools: tools/bin/ffmpeg/bin/ffmpeg.exe (an LGPL build, BtbN's
FFmpeg-Builds) and tools/bin/realesrgan/ (xinntao/Real-ESRGAN's
ncnn-vulkan release), or the same programs on PATH. On Linux, the
system's ffmpeg package; Real-ESRGAN only if the player adds it, else
--upscale auto falls back to the plain resize. Work files go to
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
# The logos and intro play at every start-up and the attract movie soon
# after, so a fresh run converts those first.
FIRST = ['xsn', 'mgs', 'Intro', 'AttractMode']


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


def upscale(esrgan, args, src, dst):
    """Real-ESRGAN on one folder of frames; False if it failed."""
    done = subprocess.run([esrgan, '-i', src, '-o', dst, '-n', args.model, '-s', str(args.scale),
                           '-f', 'png'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return done.returncode == 0 and len(os.listdir(dst)) == len(os.listdir(src))


def doubled(rate):
    """'12M' -> '24M'."""
    unit = rate[-1] if rate[-1] in 'kKmM' else ''
    return f'{float(rate[:len(rate) - len(unit)]) * 2:g}{unit}'


_encoder = None


def h264_encoder(ffmpeg):
    """libopenh264 when this FFmpeg has it (the Windows LGPL build, Fedora's
    ffmpeg-free), else libx264 (Ubuntu's, Arch's and most Linux builds)."""
    global _encoder
    if _encoder is None:
        out = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True,
                             text=True).stdout
        _encoder = ('libopenh264' if ' libopenh264 ' in out
                    else 'libx264' if ' libx264 ' in out else None)
        if not _encoder:
            sys.exit('this FFmpeg has no H.264 encoder (libopenh264 or libx264)')
        print(f'H.264 encoder: {_encoder}')
    return _encoder


def encode(ffmpeg, args, pics, durations, script, out):
    """H.264 from a list of pictures, each shown for its own duration."""
    # The concat demuxer carries each frame's own duration into the copy.
    # Its timestamps are in the first picture's time base, 1/25 s for a
    # still image unless framerate says otherwise: without the option every
    # frame time snapped to 40 ms, up to 20 ms off.
    with open(script, 'w', encoding='utf-8') as f:
        for pic, d in zip(pics, durations):
            f.write(f"file '{pic}'\noption framerate 1000\nduration {d:.6f}\n")
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', script,
                    '-vf', f'scale=-2:{args.height}:flags=lanczos,format=yuv420p',
                    # Millisecond timestamps: in the concat input's default
                    # 1/25 s ones, frames 33 ms apart share a slot and vfr
                    # drops one (1510 of Intro's 1801 frames survived).
                    '-fps_mode', 'passthrough', '-enc_time_base', '1/1000',
                    '-video_track_timescale', '1000',
                    *codec_args(ffmpeg, args),
                    '-an', '-f', 'mp4', out], check=True)


def codec_args(ffmpeg, args):
    if h264_encoder(ffmpeg) == 'libopenh264':
        # OpenH264 shares the bitrate out by the frame rate it is told,
        # capped at 60: the 1000 fps of the pictures' time base becomes 60,
        # twice the movies' 29.97, so it is asked for twice the bitrate.
        # FFmpeg refuses -r with passthrough, which would have said so.
        return ['-c:v', 'libopenh264', '-b:v', doubled(args.bitrate)]
    # x264 rates by the frames' real times, so no doubling. Main profile:
    # any H.264 decoder plays it.
    return ['-c:v', 'libx264', '-preset', 'medium', '-profile:v', 'main',
            '-b:v', args.bitrate, '-maxrate', doubled(args.bitrate),
            '-bufsize', doubled(args.bitrate)]


def convert(name, args, ffmpeg, ffprobe, esrgan):
    src = os.path.join(MOVIES, name + '.xmv')
    dst = os.path.join(OUT, name + '.mp4')
    if os.path.exists(dst) and not args.force:
        print(f'{name}: already there (--force to redo)')
        return
    work = os.path.join(WORK, name)
    shutil.rmtree(work, ignore_errors=True)
    raw = os.path.join(work, 'raw')
    os.makedirs(raw)
    t0 = time.time()

    times = frame_times(ffprobe, src)
    deinterlace = args.deinterlace == 'on' or (args.deinterlace == 'auto' and name.startswith('Port_'))
    cmd = [ffmpeg, '-v', 'error', '-y', '-i', src, '-map', '0:v:0', '-fps_mode', 'passthrough']
    if deinterlace:
        cmd += ['-vf', 'bwdif=mode=send_frame']
    subprocess.run(cmd + [os.path.join(raw, '%06d.png')], check=True)
    frames = sorted(os.listdir(raw))
    if len(frames) != len(times):
        print(f'{name}: {len(frames)} frames but {len(times)} times; spacing them evenly')
        span = times[-1] - times[0] if len(times) > 1 else len(frames) / 30.0
        times = [i * span / max(1, len(frames) - 1) for i in range(len(frames))]
    times.append(times[-1] + 1001 / 30000)   # when the last frame ends

    # Batches: move a batch's frames to their own folder, upscale it, encode
    # it, and remove its pictures before the next one.
    parts = []
    for b, first in enumerate(range(0, len(frames), args.batch)):
        names = frames[first:first + args.batch]
        lo = os.path.join(work, f'b{b}')
        os.makedirs(lo)
        for n in names:
            os.replace(os.path.join(raw, n), os.path.join(lo, n))
        folder = lo
        if args.upscale != 'lanczos':
            hi = os.path.join(work, f'b{b}x')
            os.makedirs(hi)
            if upscale(esrgan, args, lo, hi):
                folder = hi
            elif args.upscale == 'ai':
                sys.exit(f'{name}: Real-ESRGAN failed on frames {first + 1}-{first + len(names)}')
            else:
                print(f'{name}: Real-ESRGAN failed (no Vulkan graphics card?); '
                      'using a plain resize from here on')
                args.upscale = 'lanczos'
        pics = [os.path.join(folder, n) for n in sorted(os.listdir(folder))]
        span = times[first:first + len(names) + 1]
        part = os.path.join(work, f'part{b}.mp4')
        encode(ffmpeg, args, pics, [span[i + 1] - span[i] for i in range(len(names))],
               os.path.join(work, f'b{b}.txt'), part)
        parts.append((part, span[-1] - span[0]))
        shutil.rmtree(lo)
        shutil.rmtree(folder, ignore_errors=True)
        print(f'{name}: {first + len(names)} of {len(frames)} frames', flush=True)

    # Joined without re-encoding. Each part's duration is given, so the next
    # one starts exactly where the original's next frame does.
    os.makedirs(OUT, exist_ok=True)
    script = os.path.join(work, 'parts.txt')
    with open(script, 'w', encoding='utf-8') as f:
        for part, d in parts:
            f.write(f"file '{part}'\nduration {d:.6f}\n")
    tmp = dst + '.part'
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', script,
                    '-c', 'copy', '-video_track_timescale', '1000', '-f', 'mp4', tmp], check=True)
    os.replace(tmp, dst)
    shutil.rmtree(work, ignore_errors=True)
    print(f'{name}: {len(frames)} frames -> {os.path.relpath(dst, ROOT)}'
          f' ({os.path.getsize(dst) / 1e6:.0f} MB, {time.time() - t0:.0f} s)', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('names', nargs='*', help='movies to convert (default: all)')
    ap.add_argument('--upscale', choices=['auto', 'ai', 'lanczos'], default='auto')
    ap.add_argument('--model', default='realesr-animevideov3')
    ap.add_argument('--scale', type=int, default=3, help='Real-ESRGAN factor (2-4)')
    ap.add_argument('--height', type=int, default=1080)
    ap.add_argument('--bitrate', default='12M')
    ap.add_argument('--batch', type=int, default=500, help='frames upscaled at a time')
    ap.add_argument('--deinterlace', nargs='?', choices=['auto', 'on', 'off'], const='on',
                    default='auto', help='auto: the Port_* movies')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    ffmpeg = tool('ffmpeg', 'ffmpeg', 'bin')
    ffprobe = tool('ffprobe', 'ffmpeg', 'bin')
    esrgan = None
    if args.upscale == 'ai':
        esrgan = tool('realesrgan-ncnn-vulkan', 'realesrgan')
    elif args.upscale == 'auto':
        bundled = os.path.join(ROOT, 'tools', 'bin', 'realesrgan', 'realesrgan-ncnn-vulkan' + EXE)
        esrgan = bundled if os.path.isfile(bundled) else shutil.which('realesrgan-ncnn-vulkan')
        if not esrgan:
            print('Real-ESRGAN not found; using a plain resize')
            args.upscale = 'lanczos'
    names = args.names
    if not names:
        names = sorted(os.path.splitext(n)[0] for n in os.listdir(MOVIES)
                       if n.lower().endswith('.xmv'))
        names = [n for n in FIRST if n in names] + [n for n in names if n not in FIRST]
    for name in names:
        convert(name, args, ffmpeg, ffprobe, esrgan)
    print('All movies done.')


if __name__ == '__main__':
    main()
