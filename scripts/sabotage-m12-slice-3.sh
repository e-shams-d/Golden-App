#!/usr/bin/env bash
# Negative controls for M12 slice 3 — the production stack.
#
# **A production configuration is checked by nobody until the day it matters.** Every control here
# produces a stack that starts, serves both audiences, and is worse in one specific way. Two of them
# reproduce defects this slice's own first draft had.
#
# `nginx -t` runs as control 0's second half, because a configuration that does not parse is not a
# weaker deployment — it is no deployment, and the gate would then be passing on a file nothing
# could load.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
GATE=tests/backend/test_production_stack.py
PROD_COMPOSE=infra/compose/compose.prod.yml
PROD_NGINX=infra/nginx/deployment/production.conf
ACCESS=infra/nginx/deployment/admin-access.conf

WORK=$(mktemp -d)
cp "$PROD_COMPOSE" "$WORK/compose.yml"
cp "$PROD_NGINX" "$WORK/production.conf"
cp "$ACCESS" "$WORK/admin-access.conf"

restore_files() {
  cp "$WORK/compose.yml" "$PROD_COMPOSE"
  cp "$WORK/production.conf" "$PROD_NGINX"
  cp "$WORK/admin-access.conf" "$ACCESS"
  rm -f infra/nginx/conf.d/admin-access.conf
}
trap restore_files EXIT

nginx_parses() {
  local tls
  tls=$(mktemp -d)
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
      -keyout "$tls/privkey.pem" -out "$tls/fullchain.pem" -subj "/CN=admin.localhost" \
      >/dev/null 2>&1
  docker run --rm \
      --add-host trader-pwa:127.0.0.1 --add-host admin-web:127.0.0.1 --add-host backend:127.0.0.1 \
      -v "$PWD/infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
      -v "$PWD/infra/nginx/deployment/production.conf:/etc/nginx/conf.d/local.conf:ro" \
      -v "$PWD/infra/nginx/deployment/admin-access.conf:/etc/nginx/deployment/admin-access.conf:ro" \
      -v "$PWD/infra/nginx/deployment/trader-host.conf:/etc/nginx/deployment/trader-host.conf:ro" \
      -v "$PWD/infra/nginx/deployment/admin-host.conf:/etc/nginx/deployment/admin-host.conf:ro" \
      -v "$tls:/etc/nginx/tls:ro" \
      nginx:1.30.4-alpine3.24 nginx -t >/dev/null 2>&1
  local outcome=$?
  rm -rf "$tls"
  return $outcome
}

run_suite() {
  $PY -m pytest -c services/backend/pyproject.toml "$GATE" -q --no-header >"$WORK/out.txt" 2>&1
}

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
if run_suite && nginx_parses; then
  echo "clean: green, and the configuration parses"
else
  echo "clean: NOT GREEN — stop."
  tail -20 "$WORK/out.txt"
  exit 1
fi

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if run_suite; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT"
    grep -E '^FAILED|AssertionError' "$WORK/out.txt" | head -2
  fi
  restore_files
}

# 1. **An image goes back to a tag.** The stack runs, from whatever bytes that tag points at today —
#    which need not be the bytes CI's container scan examined.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/compose/compose.prod.yml")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "image: redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99",
    "image: redis:7.4.9-alpine3.21",
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "1. an image is named by tag rather than digest"

# 2. One image is pinned and another is simply dropped from the overlay. Every image the file
#    *names* is still a digest, so a check that only looked at what is there would pass — while the
#    dropped service ships from a moving tag.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/compose/compose.prod.yml")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "  redis:\n    # redis:7.4.9-alpine3.21 as of 2026-09-14.\n"
    "    image: redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99\n\n",
    "",
)
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. a third-party image is left out of the overlay entirely"

# 3. **HSTS on a stack with no TLS.** The local compose gains `SECURITY_HSTS_ENABLED`, and a browser
#    that loads the laptop stack once refuses to load it again — for a year.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/compose/compose.local.yml")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "  backend:\n",
    '  backend:\n    environment:\n      SECURITY_HSTS_ENABLED: "true"\n',
    1,
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. HSTS is enabled on the plaintext local stack"
git checkout -- infra/compose/compose.local.yml

# 4. **The production configuration loses `/files/`.** Both audiences still load, sign in and work.
#    Every receipt and every bank result 404s — on the one configuration no other test in this
#    repository runs against.
$PY - <<'EOF'
import pathlib
import re
p = pathlib.Path("infra/nginx/deployment/production.conf")
s = p.read_text(encoding="utf-8")
before = s
s = re.sub(r"    location \^~ /files/ \{.*?\n    \}\n\n", "", s, count=1, flags=re.S)
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. the production configuration stops serving /files/"

# 5. **The admin access rule is applied to the trader block too.** This is the defect the
#    `deployment/` directory exists to prevent, reproduced deliberately: the day somebody restricts
#    the panel, every trader is locked out with it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/nginx/deployment/production.conf")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    include /etc/nginx/deployment/trader-host.conf;",
    "    include /etc/nginx/deployment/trader-host.conf;\n"
    "    include /etc/nginx/deployment/admin-access.conf;",
)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. the admin access rule is applied to the trader audience as well"

# 6. A plaintext listener is added "to redirect http:// to https://". It looks like a courtesy and
#    is interceptable by anyone on the path — the first visit is the whole of what HSTS cannot
#    protect, and a redirect is exactly what an attacker rewrites.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/nginx/deployment/production.conf")
s = p.read_text(encoding="utf-8")
before = s
s += "\nserver {\n    listen 8080;\n    server_name _;\n    return 301 https://$host$request_uri;\n}\n"
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "6. a plaintext listener is added to redirect to https"

# 7. **`admin-access.conf` moves back into `conf.d/`**, where the wildcard include sweeps it up at
#    http level. Today it says `allow all`, so nothing changes — and the day it is restricted, it
#    restricts everybody. The damage is deferred, which is why a test rather than a review has to
#    catch it.
cp "$ACCESS" infra/nginx/conf.d/admin-access.conf
probe "7. the admin access rule returns to the auto-included directory"

# 8. The file stops saying what the open decision costs. `allow all;` remains, correct and
#    unexplained — indistinguishable from nobody having thought about it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/nginx/deployment/admin-access.conf")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "# The panel where payments are approved is reachable from any address on the internet. The only\n"
    "# thing between an attacker and a payment approval is a username and a password — there is no\n"
    "# second layer. The platform's own controls still hold: rate limiting, lockout, dual control on the\n"
    "# correction path, and an audit trail. None of them is a network boundary.\n",
    "# Open for now.\n",
)
assert s != before, "control 8 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "8. the open decision stops saying what it costs"

echo
echo "=== restored ==="
git status --short "$PROD_COMPOSE" "$PROD_NGINX" "$ACCESS" infra/compose/compose.local.yml infra/nginx/conf.d/
