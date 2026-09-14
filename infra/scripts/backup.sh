#!/usr/bin/env bash
# Take a backup: the database, the stored files, and a manifest of what both contained.
#
# M12 slice 2. §20.4 asks for backup automation, an off-server encrypted copy and a consistency
# manifest; §20.5 asks for a restore drill that reconciles. This produces what that drill restores.
#
# ## Three things in one bundle, and why none of them can be left out
#
# The **database** holds what the platform believes. The **storage tree** holds the evidence those
# beliefs are about — a receipt, a bank result, a cropped segment. A database restored without its
# files is a system that can name evidence it cannot show, and `file_objects.sha256_hash` would
# then be a checksum of something that is gone.
#
# The **manifest** is taken from the same database at the same moment as the dump, so it records
# what the dump saw rather than what the database looked like afterwards.
#
# ## The PostgreSQL tools come from a pinned image, over the network
#
# There is no `pg_dump` on this host and there should not be: it must match the server's major
# version, and a host that upgraded independently would produce a dump the server cannot read back.
# A throwaway container fixes the version at `postgres:16.14-alpine3.24`.
#
# **Over the network rather than `docker exec` into the database's own container.** The first
# version of this script took a container name, which is an *environment* fact: it worked locally
# and failed in CI with `No such container`, because GitHub Actions names service containers
# differently. A URL works wherever the application's own URL works — and it is what a real backup
# host does, since nothing in a deployment has a shell inside the database container.
#
# ## Encryption is gpg symmetric, and that is a deployment constraint rather than a preference
#
# No external key service is reachable, so the passphrase comes from a file the operator controls —
# the same shape as the owner's 2026-09-13 decision for production secrets. `--symmetric` with
# AES256 needs nothing but gpg, which is present on every Debian host this will run on.
#
# **The passphrase is never an argument.** A command line is visible in `ps` to every user on the
# box, and a backup passphrase in shell history is a backup anybody can read.
set -euo pipefail

PG_IMAGE="postgres:16.14-alpine3.24"

usage() {
    cat >&2 <<'EOF'
usage: backup.sh --database-url URL --storage DIR --out DIR [--passphrase-file FILE]

  --database-url     postgresql://user:password@host:port/database
  --storage          the local storage root, as LOCAL_STORAGE_ROOT gives it
  --out              directory to write the bundle into
  --passphrase-file  encrypt the bundle with this passphrase. Omitted, the bundle is
                     written unencrypted and the script says so loudly — which is
                     correct for a drill and never correct for a real backup.
EOF
}

database_url="" storage="" out="" passphrase_file=""
while [ $# -gt 0 ]; do
    case "$1" in
        --database-url) database_url="$2"; shift 2 ;;
        --storage) storage="$2"; shift 2 ;;
        --out) out="$2"; shift 2 ;;
        --passphrase-file) passphrase_file="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; usage; exit 2 ;;
    esac
done

for required in database_url storage out; do
    if [ -z "${!required}" ]; then
        printf -- '--%s is required\n' "${required//_/-}" >&2
        usage
        exit 2
    fi
done

if [ ! -d "$storage" ]; then
    printf 'storage root %s does not exist; refusing to take a backup that would restore an empty tree\n' \
        "$storage" >&2
    exit 1
fi

mkdir -p "$out"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

printf 'dumping the database...\n'
# Custom format: `pg_restore` can then create schema and data separately, and a restore into a
# *clean* database is what the drill needs. `--network host` so the URL means the same thing inside
# the container as it does here.
docker run --rm --network host "$PG_IMAGE" \
    pg_dump "$database_url" --format=custom --no-owner > "$work/database.dump"

printf 'copying the storage tree...\n'
tar --create --gzip --file "$work/storage.tar.gz" --directory "$storage" .

printf 'writing the manifest...\n'
# Built by the Python module rather than by this script: it needs a stable digest over rows in a
# defined order, and shelling out for that would put the ordering rules in two places.
#
# **`NetworkPsql` is in the module, not in this heredoc.** An earlier version lived here and had a
# parsing bug no test could reach, because the code an operator runs in production was code no test
# imported.
here=$(cd "$(dirname "$0")" && pwd)
python3 - "$here" "$database_url" "$storage" "$work/manifest.json" <<'PYTHON'
import json
import sys
from pathlib import Path

here, database_url, storage, out = sys.argv[1:5]
sys.path.insert(0, here)
import backup_manifest  # noqa: E402

manifest = backup_manifest.build(backup_manifest.NetworkPsql(database_url), Path(storage))
Path(out).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
print(f"  {sum(t['rows'] for t in manifest['tables'].values())} rows, "
      f"{manifest['storage']['files']} stored files")
PYTHON

bundle="$out/golden-backup-$stamp.tar"
tar --create --file "$bundle" --directory "$work" database.dump storage.tar.gz manifest.json
sha256sum "$bundle" | awk '{print $1}' > "$bundle.sha256"

if [ -n "$passphrase_file" ]; then
    if [ ! -r "$passphrase_file" ]; then
        printf 'passphrase file %s is not readable\n' "$passphrase_file" >&2
        exit 1
    fi
    gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase-file "$passphrase_file" --output "$bundle.gpg" "$bundle"
    rm -f "$bundle"
    printf 'wrote %s.gpg\n' "$bundle"
    printf 'digest of the plaintext bundle is in %s.sha256 — keep it with the copy, not inside it\n' \
        "$bundle"
else
    printf '\n*** UNENCRYPTED ***: no --passphrase-file was given, so %s is readable by anyone\n' \
        "$bundle" >&2
    printf '*** correct for a drill, never correct for a backup that leaves this machine ***\n\n' >&2
fi

printf 'done. Copy the bundle off this server — a backup on the machine it protects is not one.\n'
