#!/usr/bin/env bash
# Negative controls for M11 slice 1 — the notification API M9 left unreachable.
#
# The scope of this slice is a single column, `notifications.recipient_actor_id`, and every control
# below is a way of losing it. Controls 1, 2, 3, 4 and 6 each remove one half of the recipient
# predicate from a different code path, because "the query is scoped" is five separate claims and
# the ones nobody writes a test for are the ones that break.
#
# Control 0 runs the suite CLEAN FIRST. A test that fails against everything catches everything,
# and "CAUGHT" from a suite that was already red is not evidence of anything.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

ROUTER=services/backend/app/api/v1/notifications.py
READING=services/backend/app/notifications/reading.py
COMMAND=services/backend/app/commands/notification_read.py
MIGRATION=services/backend/alembic/versions/20260913_0044_notifications_read.py

BACKUP=$(mktemp -d)
cp "$ROUTER" "$BACKUP/router.py"
cp "$READING" "$BACKUP/reading.py"
cp "$COMMAND" "$BACKUP/command.py"
cp "$MIGRATION" "$BACKUP/migration.py"

restore() {
  cp "$BACKUP/router.py" "$ROUTER"
  cp "$BACKUP/reading.py" "$READING"
  cp "$BACKUP/command.py" "$COMMAND"
  cp "$BACKUP/migration.py" "$MIGRATION"
}
trap restore EXIT

SUITE="tests/integration/test_notification_reading.py tests/integration/test_notification_projection.py"

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
$PY -m pytest $SUITE tests/backend -q --no-header 2>&1 | tail -3

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if $PY -m pytest $SUITE tests/backend -q --no-header >"$BACKUP/out.txt" 2>&1; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -c '^FAILED' "$BACKUP/out.txt") failing"
    grep '^FAILED' "$BACKUP/out.txt" | head -4
  fi
  restore
}

# 1. The scope is dropped from the list entirely. SEC-NOTIFY-001's whole subject.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/notifications/reading.py")
s = p.read_text()
s = s.replace(
    """    statement = select(Notification).where(
        Notification.recipient_actor_type == recipient_actor_type,
        Notification.recipient_actor_id == recipient_actor_id,
    )""",
    "    statement = select(Notification)",
)
p.write_text(s)
EOF
probe "1. the list returns everybody's notifications"

# 2. The audience half is dropped and the id half kept. The interesting one: every scope test that
#    varies recipient *and* audience together passes against this, because two different people's
#    ids differ anyway. Only the test that holds the id fixed can see it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/notifications/reading.py")
s = p.read_text()
s = s.replace(
    "        Notification.recipient_actor_type == recipient_actor_type,\n"
    "        Notification.recipient_actor_id == recipient_actor_id,\n",
    "        Notification.recipient_actor_id == recipient_actor_id,\n",
)
p.write_text(s)
EOF
probe "2. the list ignores which audience the row was addressed to"

# 3. mark-all-read marks the whole table. SVC-NOTIFY-001's reason for existing: with one recipient
#    seeded, this sabotage is indistinguishable from correct behaviour.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/commands/notification_read.py")
s = p.read_text()
s = s.replace(
    """        .where(
            Notification.recipient_actor_type == command.recipient_actor_type,
            Notification.recipient_actor_id == command.recipient_actor_id,
            Notification.status == NOTIFICATION_UNREAD,
        )""",
    "        .where(Notification.status == NOTIFICATION_UNREAD)",
)
p.write_text(s)
EOF
probe "3. mark-all-read marks every recipient's notifications"

# 4. mark-read accepts somebody else's notification.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/commands/notification_read.py")
s = p.read_text()
s = s.replace(
    """    if (
        notification.recipient_actor_type != command.recipient_actor_type
        or notification.recipient_actor_id != command.recipient_actor_id
    ):
        raise NotFoundError()
""",
    "",
)
p.write_text(s)
EOF
probe "4. mark-read edits a notification addressed to somebody else"

# 5. The unique tiebreak is moved onto the wrong column. `ListSpec` refuses a spec with no unique
#    sort at all, so the sabotage has to *lie* about which one is unique rather than delete it.
#    Invisible unless rows share a timestamp, which is why API-NOTIFY-001 seeds six with one.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/notifications/reading.py")
s = p.read_text()
s = s.replace('SortField("id", Notification.id, unique=True),', 'SortField("id", Notification.id),')
s = s.replace(
    'SortField("created_at", Notification.created_at),',
    'SortField("created_at", Notification.created_at, unique=True),',
)
p.write_text(s)
EOF
probe "5. created_at is claimed unique, so the sort has no real tiebreak"

# 6. The unread count is computed over the whole table. A count is a disclosure: how much is
#    happening to a business is information about that business.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/commands/notification_read.py")
s = p.read_text()
s = s.replace(
    """        .where(
            Notification.recipient_actor_type == recipient_actor_type,
            Notification.recipient_actor_id == recipient_actor_id,
            Notification.status == NOTIFICATION_UNREAD,
        )""",
    "        .where(Notification.status == NOTIFICATION_UNREAD)",
)
p.write_text(s)
EOF
probe "6. the unread count leaks how much is happening to other people"

# 7. The migration grants UPDATE on every column instead of two. This is the control that went
#    NOT CAUGHT in M9 and produced `test_the_runtime_role_cannot_change_a_notification`; slice 1
#    narrowed that test rather than deleting it, so it must still catch this.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/alembic/versions/20260913_0044_notifications_read.py")
s = p.read_text()
s = s.replace(
    'GRANT UPDATE ({columns}) ON public."notifications"',
    'GRANT UPDATE ON public."notifications"',
)
p.write_text(s)
EOF
probe "7. the runtime may rewrite what a notification says"

# 8. mark-read moves `read_at` on every call, losing when it was first read.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/commands/notification_read.py")
s = p.read_text()
s = s.replace(
    """    if notification.status == NOTIFICATION_UNREAD:
        notification.status = NOTIFICATION_READ
        notification.read_at = now
        uow.flush()""",
    """    notification.status = NOTIFICATION_READ
    notification.read_at = now
    uow.flush()""",
)
p.write_text(s)
EOF
probe "8. a retry overwrites the moment the message was first read"

# 9. An unknown sort is ignored instead of refused — a different page than the caller asked for,
#    returned without saying so.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/notifications.py")
s = p.read_text()
s = s.replace("            sort=sort,\n", "            sort=None,\n")
p.write_text(s)
EOF
probe "9. the sort a caller asked for is silently ignored"

# 10. The response carries the recipient id back, giving a client a value to compare against
#     somebody else's.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/notifications.py")
s = p.read_text()
s = s.replace(
    "    id: uuid.UUID\n    notification_type: str",
    "    id: uuid.UUID\n    recipient_actor_id: uuid.UUID\n    notification_type: str",
)
s = s.replace(
    "        id=notification.id,\n",
    "        id=notification.id,\n        recipient_actor_id=notification.recipient_actor_id,\n",
)
p.write_text(s)
EOF
probe "10. the response discloses the recipient's internal id"

echo
echo "=== restored ==="
git status --short
