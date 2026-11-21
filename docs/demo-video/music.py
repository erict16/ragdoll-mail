"""Ragdoll Mail demo video: a light, warm background track, about 36 s, D major, 100 BPM.
Form (bars of 2.4 s): 1-2 electric piano motif + pad · 3-6 bass and soft hats join · 7-10 fuller, light kick and
claps, harp counter-line · 11-13 last statement · 14-15 ending on Dmaj7 with a gentle slow-down."""
import os, sys
# build with the code-composer skill: sh <skill>/engine/build.sh docs/demo-video/music.py, then
# ffmpeg -i <skill>/engine/song.wav -c:a aac -b:a 160k docs/demo-video/music.m4a
sys.path.insert(0, os.environ.get("COMPOSER", os.path.expanduser("~/.claude/skills/code-composer/engine")))
from compose_kit import *  # noqa: E402,F403

channel(0, 'ep', 4, gain=1.25, pan=-0.08, reverb=0.32)
channel(1, 'pad', 89, gain=0.38, reverb=0.5, hpf=140, haas=16)
channel(2, 'bass', 33, gain=0.75, reverb=0.08)
channel(3, 'vibes', 11, gain=0.7, pan=0.2, reverb=0.4, hpf=250)
channel(4, 'harp', 46, gain=0.55, pan=0.3, reverb=0.35, hpf=200)
channel(9, 'drums', 0, gain=0.55, reverb=0.12)

tempo([(0, 52, 100, 100), (52, 60, 100, 82)], intro=0.2, tail=3.0, seed=11)

prog = [('D', 4), ('A', 4), ('Bm', 4), ('G', 4)]
motif = [('F#5', 0.5), ('A5', 0.5), ('B5', 1), ('A5', 1), (None, 1),
         ('E5', 0.5), ('F#5', 0.5), ('A5', 1), ('E5', 2)]
answer = [('D5', 0.5), ('E5', 0.5), ('F#5', 1), ('B5', 1), (None, 1),
          ('A5', 0.5), ('G5', 0.5), ('F#5', 1), ('E5', 2)]

# bars 1-2: the motif on electric piano over a soft pad
chords(1, bar(1), [('D', 4), ('A', 4)], vel=48, lo=55, hi=74)
expression(1, bar(1), bar(3), 30, 90)
melody(0, bar(1), motif, vel=72, tag='theme')
chords(0, bar(1), [('D', 4), ('A', 4)], vel=42, lo=50, hi=66, n=3, style='arp')

# bars 3-6: bass and quiet hats join; the motif answers itself
bass(2, bar(3), prog, vel=66, pattern=[(0, 1.5), (1.5, 0.5), (2, 2)])
chords(1, bar(3), prog, vel=52, lo=55, hi=74)
chords(0, bar(3), prog, vel=44, lo=50, hi=66, n=3, style='arp')
melody(0, bar(3), answer + motif, vel=76, tag='theme')
drums(bar(5), 2, {'hat': '..x...x...x...x.'}, vel=50)

# bars 7-10: a little fuller: light kick, claps, vibraphone carries the tune, harp plucks
groove = {'kick': 'x.........x.....', 'clap': '....x.......x...', 'hat': '..x...x...x...x.'}
drums(bar(7), 4, groove, vel=58)
bass(2, bar(7), prog, vel=72, pattern=[(0, 1.5), (1.5, 0.5), (2, 1), (3, 1)])
chords(1, bar(7), prog, vel=56, lo=55, hi=74)
chords(0, bar(7), prog, vel=46, lo=50, hi=66, n=3, style='arp')
melody(3, bar(7), motif + [('D6', 0.5), ('E6', 0.5), ('F#6', 1), ('A6', 1), (None, 1),
                           ('G6', 0.5), ('F#6', 0.5), ('E6', 1), ('D6', 2)], vel=70, tag='theme')
melody(4, bar(7), [('A4', 0.5), ('D5', 0.5), ('F#5', 0.5), (None, 2.5)] * 4, vel=52)

# bars 11-13: the last statement, the drums thin out
drums(bar(11), 2, {'kick': 'x.......x.......', 'hat': '..x...x...x...x.'}, vel=52)
bass(2, bar(11), [('D', 4), ('A', 4), ('G', 4)], vel=68)
chords(1, bar(11), [('D', 4), ('A', 4), ('G', 4)], vel=54, lo=55, hi=74)
chords(0, bar(11), [('D', 4), ('A', 4), ('G', 4)], vel=44, lo=50, hi=66, n=3, style='arp')
melody(0, bar(11), motif + [('D5', 0.5), ('E5', 0.5), ('F#5', 1), ('G5', 1), ('A5', 1)], vel=74, tag='theme')

# bars 14-15: home, on a soft D major 9 that rings out
chords(1, bar(14), [('Dmaj7', 8)], vel=50, lo=55, hi=76)
expression(1, bar(14), bar(16), 90, 30)
bass(2, bar(14), [('D', 8)], vel=60)
chords(0, bar(14), [('Dmaj7', 4)], vel=40, lo=50, hi=70, n=4, style='arp')
melody(3, bar(14), [('F#6', 1), ('A6', 1), ('D6', 6)], vel=58)
note(9, DRUM['crash'], bar(14), 1, 46)

export(end_beat=bar(16))
