#!/usr/bin/env bash
# Negative controls for M9 slice 6 — the trader surface.
#
# Control 1 is the one that matters, and it is the *plausible* mistake: a dispute that marks the
# attempt unpaid. That is the intuitive response to "the money did not arrive" and it is exactly
# what doc 05 forbids — "does not automatically reverse bank facts". A test reading only the
# request's status would pass against it, which is why the live test compares whole rows.
#
# Control 3 is the security one: turning the second trader's 404 into a 403 tells them the
# publication exists.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/trader_result.py"
ROUTES="services/backend/app/api/v1/trader_publications.py"
TASKS="services/backend/app/commands/manual_review_task.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$ROUTES" "$BACKUP/routes.py"
cp "$TASKS" "$BACKUP/tasks.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/routes.py" "$ROUTES"
  cp "$BACKUP/tasks.py" "$TASKS"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_trader_publications.py
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

echo "== M9 slice 6 negative controls =="

# 1. Make the dispute helpful: mark the attempt unpaid, which is what "the money did not arrive"
#    intuitively means and what doc 05 `:1942` forbids in as many words.
perl -0pi -e 's/(    task = _open_a_dispute_task\()/    session.execute(\n        __import__("sqlalchemy").text(\n            "UPDATE payment_attempts SET status = \x27failed\x27 WHERE payment_request_id = :r"\n        ),\n        {"r": request.id},\n    )\n$1/' "$COMMANDS"
run "a dispute reverses the bank fact" "test_a_dispute_reverses_no_bank_fact" "$LIVE"

# 2. Let acknowledgement touch the publication. The safe-looking action is where a convenience
#    write gets added, which is why it gets the same read-back as the dispute.
perl -0pi -e 's/(        values=\{"status": REQUEST_ACKNOWLEDGED, "trader_acknowledged_at": now\},)/$1\n    )\n    session.execute(\n        __import__("sqlalchemy").text(\n            "UPDATE payment_result_publications SET status = \x27revoked\x27 WHERE id = :p"\n        ),\n        {"p": publication.id},/' "$COMMANDS"
run "acknowledging edits the publication" "test_a_trader_acknowledges_and_nothing_financial" "$LIVE"

# 3. Answer 403 instead of 404 for somebody else's request. An authorisation error over a
#    guessable identifier is an enumeration oracle.
perl -0pi -e 's/    return require_owned\(request, request\.trader_id if request else None, actor\)/    if request is None or not actor.owns(request.trader_id):\n        raise ForbiddenError()\n    return request/' "$ROUTES"
run "not-mine answers 403" "test_another_trader_gets_404_and_not_403" "$LIVE"

# 4. Point the dispute task at the attempt instead of the publication. Plausible — slice 3 does
#    exactly that for an overpayment — and it loses the publication version §17 `:1185` requires.
perl -0pi -e 's/            entity_type=ENTITY_PAYMENT_PUBLICATION,\r?\n            entity_id=publication\.id,\r?\n            entity_record_version=publication\.publication_version,/            entity_type="payment_attempt",\n            entity_id=request.id,\n            entity_record_version=None,/' "$COMMANDS"
run "the task loses the publication version" "test_a_dispute_opens_a_task_naming_the_exact" "$LIVE"

# 5. Forget that `resolve_task` recomputes the version. Removing the publication branch from
#     `_subject_version` erases §17's reference at the moment somebody acts on the dispute.
perl -0pi -e 's/    if task\.entity_type == ENTITY_PAYMENT_PUBLICATION:\r?\n        publication = session\.get\(PaymentResultPublication, task\.entity_id\)\r?\n        return publication\.publication_version if publication else None\r?\n//' "$TASKS"
run "resolving erases the disputed version" "test_resolving_a_dispute_keeps_the_publication" "$LIVE"

# 6. Let a trader respond before anything is published. Document 06 draws both arrows from
#    `result_published`, and there is nothing to agree with before one exists.
perl -0pi -e 's/    if request\.status not in RESPONDABLE_FROM:/    if False:/' "$COMMANDS"
run "a trader responds to nothing" "test_a_trader_cannot_respond_before_a_result" "$LIVE"

# 7. Ignore the caller's expected version. A correction replacing the result while the trader
#    reads it would then be acknowledged anyway.
perl -0pi -e 's/        expected_version=command\.expected_record_version,/        expected_version=request.record_version,/g' "$COMMANDS"
run "the expected version is ignored" "test_a_stale_if_match_refuses_a_trader_response" "$LIVE"

# 8. Enqueue an outbox event for a trader response. The catalogue lists none, and an event nobody
#    consumes is a second delivery path for one fact.
perl -0pi -e 's/(    _audit\(\r?\n        session,\r?\n        policy,\r?\n        names=DISPUTE_PUBLICATION,)/    from app.audit.outbox import OutboxMessage, OutboxWriter\n\n    OutboxWriter(session, policy).enqueue(\n        OutboxMessage(\n            aggregate_type="payment_request",\n            aggregate_id=request.id,\n            aggregate_version=request.record_version,\n            event_type="TraderResultCorrected",\n            payload={},\n            payload_version=1,\n            headers={},\n        )\n    )\n$1/' "$COMMANDS"
run "a trader response emits an event" "test_both_trader_responses_are_audited" "$LIVE"

# 9. Accept a file id on the dispute body. A file this command never checks the ownership of is
#    the IDOR case, arriving through a field that looks helpful.
perl -0pi -e 's/(    reason_code: str = Field\(min_length=1, max_length=64\))/    attachment_file_ids: list[uuid.UUID] = Field(default_factory=list)\n$1/' "$ROUTES"
run "the dispute body names a file" "test_a_dispute_body_cannot_name_a_file" "$LIVE"

# 10. Show a trader who published their result. The centre's record of its own act is not the
#     trader's business, and a field present-and-null today is a field filled in later.
perl -0pi -e 's/(    acknowledged_at: datetime \| None\r?\n)/    published_by_admin_user_id: uuid.UUID | None = None\n$1/' "$ROUTES"
run "the trader sees who published it" "test_the_trader_response_hides_who_published" "$LIVE"

echo "== done =="
