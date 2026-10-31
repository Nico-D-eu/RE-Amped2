"""Writes the suite's pad scripts (RECOMP_PAD_SCRIPT=@file).

    py -3 -I tools/suite/pads/make_pads.py

One step per line, <ms>:<button>[+<button>...][:<hold ms>], with times from
the title's first pad poll. The toolkit's parser takes no comments and at
most 256 steps, so the timings are kept readable here instead. Mapped from
shots on 2026-10-30 (fresh console, PlayMovies=0):

  title (Start) -> Choose a Look (Start) -> Enter Name (A on Done) -> saving
  -> Main Menu (A: Career) -> Career (A: Ride!) -> Ride! (A: Millicent 1)
  -> loading -> Millicent 1 (A: Evergreen) -> Media Challenge (A)
  -> Challenges (A) -> riding, about 30 s after the first poll.

A that lands on a loading screen is ignored, and one that lands in the game
is a jump, so the menus get an A every 2 s instead of exact times. In the
game the pause menu is Resume, Restart Run, Choose New Run, Challenge
Checklist, Recent Players, Options, Leave Mountain; Leave Mountain goes
straight back to Career, with no confirmation.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def menu(t0=14000, t1=50000):
    """From the title into ML1's first run."""
    s = ['4000:start', '7000:start', '10000:start']
    return s + ['%d:a' % t for t in range(t0, t1 + 1, 2000)]


def ride(t0, t1):
    """Weave 1.5 s left, 1.5 s right, with a jump in each."""
    s, t, left = [], t0, True
    while t < t1:
        s.append('%d:%s:1400' % (t, 'lleft' if left else 'lright'))
        s.append('%d:a' % (t + 700))
        t += 1500
        left = not left
    return s


def leave(t0):
    """Pause, down to Leave Mountain, A; then A through the menus back to
    riding (about 20 s later)."""
    s = ['%d:start' % t0]
    s += ['%d:down' % (t0 + 2000 + 600 * i) for i in range(6)]
    s.append('%d:a' % (t0 + 6500))
    s += ['%d:a' % t for t in range(t0 + 10000, t0 + 34001, 2000)]
    return s


def write(name, steps):
    assert len(steps) <= 256, (name, len(steps))
    with open(os.path.join(HERE, name), 'w', newline='\n') as f:
        f.write('\n'.join(steps) + '\n')
    print('%s: %d steps' % (name, len(steps)))


# ml1: into ML1, then ride to the end of the case (200 s).
write('ml1.pad', menu() + ride(52000, 210000))

# reload3: ride 15 s, leave the mountain, back in; three times.
steps, t = menu(), 52000
for _ in range(3):
    steps += ride(t, t + 15000)
    steps += leave(t + 16000)
    t += 16000 + 36000
steps += ride(t, t + 30000)
write('reload3.pad', steps)
