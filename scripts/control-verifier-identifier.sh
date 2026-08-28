#!/usr/bin/env bash
# The control for `verify-docker.sh`'s end-to-end authentication identifier.
#
# On 2026-08-28 that stage failed in CI with "A correct password did not complete
# authentication against the stack", and its own message named AUTH_CSRF_KEY_SECRET —
# which was present and correct. The real cause was the identifier the stage generated
# for itself: `09` followed by `cut -c1-9` of a uint32's decimal text, which is shorter
# than nine digits whenever the number is below 10^8.
#
# **Three correct behaviours hid it.** `normalize_mobile` refuses a short number;
# `POST /traders/register` answers `accepted=true` anyway so a public endpoint cannot
# be used to enumerate accounts; and a login refusal is a generic 401 because
# `12_Security_RBAC_Audit.md:403` forbids separating "not a valid number" from "wrong
# password". So registration reported success for an account that was never created,
# the wrong-password probe got its expected 401 for the wrong reason, and only the
# correct-password probe failed — pointing confidently at the wrong thing.
#
# This script exists because that diagnosis was a probability claim, and a probability
# claim asserted in a comment is unfalsifiable. It measures both forms. The old one
# must misfire — a control that never fires proves nothing — and the new one must not.
#
# Run it if the generator in `assert_authentication_completes` is ever rewritten.
set -uo pipefail

TRIALS=${1:-20000}

old_bad=0
new_bad=0
i=0
while [ "$i" -lt "$TRIALS" ]; do
    n=$(od -An -N4 -tu4 /dev/urandom | tr -d ' \n')

    # The form that shipped until 2026-08-28.
    old="09$(printf '%s' "$n" | cut -c1-9)"
    old=$(printf '%s' "$old" | cut -c1-11)
    case "$old" in
        09[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
        *) old_bad=$((old_bad + 1)) ;;
    esac

    # The form in the verifier now.
    new=$(printf '09%09d' "$((n % 1000000000))")
    case "$new" in
        09[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
        *) new_bad=$((new_bad + 1)) ;;
    esac

    i=$((i + 1))
done

printf 'trials: %s\n' "$TRIALS"
printf 'old form, malformed: %s  (expected about %s, i.e. 10^8/2^32)\n' \
    "$old_bad" "$((TRIALS * 100000000 / 4294967296))"
printf 'new form, malformed: %s  (must be 0)\n' "$new_bad"

if [ "$old_bad" -eq 0 ]; then
    printf '%s\n' \
        "CONTROL FAILED: the old form never misfired in $TRIALS trials, so it does" \
        "not explain the CI failure this fix was written for." >&2
    exit 1
fi
if [ "$new_bad" -ne 0 ]; then
    printf '%s\n' "FIX FAILED: the new form still produces malformed identifiers." >&2
    exit 1
fi
printf '%s\n' "PROVEN: the old form misfires, the new form cannot."
