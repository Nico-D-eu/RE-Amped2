"""Checks one suite run: its log, its samples and its screenshots.

    py -3 -I tools/suite/analyze.py <case.json> <run.txt> [--samples run.samples.csv]
        [--shots <dir> --shot-prefix <prefix>] [--goldens <dir>]
        [--baseline coverage-baseline.txt] [--crash-dir <dir>]

Prints one JSON object: the case name, pass or fail, every check with its
detail, and the numbers the report shows. tools/suite.ps1 runs it once per
case; the case itself comes from tools/suite/cases.json.

The log has no timestamps. diag.ps1 -Samples records the log's size once a
second, which puts a time on every line to within a second. The title's
own clock is the [GPU] frames line ("N in T s"), written every ~10 s while
it flips; the frame-rate checks use that.
"""
import argparse
import json
import os
import re
import struct
import sys

# Common checks: things no case may show. Case-sensitive, as in diag.ps1
# (a case-insensitive CRASH would match the title's Crashes.xsb).
FATAL = [
    ('crash', r'\[CRASH\]'),
    ('watchdog', r'\[WATCHDOG\]'),
    ('reboot', r'HalReturnToFirmware'),
    ('out-of-memory', r'out-of-memory handler'),
    ('bug-check', r'KeBugCheck'),
    ('audio-repeat', r'\[AUDIO\] the output repeats'),
]

FRAMES = re.compile(r'^\[GPU\] frames: (\d+) in (\d+) s')
IDLE_VOICES = re.compile(r'(\d+) idle voices linked')
APU_RATE = re.compile(r'APU (\d+) frames/s')
LOCK_HOLD = re.compile(r'longest hold (\d+) ms at guest (0x[0-9A-Fa-f]+)')
REACHED = re.compile(r'\[REACHED\] (\S+) (0x[0-9A-Fa-f]+)')
PACE_LATE = re.compile(r'\[PACE\] frame (\d+) ms late')
BOOT = re.compile(r'^\[BOOT\] RE-Amped2 build (.*)$')


def read_log(path):
    """Lines with the byte offset each one ends at."""
    with open(path, 'rb') as f:
        data = f.read()
    lines, ends, pos = [], [], 0
    for raw in data.split(b'\n'):
        pos += len(raw) + 1
        lines.append(raw.decode('utf-8', 'replace').rstrip('\r'))
        ends.append(pos)
    return lines, ends


def read_samples(path):
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path) as f:
        next(f, None)
        for line in f:
            p = line.strip().split(',')
            if len(p) == 4:
                rows.append((float(p[0]), int(p[1]), float(p[2]), float(p[3])))
    return rows


def line_time(samples, end_byte):
    """The first sample whose log size covers the line: when it was there."""
    for t, size, _, _ in samples:
        if size >= end_byte:
            return t
    return samples[-1][0] if samples else None


def find(lines, pattern, start=0):
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i
    return None


def bmp_grid(path, cols=32, rows=18):
    """A cols x rows grid of mean RGB over a 24-bit BMP, from a sparse
    sample of each cell (the shots are 720p; every pixel is not needed)."""
    with open(path, 'rb') as f:
        data = f.read()
    off = struct.unpack_from('<I', data, 10)[0]
    w, h = struct.unpack_from('<ii', data, 18)
    bpp = struct.unpack_from('<H', data, 28)[0]
    if bpp not in (24, 32):
        raise ValueError('%s: %d bpp' % (path, bpp))
    step = bpp // 8
    stride = (w * step + 3) & ~3
    flip = h > 0
    h = abs(h)
    grid = []
    for gy in range(rows):
        for gx in range(cols):
            acc = [0, 0, 0]
            n = 0
            for sy in range(4):
                y = (gy * h // rows) + (sy * h // rows) // 4
                row = (h - 1 - y) if flip else y
                for sx in range(4):
                    x = (gx * w // cols) + (sx * w // cols) // 4
                    i = off + row * stride + x * step
                    acc[0] += data[i + 2]
                    acc[1] += data[i + 1]
                    acc[2] += data[i]
                    n += 1
            grid.append((acc[0] / n, acc[1] / n, acc[2] / n))
    return grid


def grid_diff(a, b):
    """Mean absolute difference per channel, 0-255."""
    return sum(abs(p - q) for x, y in zip(a, b) for p, q in zip(x, y)) / (3 * len(a))


def grid_brightness(g):
    return sum(sum(c) for c in g) / (3 * len(g))


class Result:
    def __init__(self, name):
        self.name = name
        self.checks = []
        self.metrics = {}

    def check(self, name, ok, detail='', warn=False):
        self.checks.append({'check': name, 'ok': bool(ok), 'warn': warn and not ok,
                            'detail': detail})

    @property
    def passed(self):
        return all(c['ok'] or c['warn'] for c in self.checks)


def frames_after(lines, start, skip_s):
    """[GPU] frames samples after line `start`, skipping the first skip_s
    seconds of the title's clock: (index, frames, seconds)."""
    pts = []
    for i in range(start, len(lines)):
        m = FRAMES.match(lines[i])
        if m:
            pts.append((i, int(m.group(1)), int(m.group(2))))
    if not pts:
        return []
    t0 = pts[0][2] + skip_s
    return [p for p in pts if p[2] >= t0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('case')
    ap.add_argument('log')
    ap.add_argument('--samples')
    ap.add_argument('--shots')
    ap.add_argument('--shot-prefix', default='')
    ap.add_argument('--goldens')
    ap.add_argument('--baseline')
    ap.add_argument('--crash-dir')
    a = ap.parse_args()

    # utf-8-sig: PowerShell 5.1 writes UTF-8 with a byte-order mark.
    case = (json.loads(a.case) if a.case.lstrip().startswith('{')
            else json.load(open(a.case, encoding='utf-8-sig')))
    checks = case.get('checks', {})
    r = Result(case['name'])
    lines, ends = read_log(a.log)
    samples = read_samples(a.samples)

    m = next((BOOT.match(l) for l in lines[:50] if BOOT.match(l)), None)
    r.metrics['build'] = m.group(1) if m else '?'
    r.metrics['log_lines'] = len(lines)

    # Common checks.
    for name, pat in FATAL:
        rx = re.compile(pat)
        hits = [i for i, l in enumerate(lines) if rx.search(l)]
        r.check('no ' + name, not hits,
                ('line %d: %s' % (hits[0] + 1, lines[hits[0]].strip()[:160])) if hits else '')
    if a.crash_dir and os.path.isdir(a.crash_dir):
        reports = os.listdir(a.crash_dir)
        r.check('no crash report', not reports, ', '.join(reports[:3]))
    # Idle voices linked: a handful in passing is DirectSound's normal stop
    # path (toolkit apu_vp.c); a steady count is the dead-voice bug, which
    # also slows the APU (2026-10-02: a third of its 1500 frames/s).
    idle = [int(x.group(1)) for x in map(IDLE_VOICES.search, lines) if x]
    apu = [int(x.group(1)) for x in map(APU_RATE.search, lines) if x]
    r.metrics['idle_voices_max'] = max(idle) if idle else None
    if checks.get('health', True):
        run = longest = 0
        for v in idle:
            run = run + 1 if v else 0
            longest = max(longest, run)
        r.check('idle voices linked not steady', idle and longest < 3,
                'max %s, nonzero in %d of %d [HEALTH] lines, %d in a row at most'
                % (max(idle) if idle else '-', sum(1 for v in idle if v), len(idle), longest))
        # The first lines can come before the APU runs.
        steady = apu[2:]
        r.metrics['apu_frames_min'] = min(steady) if steady else None
        r.check('APU at >= 1400 frames/s', steady and min(steady) >= 1400,
                'min %s over %d lines' % (min(steady) if steady else '-', len(steady)))
    # The XACT DPC hitch (docs/DEVELOPING.md): a long dispatch-lock hold.
    # Known and rare, so a warning, not a failure.
    holds = [(int(x.group(1)), x.group(2)) for x in map(LOCK_HOLD.search, lines) if x]
    if holds:
        worst = max(holds)
        r.metrics['lock_hold_max_ms'] = worst[0]
        r.check('dispatch-lock holds under %d ms' % checks.get('hold_max_ms', 250),
                worst[0] < checks.get('hold_max_ms', 250),
                'longest %d ms at guest %s' % worst, warn=True)
    stalls = [l.strip()[:120] for l in lines if '[STALL]' in l and 'held the' in l]
    r.metrics['stalls'] = len(stalls)
    r.check('at most %d dispatch-lock stalls' % checks.get('stalls_max', 3),
            len(stalls) <= checks.get('stalls_max', 3), '; '.join(stalls[:2]), warn=True)

    # Coverage: nothing reached that the baseline has not seen.
    reached = sorted({(x.group(1), x.group(2).upper().replace('0X', '0x'))
                      for x in map(REACHED.search, lines) if x})
    r.metrics['reached'] = ['%s %s' % k for k in reached]
    if a.baseline and not os.path.exists(a.baseline):
        r.check('coverage baseline', False, 'none yet (-UpdateBaseline)', warn=True)
    elif a.baseline:
        base = set()
        if os.path.exists(a.baseline):
            for l in open(a.baseline):
                p = l.split()
                if len(p) >= 2 and not l.startswith('#'):
                    base.add((p[0], p[1].upper().replace('0X', '0x')))
        new = [k for k in reached if k not in base]
        r.metrics['reached_new'] = ['%s %s' % k for k in new]
        r.check('no coverage beyond the baseline', not new,
                ', '.join('%s %s' % k for k in new[:6]) if new else
                '%d reached, all known' % len(reached))

    # Markers that must appear, in order.
    at = 0
    times = {}
    for pat in checks.get('markers', []):
        i = find(lines, pat, at)
        r.check('reached /%s/' % pat, i is not None,
                ('line %d%s' % (i + 1, ', %.0f s' % line_time(samples, ends[i])
                                if samples else '')) if i is not None else 'not in the log')
        if i is None:
            break
        times[pat] = i
        at = i
    for pat in checks.get('forbid', []):
        i = find(lines, pat)
        r.check('never /%s/' % pat, i is None,
                'line %d: %s' % (i + 1, lines[i].strip()[:120]) if i is not None else '')

    # Events that show up as a cluster of lines (a level load opens its
    # files a few times): clusters more than gap_lines apart.
    for spec in checks.get('counts', []):
        rx = re.compile(spec['pattern'])
        hits = [i for i, l in enumerate(lines) if rx.search(l)]
        n, last = 0, None
        for i in hits:
            if last is None or i - last > spec.get('gap_lines', 300):
                n += 1
            last = i
        label = spec.get('what', spec['pattern'])
        r.metrics[label] = n
        r.check('%s at least %d times' % (label, spec['min']), n >= spec['min'], '%d' % n)

    # How long from one marker to the next, by the samples' clock.
    for spec in checks.get('durations', []):
        i = find(lines, spec['from'])
        j = find(lines, spec['to'], i or 0) if i is not None else None
        label = '%s within %s s' % (spec.get('what', 'duration'), spec['max_s'])
        if i is None or j is None or not samples:
            r.check(label, False, 'markers or samples missing')
            continue
        d = line_time(samples, ends[j]) - line_time(samples, ends[i])
        r.metrics[spec.get('what', 'duration') + '_s'] = round(d, 1)
        r.check(label, d <= spec['max_s'], '%.0f s' % d,
                warn=bool(spec.get('known')))
        if spec.get('known') and d > spec['max_s']:
            r.checks[-1]['detail'] += ' (known: %s)' % spec['known']

    # Numbers the log reports: the last match of a pattern with one group.
    for spec in checks.get('numbers', []):
        rx = re.compile(spec['pattern'])
        vals = [float(x.group(1)) for x in map(rx.search, lines) if x]
        label = spec.get('what', spec['pattern'])
        if not vals:
            r.check(label, False, 'not in the log')
            continue
        v = vals[-1]
        ok = ('min' not in spec or v >= spec['min']) and ('max' not in spec or v <= spec['max'])
        r.metrics[label] = v
        r.check('%s in [%s, %s]' % (label, spec.get('min', ''), spec.get('max', '')), ok, '%g' % v)

    # Frame rate and pacing, from a marker on.
    fps = checks.get('fps')
    if fps:
        start = find(lines, fps['after']) if fps.get('after') else 0
        pts = frames_after(lines, start or 0, fps.get('skip_s', 0)) if start is not None else []
        if pts and 'span_s' in fps:
            # A bounded window: e.g. before an idle title starts its attract
            # movie, which draws no frames of the title's own.
            pts = [p for p in pts if p[2] <= pts[0][2] + fps['span_s']]
        if len(pts) >= 2:
            (i0, f0, t0), (i1, f1, t1) = pts[0], pts[-1]
            rate = (f1 - f0) / max(1, t1 - t0)
            steps = [(b[1] - a_[1]) / max(1, b[2] - a_[2]) for a_, b in zip(pts, pts[1:])]
            r.metrics['fps'] = round(rate, 2)
            r.metrics['fps_min_10s'] = round(min(steps), 1)
            r.metrics['fps_window_s'] = t1 - t0
            r.check('>= %s fps over %d s' % (fps['min'], t1 - t0), rate >= fps['min'],
                    '%.2f fps, slowest 10 s %.1f' % (rate, min(steps)))
            if 'min_10s' in fps:
                r.check('no 10 s below %s fps' % fps['min_10s'], min(steps) >= fps['min_10s'],
                        'slowest %.1f' % min(steps))
            if 'window_s' in fps:
                r.check('fps window at least %d s' % fps['window_s'], t1 - t0 >= fps['window_s'],
                        '%d s' % (t1 - t0))
            late = [int(x.group(1)) for x in map(PACE_LATE.search, lines[i0:i1 + 1]) if x]
            r.metrics['pace_resyncs'] = len(late)
            r.check('at most %d pacing resyncs' % fps.get('resyncs_max', 3),
                    len(late) <= fps.get('resyncs_max', 3),
                    '%d (longest %d ms)' % (len(late), max(late)) if late else 'none')
        else:
            r.check('fps window', False, 'fewer than two [GPU] frames lines after /%s/'
                    % fps.get('after'))

    # Memory: flat from a marker on (private bytes, the host's view).
    mem = checks.get('memory')
    if mem and not samples:
        r.check('memory window', False, 'no samples (diag.ps1 -Samples)')
    elif mem:
        start = find(lines, mem['after']) if mem.get('after') else 0
        t_start = (line_time(samples, ends[start]) if start is not None else None)
        if t_start is not None:
            t_start += mem.get('skip_s', 0)
            win = [s for s in samples if s[0] >= t_start]
            if len(win) >= 10:
                head = sorted(s[2] for s in win[:5])[2]
                tail = sorted(s[2] for s in win[-5:])[2]
                peak = max(s[2] for s in win)
                tol = mem.get('tolerance', 0.05)
                r.metrics['private_mb'] = [round(head), round(tail), round(peak)]
                r.check('private memory flat (+-%d%%)' % (tol * 100),
                        abs(tail - head) <= tol * head and peak <= head * (1 + 2 * tol),
                        '%.0f -> %.0f MB (peak %.0f) over %.0f s'
                        % (head, tail, peak, win[-1][0] - win[0][0]))
            else:
                r.check('memory window', False, 'only %d samples after the marker' % len(win))
        else:
            r.check('memory window', False, 'marker /%s/ not found' % mem.get('after'))

    # Screenshots against the goldens.
    shots = checks.get('shots')
    if shots and a.shots:
        for spec in shots:
            idx = spec['index']
            path = os.path.join(a.shots, '%s%04d.bmp' % (a.shot_prefix, idx))
            label = 'shot %d (%s)' % (idx, spec.get('what', ''))
            if not os.path.exists(path):
                r.check(label, False, 'not taken')
                continue
            g = bmp_grid(path)
            bright = grid_brightness(g)
            if 'min_brightness' in spec:
                r.check(label + ' not black', bright >= spec['min_brightness'],
                        'mean %.1f' % bright)
            gold = os.path.join(a.goldens or '', '%04d.bmp' % idx)
            if spec.get('golden') is False:
                continue
            if a.goldens and os.path.exists(gold):
                d = grid_diff(g, bmp_grid(gold))
                tol = spec.get('tolerance', 12)
                r.metrics['shot%d_diff' % idx] = round(d, 1)
                r.check(label + ' matches golden', d <= tol, 'diff %.1f (tolerance %s)' % (d, tol))
            else:
                r.check(label + ' golden', True, 'no golden yet (-UpdateGoldens)', warn=False)

    out = {'case': r.name, 'pass': r.passed, 'checks': r.checks, 'metrics': r.metrics}
    json.dump(out, sys.stdout)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
