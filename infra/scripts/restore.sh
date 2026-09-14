#!/usr/bin/env bash
# Restore a backup bundle into a clean database and a clean storage tree.
#
# M12 slice 2, and the half that matters: §20.5's exit condition is a restore *drill* that
# reconciles, not a backup script that ran.
#
# ## It refuses to restore over a database that has rows in it
#
# **Deliberate, and the most important line in this file.** Restoring over a live database is how a
# drill destroys the thing it was meant to protect, and it is also how a drill proves nothing: rows
# that were already there reconcile with a manifest whether or not the dump contained them.
#
# `--force` exists because a real recovery *is* a restore over a broken database, and an operator at
# 3am should not have to edit a script. It is a separate word they have to type.
#
# ## The storage tree is replaced, not merged
#
# A merge would leave files from before the failure beside files from the backup, and the manifest
# would then reconcile against a tree nobody has ever had. The target directory must be empty or
# `--force`d, for the same reason as the database.
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
usage: restore.sh --bundle FILE --container NAME --database NAME --user NAME --storage DIR
                  [--passphrase-file FILE] [--force]

  --bundle           the .tar or .tar.gpg written by backup.sh
  --container        the running PostgreSQL container to restore into
  --database         the database to restore into. Must exist and must be EMPTY
                     unless --force is given.
  --user             PostgreSQL role to restore as
  --storage          where to unpack the stored files. Must be empty or absent
                     unless --force is given.
  --passphrase-file  decrypt with this passphrase, if the bundle is encrypted
  --force            restore over existing rows and existing files. This is what a
                     real recovery does and what a drill must never do.
EOF
}

bundle="" container="" database="" user="" storage="" passphrase_file="" force=0
while [ $# -gt 0 ]; do
    case "$1" in
        --bundle) bundle="$2"; shift 2 ;;
        --container) container="$2"; shift 2 ;;
        --database) database="$2"; shift 2 ;;
        --user) user="$2"; shift 2 ;;
        --storage) storage="$2"; shift 2 ;;
        --passphrase-file) passphrase_file="$2"; shift 2 ;;
        --force) force=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; usage; exit 2 ;;
    esac
done

for required in bundle container database user storage; do
    if [ -z "${!required}" ]; then
        printf -- '--%s is required\n' "$required" >&2
        usage
        exit 2
    fi
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

plain="$bundle"
case "$bundle" in
    *.gpg)
        if [ -z "$passphrase_file" ]; then
            printf 'the bundle is encrypted and no --passphrase-file was given\n' >&2
            exit 2
        fi
        plain="$work/bundle.tar"
        gpg --batch --yes --quiet --passphrase-file "$passphrase_file" \
            --output "$plain" --decrypt "$bundle"
        ;;
esac

tar --extract --file "$plain" --directory "$work"
for member in database.dump storage.tar.gz manifest.json; do
    if [ ! -f "$work/$member" ]; then
        printf 'the bundle has no %s; it was not written by backup.sh\n' "$member" >&2
        exit 1
    fi
done

# The emptiness check, and the reason it is a query rather than a file test: a database can exist,
# have a schema, and hold no rows — which is exactly the state a drill wants and a file test cannot
# tell from a database full of money.
rows=$(docker exec -i "$container" psql --username "$user" --dbname "$database" \
    --no-align --tuples-only --command \
    "SELECT COALESCE(SUM(n_live_tup), 0) FROM pg_stat_user_tables" 2>/dev/null || echo "0")
rows=${rows//[!0-9]/}
if [ "${rows:-0}" -gt 0 ] && [ "$force" -eq 0 ]; then
    printf 'refusing: %s already holds about %s rows.\n' "$database" "$rows" >&2
    printf 'A drill restores into a CLEAN database — rows that were already there reconcile\n' >&2
    printf 'with any manifest, which is how a drill passes while proving nothing.\n' >&2
    printf 'Pass --force only if this is a real recovery over a broken database.\n' >&2
    exit 1
fi

if [ -d "$storage" ] && [ -n "$(ls -A "$storage" 2>/dev/null)" ] && [ "$force" -eq 0 ]; then
    printf 'refusing: %s is not empty. See the database refusal above; the same applies.\n' \
        "$storage" >&2
    exit 1
fi

printf 'restoring the database...\n'
# `--clean --if-exists` so a `--force`d recovery replaces what is there rather than colliding with
# it. On the empty database a drill uses, both are no-ops.
docker exec -i "$container" pg_restore --username "$user" --dbname "$database" \
    --no-owner --clean --if-exists < "$work/database.dump"

printf 'restoring the storage tree...\n'
mkdir -p "$storage"
if [ "$force" -eq 1 ]; then
    find "$storage" -mindepth 1 -delete
fi
tar --extract --gzip --file "$work/storage.tar.gz" --directory "$storage"

cp "$work/manifest.json" "$storage/../restored-manifest-source.json" 2>/dev/null || true

printf '\nrestored. The bundle'"'"'s own manifest is at %s/manifest.json inside it.\n' "$work"
printf 'Reconcile before believing this worked:\n'
printf '  python3 infra/scripts/backup_manifest.py EXPECTED.json ACTUAL.json\n'
printf 'A restore that ran is not a restore that is correct.\n'
