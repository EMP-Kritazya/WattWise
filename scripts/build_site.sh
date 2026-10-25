#!/bin/sh
# Builds the static site in site/: the 3D demo (frontend showcase build → site/demo) and the pitch deck (→ site/pitch).
# site/demo and site/pitch are generated; their sources are frontend/src/showcase and pitch/.
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$root/frontend" && npx vite build -c vite.showcase.config.ts)
rm -rf "$root/site/pitch" && mkdir -p "$root/site/pitch"
cp "$root/pitch/WattWise-pitch.html" "$root/site/pitch/index.html"
cp "$root/pitch/WattWise-pitch.pdf" "$root/site/pitch/"
[ -f "$root/pitch/demo-still.png" ] && cp "$root/pitch/demo-still.png" "$root/site/pitch/"
echo "site ready"
