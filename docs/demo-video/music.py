"""Ragdoll Mail demo video: an upbeat launch track, 120 BPM, A minor to C, about 36 s. One bar = 2 s.
Cut to the video: bars 1-2 pluck riff alone (the app, the terminal opens) · 3-5 hats, claps and a rising bass while
the agent types · bar 6 (10 s) the drop as the draft lands in the app: four-on-the-floor kick, synth bass,
lead riff · 9-11 send, undo, send later · 12-15 search, the riff an octave up · bar 16 (30 s) the end card:
a big hit that rings out. make.sh plays bars 6-9 twice, so the cut of the current story (the draft saved, read in the app,
sent by the agent, found in Sent) gets 38 s: the drop as the draft is saved, the hit with the end card.
Build with the code-composer skill: sh <skill>/engine/build.sh docs/demo-video/music.py, then
ffmpeg -i <skill>/engine/song.wav -c:a aac -b:a 160k docs/demo-video/music.m4a"""
import os, sys
sys.path.insert(0, os.environ.get("COMPOSER", os.path.expanduser("~/.claude/skills/code-composer/engine")))
from compose_kit import *  # noqa: E402,F403

channel(0, 'pluck', 80, gain=0.85, pan=-0.1, reverb=0.22, hpf=180)      # square lead, short notes: a pluck
channel(1, 'pad', 89, gain=0.42, reverb=0.45, hpf=160, haas=16)
channel(2, 'bass', 38, gain=1.0, reverb=0.04)                             # synth bass 1
channel(3, 'lead', 81, gain=0.62, pan=0.12, reverb=0.3, hpf=250, haas=8)  # saw lead
channel(4, 'bells', 9, gain=0.5, pan=0.25, reverb=0.4, hpf=400)          # glockenspiel sparkle
channel(9, 'drums', 0, gain=1.15, reverb=0.08)

tempo([(0, 64, 120, 120)], intro=0.05, tail=4.5, seed=21)

prog = [('Am', 4), ('F', 4), ('C', 4), ('G', 4)]
# the riff: 16th-note plucks, two bars long
riff = [('A5', .5), ('E5', .25), ('A5', .25), ('C6', .5), ('A5', .5), ('E6', .5), ('D6', .25), ('C6', .25), ('B5', .5), ('G5', .5),
        ('F5', .5), ('A5', .25), ('C6', .25), ('F6', .5), ('C6', .5), ('E6', .5), ('D6', .5), ('B5', .5), ('G5', .5)]


def riff_at(ch, b, octave=0, vel=78):
    up = lambda p: p[:-1] + str(int(p[-1]) + octave)  # noqa: E731
    melody(ch, b, [(up(p), d) for p, d in riff], vel=vel, legato=0.45, tag='theme')


# bars 1-2: the riff alone, with a soft pad
riff_at(0, bar(1), vel=56)
chords(1, bar(1), [('Am', 4), ('F', 4)], vel=46, lo=57, hi=76)
expression(1, bar(1), bar(6), 40, 100)

# bars 3-5: the build while the agent types: hats, claps, a pulsing bass, a snare roll into the drop
riff_at(0, bar(3), vel=62)
chords(1, bar(3), prog[:2] + [('C', 4)], vel=52, lo=57, hi=76)
drums(bar(3), 2, {'hat': 'x.x.x.x.x.x.x.x.', 'clap': '....x.......x...'}, vel=54)
for i in range(8):
    note(2, p('A2') if i < 4 else p('F2'), bar(3) + i, 0.45, 70)
for i in range(8):
    note(2, p('C3'), bar(5) + i * 0.5, 0.22, 66 + i * 3)
for i in range(16):
    note(9, DRUM['snare'], bar(5) + 2 + i * 0.125, 0.1, 50 + i * 3)

# bars 6-11: the drop: four-on-the-floor, offbeat open hats, synth bass, the lead takes the riff
groove = {'kick': 'x...x...x...x...', 'clap': '....x.......x...', 'ohat': '..x...x...x...x.', 'hat': 'x.xxx.xxx.xxx.xx'}
drums(bar(6), 6, groove, vel=92)
note(9, DRUM['crash'], bar(6), 1, 110)
bass(2, bar(6), prog + prog[:2], vel=96, pattern=[(0, .5), (.75, .25), (1, .5), (1.5, .5), (2, .5), (2.75, .25), (3, .5), (3.5, .5)])
chords(1, bar(6), prog + prog[:2], vel=60, lo=57, hi=76)
riff_at(3, bar(6), vel=88)
riff_at(0, bar(6), vel=60)
riff_at(3, bar(8), vel=90)
riff_at(0, bar(8), vel=62)
riff_at(3, bar(10), vel=86)
melody(4, bar(6), [('E6', 2), ('C6', 2), ('G6', 2), ('B6', 2)] * 3, vel=56)

# bars 12-15: search: the riff an octave up, bells, a short lift into the end card
drums(bar(12), 4, groove, vel=94)
note(9, DRUM['crash'], bar(12), 1, 100)
bass(2, bar(12), prog * 2, vel=98, pattern=[(0, .5), (.75, .25), (1, .5), (1.5, .5), (2, .5), (2.75, .25), (3, .5), (3.5, .5)])
chords(1, bar(12), prog * 2, vel=64, lo=57, hi=76)
riff_at(3, bar(12), octave=1, vel=84)
riff_at(0, bar(12), vel=66)
riff_at(3, bar(14), octave=1, vel=88)
riff_at(0, bar(14), vel=68)
melody(4, bar(12), [('A6', 1), ('E6', 1), ('C7', 2), ('G6', 1), ('D6', 1), ('B6', 2)] * 2, vel=58)
for i in range(8):
    note(9, DRUM['snare'], bar(15) + 2 + i * 0.25, 0.1, 60 + i * 5)

# bar 16: the end card: one big C major hit that rings out
note(9, DRUM['crash'], bar(16), 1, 118)
note(9, DRUM['kick'], bar(16), 1, 110)
chords(1, bar(16), [('Cadd9', 8)], vel=72, lo=55, hi=79)
expression(1, bar(16), bar(18), 110, 20)
chords(3, bar(16), [('C', 2)], vel=80, lo=60, hi=84, n=4)
bass(2, bar(16), [('C', 4)], vel=90, pattern=[(0, 3)])
melody(4, bar(16), [('C7', 1), ('G6', 1), ('E6', 4)], vel=62)
melody(0, bar(16), [('C6', .5), ('G5', .5), ('E6', 1), ('C6', 2)], vel=66)

export(end_beat=bar(18))
