#!/usr/bin/env bash
# Negative controls for M9 slice 7 — notifications.
#
# Control 1 is the promise: remove `PaymentAttemptFailed` from the projection and G-5's decision —
# that a failed payment is *told* rather than published — goes back to being a sentence in a plan.
#
# Control 4 is the one that matters most operationally. It makes the projection write in a
# transaction of its own, which is the change somebody makes to "isolate" it — and which turns a
# notification failure into something that can leave financial state half-written. §17 `:1185`
# names that as one of M9's ten tests.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PROJECTION="services/backend/app/notifications/projection.py"
MIGRATION="services/backend/alembic/versions/20260902_0033_notifications.py"
BACKUP="$(mktemp -d)"

cp "$PROJECTION" "$BACKUP/projection.py"
cp "$MIGRATION" "$BACKUP/migration.py"

restore() {
  cp "$BACKUP/projection.py" "$PROJECTION"
  cp "$BACKUP/migration.py" "$MIGRATION"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_notification_projection.py
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2" target="$3"
  "$PYTHON" -m pytest -c services/backend/pyproject.toml "$target" -q > "$OUT" 2>&1

  if ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi
  if grep -qE '[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-54s' "$label"
    if grep -q "$expect" "$OUT"; then
      echo "(on: $expect)"
    else
      echo "*** WRONG ASSERTION *** expected: $expect"
      grep -E '^FAILED' "$OUT" | head -4
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

echo "== M9 slice 7 negative controls =="

# 1. Stop reading `PaymentAttemptFailed`. This is G-5's whole argument: the plan decided a failure
#    is notified rather than published *because* the event already existed and only needed a
#    reader. Without the reader the decision routes a case to nothing.
perl -0pi -e 's/    "PaymentAttemptFailed": TYPE_ATTEMPT_FAILED,\r?\n//' "$PROJECTION"
run "the failure event loses its consumer" "test_a_confirmed_failure_reaches_its_trader" "$LIVE"

# 2. Put the amount in the message. Every channel ADR-009 might choose delivers outside the
#    authenticated surface, so a figure here is a figure on somebody's lock screen.
perl -0pi -e 's/(        f"An attempt to pay request \{number\} did not succeed\.\{detail\})/$1 Amount: {payload.get(\x27amount_irr\x27, \x27\x27)}./' "$PROJECTION"
run "the message carries an amount" "test_a_notification_carries_no_amount" "$LIVE"

# 3. Key the message rather than the event — a fresh uuid per delivery. This is the realistic
#    mistake and the one the earlier version of this control missed: setting the key to `None`
#    left `_insert_once`'s read finding the previous row through `IS NULL`, so the property held
#    for the wrong reason and the control went NOT CAUGHT. A per-delivery key defeats both the
#    read and the index, which is what "the deduplication key is the *event* id" actually means.
perl -0pi -e 's/        deduplication_key=str\(event\.id\),/        deduplication_key=str(__import__("uuid").uuid4()),/' "$PROJECTION"
run "the key is per delivery, not per event" "test_the_same_event_twice_produces_one_message" "$LIVE"

# 4. Raise on an event type this consumer does not read. Eight of the eleven are normal traffic,
#    and dead-lettering them would report a fault every time a batch was approved.
perl -0pi -e 's/    if notification_type is None:\r?\n        return None/    if notification_type is None:\n        raise NotificationProjectionError("unknown event")/' "$PROJECTION"
run "an unread event type is a fault" "test_an_unhandled_event_type_is_not_a_failure" "$LIVE"

# 5. Swallow a malformed payload instead of failing it. The message is then dropped in silence,
#    which is the one failure mode a notification table cannot afford.
#
#    Returning `None` from `_request_for` was the earlier attempt and it went NOT CAUGHT for a
#    reason worth keeping: the caller then hit `None.trader_id`, the dispatcher caught the
#    `AttributeError`, and the event failed anyway. The property survived a sabotage that looked
#    like it should break it — the third meaning of NOT CAUGHT. Returning from `project` is where
#    a real "drop it quietly" would be written.
perl -0pi -e 's/    payload: dict\[str, Any\] = dict\(event\.payload or \{\}\)/    payload: dict[str, Any] = dict(event.payload or {})\n    if "payment_request_id" not in payload:\n        return None/' "$PROJECTION"
run "a malformed payload is dropped quietly" "test_an_event_naming_no_request_is_a_retryable" "$LIVE"

# 6. Grant UPDATE on the notifications table, **inside `upgrade`** so the statement actually runs.
#    The earlier version defined an uncalled `_grant` helper and went NOT CAUGHT, which was the
#    control asking the wrong question rather than the gate failing — and chasing that revealed
#    there was no gate at all: `test_batching_table_privileges.py`'s matrix is M6's and stops at
#    the batching tables. `test_the_runtime_role_cannot_change_a_notification` exists because of
#    this control.
perl -0pi -e 's/    # No GRANT\. See the module docstring/    bind = op.get_bind()\n    bind.execute(sa.text(\x27GRANT UPDATE ON public."notifications" TO PUBLIC\x27))\n\n    # No GRANT. See the module docstring/' "$MIGRATION"
run "the migration grants UPDATE" "test_the_runtime_role_cannot_change_a_notification" "$LIVE"

# 7. Read an event name the catalogue does not list. A rename there and not here stops producing
#    notifications silently, which is worse than failing.
perl -0pi -e 's/    "TraderResultCorrected": TYPE_RESULT_CORRECTED,/    "TraderResultCorrectedV2": TYPE_RESULT_CORRECTED,/' "$PROJECTION"
run "the projection reads an uncatalogued event" "test_every_handled_event_name_is_one_the" "$LIVE"

echo "== done =="
