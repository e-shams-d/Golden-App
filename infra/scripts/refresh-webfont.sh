#!/usr/bin/env sh
# Refresh the vendored Persian webfont from its upstream package.
#
# The font is committed under each app's `public/fonts/`, not installed at build time, and
# that is deliberate rather than lazy.
#
# **Self-hosted, because the deployment country decides it.** This platform runs only inside
# Iran, where Google Fonts and the other font hosts are unreachable; a stylesheet that waits
# on one renders in the fallback for as long as the request takes to fail. The applications'
# own security headers would refuse the request in any case.
#
# **Committed rather than a dependency, because the container build has no registry.** It was
# briefly a devDependency of `@gold/config`, and the image build failed on
# `pnpm install --frozen-lockfile`: the host reaches the npm registry through a proxy the
# Docker build does not inherit, and this machine's mirrors are geo-blocked. A typeface is a
# static asset that changes about once a year — making every image build depend on a network
# fetch to obtain it trades a 111KB file for a recurring outage.
#
# So this script exists for the once-a-year case, run by a person who has network, and the
# rest of the time nothing needs it. Provenance is in the file it writes and in this comment,
# rather than in a lockfile entry nobody reads.
#
# Vazirmatn is SIL Open Font License 1.1; the licence is copied beside the font, which that
# licence requires.
set -eu

VERSION="${1:-33.0.3}"
REPOSITORY_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$REPOSITORY_ROOT"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

printf 'fetching vazirmatn@%s\n' "$VERSION"
# `npm pack` rather than adding a dependency: it downloads the tarball and leaves the
# workspace untouched, so nothing about the build graph changes.
( cd "$WORK" && npm pack "vazirmatn@${VERSION}" >/dev/null && tar -xzf ./*.tgz )

FONT="$WORK/package/fonts/webfonts/Vazirmatn[wght].woff2"
[ -f "$FONT" ] || { printf '%s\n' "the variable font is not where it used to be in this package" >&2; exit 1; }

for app in admin-web trader-pwa; do
    mkdir -p "apps/$app/public/fonts"
    # Renamed: the bracket in the upstream filename would have to be percent-encoded in every
    # `url()`, and a font that loads only when somebody remembers to escape it is a font that
    # silently stops loading.
    cp "$FONT" "apps/$app/public/fonts/Vazirmatn-Variable.woff2"
    cp "$WORK/package/OFL.txt" "apps/$app/public/fonts/Vazirmatn-OFL.txt"
    printf '  apps/%s/public/fonts/Vazirmatn-Variable.woff2\n' "$app"
done

printf 'done. Commit the two font files and their licence together.\n'
