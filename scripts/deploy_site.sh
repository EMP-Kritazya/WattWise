#!/bin/sh
# Builds the static site and deploys the site/ folder to Vercel production (project "wattwise").
# The site is deployed already built, so Vercel never sees the repo's backend or frontend app.
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
sh "$root/scripts/build_site.sh"
cd "$root/site"
[ -f .vercel/project.json ] || npx --yes vercel@65.2.0 link --yes --project wattwise
npx --yes vercel@65.2.0 deploy --prod --yes
