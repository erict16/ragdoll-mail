#!/bin/sh
# Make the landing page's demo videos again, after the app's look changes:
#   sh docs/demo-video/make.sh
# Records the demo mailbox in headless Chromium (English and Chinese app), cuts each take with
# captions, cursor and gentle zoom (compose.py, needs Pillow), and writes:
#   site/media/demo-en.mp4, demo-zh.mp4  (H.264, 1920x1200) and their first frames as .webp posters
#   docs/demo.gif                         (the English cut, for the README)
# Needs node, ffmpeg, python3 with Pillow (set PY to that python), and Chromium (see CHROME in drv.mjs).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PY=${PY:-python3}
FF=${FF:-ffmpeg}
PORT=${PORT:-8795}
WORK=${WORK:-${TMPDIR:-/tmp}/ragdoll-demo-video}
mkdir -p "$WORK/out"
cd "$WORK"
export PORT

server() {   # a fresh demo mailbox for each take
  for p in $(lsof -ti tcp:"$PORT" -sTCP:LISTEN); do kill "$p"; done
  sleep 1
  (cd "$REPO" && RAGDOLL_APP_TOKEN=devtok python3 ragdoll_app.py --demo --browser --no-open --port "$PORT" > "$WORK/server.log" 2>&1 &)
  for i in $(seq 1 40); do sleep 0.5; curl -s -o /dev/null "http://127.0.0.1:$PORT/" && return 0; done
  echo "the demo server did not start"; exit 1
}

# SKIP_RECORD=1 cuts the takes already in $WORK again (after a change to compose.py)
[ -n "$SKIP_RECORD" ] || for l in en zh; do
  rm -rf "take-$l"
  server
  node "$HERE/record.mjs" $l "take-$l" 2.5
  node "$HERE/assets.mjs" $l "assets-$l"
done
[ -n "$SKIP_RECORD" ] || for p in $(lsof -ti tcp:"$PORT" -sTCP:LISTEN); do kill "$p"; done

for l in en zh; do
  $PY "$HERE/compose.py" $l "take-$l" "assets-$l" "master-$l.mp4" | tail -1
  $FF -v error -y -i "master-$l.mp4" -c:v libx264 -preset veryslow -crf 22 -tune animation -pix_fmt yuv420p \
    -profile:v high -level 5.1 -movflags +faststart -an -color_primaries bt709 -color_trc bt709 -colorspace bt709 "out/demo-$l.mp4"
  $FF -v error -y -i "out/demo-$l.mp4" -frames:v 1 "out/poster-$l.png"
  $PY -c "from PIL import Image; Image.open('out/poster-$l.png').convert('RGB').save('out/demo-$l.webp', 'WEBP', quality=86, method=6)"
  cp "out/demo-$l.mp4" "out/demo-$l.webp" "$REPO/site/media/"
done
# the GIF: 10 frames a second, 5 while the camera moves (those frames change everywhere and cost the most)
MV=$($PY "$HERE/compose.py" en take-en assets-en x --moving)
$FF -v error -y -i master-en.mp4 -vf "fps=10,select='if(gt(${MV},0),not(mod(n,2)),1)',scale=1000:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=full[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" -fps_mode vfr "$REPO/docs/demo.gif"
ls -la "$REPO/site/media" "$REPO/docs/demo.gif"
