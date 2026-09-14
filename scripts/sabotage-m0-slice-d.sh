#!/usr/bin/env bash
# Negative controls for M0 slice D — statement import, and the per-version mapping.
#
# The interesting controls here are 2 and 3. This slice began as "seed one mapping row and point the
# route at its id", which passes every test that existed: the fixture worlds each have exactly one
# active version, so a constant and a derivation are indistinguishable in them. The defect only
# appears after an ordinary activation, which no test performed. Controls 2 and 3 reproduce that
# shape deliberately — a system that is **wrong but works** — and a control that merely broke the
# import would prove nothing about it.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@172.17.0.2:5432/postgres}"

EXPECTED=services/backend/app/statements/expected_file.py
RESOLUTION=services/backend/app/bankconfig/resolution.py
COMMAND=services/backend/app/commands/bank_statement.py
LIST=apps/admin-web/app/bank-statements/page.tsx
DETAIL=apps/admin-web/app/bank-statements/\[statementId\]/page.tsx
DATA=apps/admin-web/src/bank-statements.ts

BACKUP=$(mktemp -d)
cp "$EXPECTED" "$BACKUP/expected_file.py"
cp "$RESOLUTION" "$BACKUP/resolution.py"
cp "$COMMAND" "$BACKUP/bank_statement.py"
cp "$LIST" "$BACKUP/list.tsx"
cp "$DETAIL" "$BACKUP/detail.tsx"
cp "$DATA" "$BACKUP/data.ts"

restore() {
  cp "$BACKUP/expected_file.py" "$EXPECTED"
  cp "$BACKUP/resolution.py" "$RESOLUTION"
  cp "$BACKUP/bank_statement.py" "$COMMAND"
  cp "$BACKUP/list.tsx" "$LIST"
  cp "$BACKUP/detail.tsx" "$DETAIL"
  cp "$BACKUP/data.ts" "$DATA"
}
trap restore EXIT

# `test_bank_configuration.py` is here for ADR-007: its `TestNothingIsSeeded` is what refused the
# first draft of this slice, which planted the mapping in a migration. A control run without it
# would not notice a revision being added back.
SUITE="tests/backend \
tests/integration/test_bank_statement_import.py \
tests/integration/test_bank_version_resolution.py \
tests/integration/test_bank_configuration.py"

run_suite() {
  # Both halves, because this slice's claims are split across them: the backend decides which
  # mapping is used and the screens decide what an operator is asked. A control that ran only
  # pytest would report NOT CAUGHT for every frontend property.
  # shellcheck disable=SC2086
  $PY -m pytest -c services/backend/pyproject.toml $SUITE -q --no-header >"$BACKUP/out.txt" 2>&1
  local backend=$?
  (cd apps/admin-web && pnpm vitest run test/bank-statements.test.ts >>"$BACKUP/out.txt" 2>&1)
  local frontend=$?
  [ $backend -eq 0 ] && [ $frontend -eq 0 ]
}

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
if run_suite; then
  echo "clean: green"
else
  echo "clean: NOT GREEN — stop. Every result below is meaningless."
  tail -20 "$BACKUP/out.txt"
  exit 1
fi

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if run_suite; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -cE '^(FAILED|.*✗|.* FAIL )' "$BACKUP/out.txt") failing"
    grep -E '^FAILED' "$BACKUP/out.txt" | head -4
    grep -E 'Tests .*failed' "$BACKUP/out.txt" | head -2
  fi
  restore
}

# 1. The parser and the mapping disagree: a field name that produces nothing. The import would fail
#    at configuration time, after a person has uploaded a statement and pressed the button, and the
#    message would name a field rather than this file.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/statements/expected_file.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace('"field": "tracking_number"', '"field": "traceing_number"')
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "1. the expected mapping names a field the parser does not produce"

# 2. **The defect this slice's design exists to prevent.** Activation stops seeding the mapping.
#    Nothing else changes: the migration still seeds, the command still resolves by version, every
#    existing bank still imports. It breaks only for a version activated after deployment — a
#    working system that is wrong.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/bankconfig/resolution.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    _give_this_version_the_expected_statement_mapping(uow, version)\n",
    "",
)
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. activating a version no longer gives it a mapping"

# 3. The same defect from the other side, and the shape this slice was **originally written in**:
#    the command resolves the mapping from a constant rather than from the statement's version. In
#    a world with one active version this is indistinguishable from correct.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/commands/bank_statement.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "        .where(BankMapping.bank_profile_version_id == statement.bank_profile_version_id)\n",
    "",
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. the command takes any active statement mapping, not the statement's own"

# 4. The mapping is written as a draft rather than active. It exists, an operator inspecting the
#    table would see it, and every import refuses it as unapproved — which reads identically to no
#    mapping at all while looking like the opposite.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/bankconfig/resolution.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("            status=MAPPING_ACTIVE,\n", '            status="draft",\n')
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. the mapping is written as a draft and refused as unapproved"

# 5. `config_hash` becomes a per-row random value instead of a digest of what it describes. Every
#    import still works. What breaks is the column's purpose: two deployments on the same release
#    disagree, and `UNIQUE(bank_profile_version_id, file_type, config_hash)` stops being able to
#    refuse the same shape inserted twice. The first draft of this slice computed its own hash
#    locally, which is how this mistake actually arises.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/bankconfig/resolution.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "            config_hash=EXPECTED_CONFIG_HASH,\n",
    '            config_hash=__import__("hashlib").sha256(str(version.id).encode()).hexdigest(),\n',
)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. config_hash is per-row rather than a digest of the mapping"

# 6. The detail screen collapses "not parsed yet" into a number. A queued run reports zero rows, and
#    an operator reads that as a statement the bank sent empty. Renders perfectly.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/bank-statements/[statementId]/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    """                        {run.row_count === null ? (
                          t("statement.rowCountPending")
                        ) : (
                          <BidiText>{String(run.row_count)}</BidiText>
                        )}""",
    """                        <BidiText>{String(run.row_count ?? 0)}</BidiText>""",
)
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "6. a queued run reports zero rows instead of 'not read yet'"

# 7. The data module sends a mapping id it invented. The screen works today, because the id is right
#    today — and goes wrong the first time a version is activated, silently aiming a run at a
#    retired version's mapping.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/src/bank-statements.ts")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    body: {},\n",
    '    body: { bank_mapping_id: "0192d4c7-8f3a-7c21-9d55-5e2f1a6b4c30" },\n',
)
assert s != before, "control 7 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "7. the screen names the mapping it thinks the server will use"

# 8. The list screen accepts half a date range. The command refuses it and the CHECK refuses it, so
#    nothing is corrupted — the operator simply gets a 400 for a field the form said was optional.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/bank-statements/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("      !rangeIsWhole\n", "      false\n")
assert s != before, "control 8 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "8. the form submits one end of a date range"

echo
echo "=== restored ==="
git status --short "$EXPECTED" "$RESOLUTION" "$COMMAND" "$LIST" "$DETAIL" "$DATA"
