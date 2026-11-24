#!/bin/sh
# Make the landing page's demo videos again, after the app's look changes:
#   sh docs/demo-video/make.sh
# Records the demo mailbox in headless Chromium (English app on the English mailbox, Chinese on the Chinese), cuts each take with
# captions, cursor and gentle zoom (compose.py, needs Pillow), and writes:
#   site/media/demo-en.mp4, demo-zh.mp4  (H.264, 1920x1200) and their first frames as .webp posters
#   docs/demo.gif                         (the English cut, for the README)
# Needs node, ffmpeg, python3 with Pillow (set PY to that python), and Chromium (see CHROME in drv.mjs).
# Runs on a Mac, or on Windows from Git Bash (ffmpeg on PATH, PY=python).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PY=${PY:-$(command -v python3 >/dev/null 2>&1 && python3 -c "" 2>/dev/null && echo python3 || echo python)}
FF=${FF:-ffmpeg}
PORT=${PORT:-8795}
WORK=${WORK:-${TMPDIR:-/tmp}/ragdoll-demo-video}
mkdir -p "$WORK/out"
cd "$WORK"
export PORT

stop() {     # whatever listens on the port (lsof on a Mac, PowerShell on Windows)
  if command -v lsof >/dev/null 2>&1; then for p in $(lsof -ti tcp:"$PORT" -sTCP:LISTEN); do kill "$p"; done
  else powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue | % { Stop-Process -Id \$_.OwningProcess -Force }; exit 0" || true; fi
}
server() {   # a fresh demo mailbox for each take
  stop
  sleep 1
  (cd "$REPO" && RAGDOLL_APP_TOKEN=devtok $PY ragdoll_app.py --demo --demo-lang "$1" --browser --no-open --port "$PORT" > "$WORK/server.log" 2>&1 &)
  for i in $(seq 1 40); do sleep 0.5; curl -s -o /dev/null "http://127.0.0.1:$PORT/" && return 0; done
  echo "the demo server did not start"; exit 1
}

# SKIP_RECORD=1 cuts the takes already in $WORK again (after a change to compose.py)
[ -n "$SKIP_RECORD" ] || for l in en zh; do
  rm -rf "take-$l"
  server $l
  node "$HERE/record.mjs" $l "take-$l" 2.5
  node "$HERE/assets.mjs" $l "assets-$l"
done
[ -n "$SKIP_RECORD" ] || stop

# the music, 4 bars longer: bars 6-9 (the drop) once more after bar 11, so the end card's hit comes at 38 s (compose.py)
$FF -v error -y -i "$HERE/music.m4a" -filter_complex "[0:a]asplit=3[x][y][z];[x]atrim=0:22.05,asetpts=PTS-STARTPTS[a];[y]atrim=10.05:18.05,asetpts=PTS-STARTPTS[b];[z]atrim=start=22.05,asetpts=PTS-STARTPTS[c];[a][b]acrossfade=d=0.02:c1=tri:c2=tri[ab];[ab][c]acrossfade=d=0.02:c1=tri:c2=tri" -c:a aac -b:a 160k music-long.m4a
for l in en zh; do
  $PY "$HERE/compose.py" $l "take-$l" "assets-$l" "master-$l.mp4" | tail -1
  $FF -v error -y -i "master-$l.mp4" -c:v libx264 -preset veryslow -crf 22 -tune animation -pix_fmt yuv420p \
    -profile:v high -level 5.1 -movflags +faststart -an -color_primaries bt709 -color_trc bt709 -colorspace bt709 "out/demo-$l.mp4"
  $FF -v error -y -i "out/demo-$l.mp4" -frames:v 1 "out/poster-$l.png"
  $PY -c "from PIL import Image; Image.open('out/poster-$l.png').convert('RGB').save('out/demo-$l.webp', 'WEBP', quality=86, method=6)"
  # the background music (music.py, made with the code-composer skill), quiet and faded to the cut's length
  D=$($PY -c "import subprocess as s;print(s.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0','out/demo-$l.mp4']).decode().strip())")
  F=$($PY -c "print(round($D-2.5,2))")
  $FF -v error -y -i "out/demo-$l.mp4" -i music-long.m4a -filter_complex "[1:a]atrim=0:$D,afade=t=in:d=0.4,afade=t=out:st=$F:d=2.5,loudnorm=I=-20:TP=-2:LRA=9[a]" \
    -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 128k -ar 48000 -movflags +faststart -shortest "out/demo-$l-a.mp4"
  mv "out/demo-$l-a.mp4" "out/demo-$l.mp4"
  cp "out/demo-$l.mp4" "out/demo-$l.webp" "$REPO/site/media/"
done
# the GIF: 20 frames a second all the way through, so the camera moves and the typing look smooth
$FF -v error -y -i master-en.mp4 -vf "fps=20,scale=860:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" "$REPO/docs/demo.gif"
ls -la "$REPO/site/media" "$REPO/docs/demo.gif"
