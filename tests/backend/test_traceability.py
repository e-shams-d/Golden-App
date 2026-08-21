"""TRACE-001: every obligation the plan claims is proved must name a test.

The plan's "What proves it" sections list the obligations each slice discharges. That
list is a promise, and until now nothing checked it — a slice could claim
`DB-BANK-003` and ship no test for it, and the only way to notice would be for
somebody to read both documents side by side.

So the plan is the authority and this reads it directly. There is no second
hand-maintained list of requirement IDs, because a second list is a second thing to
drift — which is the failure this whole slice has been about.

**An uncovered obligation is recorded, not tolerated silently.** `RECORDED_GAPS`
holds the ones M2 genuinely does not discharge, each with its reason, and the gate
fails on any obligation that is neither cited by a test nor listed there. The
difference between "we know this is not covered" and "nobody checked" is the entire
value of a traceability matrix.

Citations live in module docstrings as `Covers: ID, ID.` lines, alongside the IDs
already quoted in prose throughout the suite. Docstrings rather than markers or a
mapping file: the ID belongs next to the reasoning that explains why the test proves
it, and a reader looking for coverage looks at the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HANDOFF = REPOSITORY_ROOT / "docs" / "handoff"


# Every milestone plan, not one hard-wired path. The M3 plan existed for nine
# merged slices while this gate read only M2 — so roughly eighty obligations were
# stated in a document nothing checked, which is the failure this gate exists to
# prevent, committed against the gate itself.
#
# Slice 1's revision note deferred the fix and said why a naive glob would not do:
# obligations are discharged slice by slice, so pointing the gate at a plan in
# progress fails on the day it lands. `PENDING` below is the answer — an
# obligation is either cited by a test or owned by a named slice, and never
# neither.
def plans() -> list[Path]:
    return sorted(HANDOFF.glob("M*_IMPLEMENTATION_PLAN.md"))


TESTS = REPOSITORY_ROOT / "tests"

# The catalogue prefixes. An ID outside these is a typo or an invented category, and
# either way nothing downstream can group it.
#
# The plan's slice-10 text names ten prefixes (UT, DB, SVC, API, SEC, CON, FILE, AUD,
# OPS, PERF) but its own "What proves it" sections also use JOB, CI, TRACE, SEED and
# BANK. `JOB` was missing from this list on the first attempt, and the invented-prefix
# test below caught it — which meant four obligations (JOB-CRASH-001, JOB-EAGER-001,
# JOB-LEASE-001, JOB-RETRY-001) had been silently outside the coverage check. The list
# here follows the plan's usage rather than its narrower prose.
PREFIXES = (
    "UT",
    "DB",
    "SVC",
    "API",
    "SEC",
    "CON",
    "FILE",
    "AUD",
    "OPS",
    "PERF",
    "CI",
    "TRACE",
    "SEED",
    "BANK",
    "JOB",
    # M3's frontend obligations. Added when this gate was pointed at the M3 plan and
    # the invented-prefix test below refused every `UI-` id — the second time that
    # test has caught a prefix omission that would otherwise have left a whole
    # category outside the coverage check.
    "UI",
)

_ID = re.compile(rf"\b(?:{'|'.join(PREFIXES)})-[A-Z0-9]+(?:-\d+)?\b")
_PROVES_SECTION = re.compile(r"### What proves it\n(.*?)(?=\n### |\n## |\Z)", re.S)

# Obligations M2 does not discharge, with the reason. Each must be a real decision
# rather than a deferral of convenience.
RECORDED_GAPS: dict[str, str] = {
    "PERF-QUEUE-001": (
        "Performance evidence requires a recorded p95 together with the test data "
        "volume and the environment it was measured on. A latency figure without "
        "both is not acceptable evidence, and M2 produces neither a representative "
        "volume nor a production-shaped environment. The evidence emitter records "
        "this field as unfilled with the same reason rather than omitting it, so a "
        "release reader sees the gap instead of a complete-looking set."
    ),
    "BANK-VER-005": (
        "Activation is supposed to be refused unless the version's mappings parse the "
        "synthetic fixtures (08_Bank_File_and_Result_Processing.md:343). No parser "
        "exists: `BankStatementParser` and its siblings are interfaces M8 implements, so "
        "'the mappings parse' is a claim nothing can currently evaluate. The alternative "
        "was a validation step that always passes, which is worse than an absent one "
        "because it reads as a check and would be cited as coverage. M8 adds the parser "
        "and this becomes a real gate; until then activation is refused to every role "
        "anyway under DOC-CONFLICT-045, so nothing can be activated unvalidated."
    ),
    "SEC-FILEDL-008": (
        "M4 issues no signed URLs, so there is no expiry to test. The milestone's "
        "authority lists 'signed/authorized access expires or is re-authorized correctly' "
        "as an M4 test (15_Agent_Implementation_Plan.md:726) and its authorized half is "
        "discharged by SEC-FILEDL-006, which revokes a session between two identical "
        "download requests. The signed half needs a backend that can sign: the local "
        "pilot adapter cannot, ADR-003 has not chosen the production adapter, and a "
        "signed URL is a bearer credential — building one against an undecided backend "
        "would be guessing at the shape of a credential. Recorded rather than dropped so "
        "that whoever accepts M4 reads the absence instead of a complete-looking set."
    ),
}


# Obligations a plan states that no test cites yet, each owned by the slice that
# owes it. Distinct from `RECORDED_GAPS`, which is for obligations that will never
# be discharged and say why — these are simply not written yet.
#
# An entry here is a commitment, not an exemption: two tests below fail on an entry
# whose obligation no plan states, and on an entry for something already covered.
PENDING: dict[str, str] = {
    # DB-SPEC-001 and TRACE-PLAN-001 were owed by slice 1B and are discharged by it.
    #
    # TRACE-PLAN-001 had **no definition anywhere**. It appeared exactly twice in the
    # repository: in the plan line deferring it, and in this dictionary recording the
    # deferral. It was carried for two milestones as a name with an owner and no content,
    # which is a small instance of the failure it now catches — slice 1B defined it from
    # the defect that slice found rather than from the name, and the definition is in
    # `tests/backend/test_governance_evidence_exists.py`.
    #
    # API-PWD-002, AUD-ROLE-001 and SEC-ROLECHANGE-001 were owed by slice 8E and are
    # discharged by it. SEC-ROLECHANGE-001 is the one worth a note: it was renamed in
    # slice 8B from SEC-ROLE-001, which M2:516 uses for an unrelated Postgres privilege
    # test that a merged test already cited — so M2's test was discharging M3's obligation
    # and the plan's own negative control could not fire. Two attempts at the rename
    # collided again, which is why `test_no_obligation_id_means_two_different_things`
    # exists. It has now failed for the first time under the name it was given.
    #
    # UI-ISO-002, UI-LOGIN-001 and UI-NAV-001 were owed by slice 10D and are discharged by
    # it. All three were blocked on the same absence: `adminAuthAdapter` was exported and
    # imported nowhere, so neither app ever called `GET /auth/me`, the shell rendered a
    # literal "role unknown", and an authenticated administrator and an anonymous visitor
    # produced identical bytes. There was no difference to assert against — the third time
    # in this milestone a complete mechanism turned out to have no caller.
    #
    # UI-NAV-001 additionally needed an owner decision, recorded in slice 10D: navigation is
    # gated on the permission that lets you **act**, not the one that lets you read.
    # `accountant` holds a read permission behind every item, so read-gating would have
    # hidden nothing and the test would have been written against a permission nobody holds.
    #
    # `OPS-EVID-001` and `UI-STATE-001` were owed by slice 10C and are discharged by it.
    #
    # The identifier question 10C had to settle first: the plan writes `OPS-EVID-001` and
    # the two existing tests write `OPS-EVIDENCE-001`, which is M2's id (M2 plan:1358).
    # They are **two obligations**, not one misspelling. M2's is about the emitter's shape
    # and its refusals; M3's is about the artifact carrying M3's own state. Deciding they
    # were the same would have discharged an M3 obligation with an M2 test — the cheapest
    # false discharge available anywhere in this ledger, and it needed one docstring line.
    #
    # ---- M4, stated by `docs/handoff/M4_IMPLEMENTATION_PLAN.md` and not yet written ----
    #
    # The plan lands before its slices, so every obligation it states is owed rather than
    # covered. Each entry names the slice that owes it; each slice PR removes its own.
    # SEC-FILEDL-008 is deliberately absent: M4 issues no signed URLs, so it is a recorded
    # gap rather than pending work.
    #
    # Slice 1 is merged: FILE-PURPOSE-001/-002/-003, SEC-PURPOSE-001 and OPS-LIMIT-001 are
    # discharged by tests/backend/test_file_purposes.py.
    # Slice 2 is merged: FILE-UP-001 to -005, API-FILE-001 and AUD-FILE-001 are discharged
    # by tests/integration/test_file_upload.py, and TRACE-CALLER-001 by
    # tests/backend/test_storage_has_a_caller.py — the gate that asks the question no
    # other test in this suite asks, which is whether anything calls the mechanism.
    # Slice 3 is merged: FILE-VAL-005 is discharged by the decision function's own tests
    # in tests/backend/test_file_inspection.py, and FILE-VAL-001 to -004 and
    # SEC-FILEUP-001 by tests/integration/test_file_inspection.py — the consequences
    # (which outcomes keep a row, which keep the bytes, which never reach storage) are
    # claims about the route and the database, not about the detector.
    # Slice 4 is merged. FILE-SCAN-002/-004 and FILE-LIFE-002 are discharged by
    # tests/backend/test_scan_adapters.py; FILE-SCAN-001/-003 and FILE-LIFE-001 by
    # tests/integration/test_scan_policy.py. The split is deliberate: FILE-SCAN-003 is
    # the claim that the *database* refuses `available` without a clean scan, so it is
    # proved with direct SQL that bypasses the command — a test going through the route
    # could not say which of the two layers was holding.
    #
    # Slice 3's file was renamed on the way: tests/backend/test_file_inspection.py is now
    # test_content_inspection.py, because a basename shared with the integration suite
    # stops pytest collecting either.
    # Slice 5 is merged. SEC-FILEDL-003 is discharged by
    # tests/backend/test_file_ownership.py — the registry's own rules, where the cases are
    # cheap to enumerate — and the rest by tests/integration/test_file_download.py, which
    # is where "every request re-evaluates" can be proved by revoking a session between
    # two identical requests rather than by reading the code.
    #
    # SEC-FILEDL-008 stays in RECORDED_GAPS: M4 issues no signed URLs, so there is no
    # expiry to test.
    # Slice 6 is merged: all five are discharged by
    # tests/integration/test_file_derivation.py. Every claim in that slice is about
    # atomicity or about a row existing, so none of it can be proved without a database —
    # including FILE-DERIV-002, which runs the writer and the reconciliation check
    # against each other rather than asserting either alone.
    # Slice 7 is merged: all five are discharged by
    # tests/integration/test_reconciliation_cli.py.
    #
    # The plan's heading says "the six reconciliation checks". There are **seven**, plus an
    # aggregator M2 had already written. OPS-RECON-001 is enumerated from the module for
    # exactly that reason — a literal count in the test would have encoded the plan's
    # mistake and passed.
    # Slice 8 is merged: all nine are discharged by
    # tests/integration/test_bank_config_api.py.
    #
    # The slice also tried to add value CHECKs to `bank_profile_versions.status` and
    # `bank_mappings.status`, and `test_status_catalogue_drift.py` refused them. Its
    # `DELIBERATELY_UNCONSTRAINED` note exists so "the next person to reach for an enum
    # finds the reason before the constraint", and it worked exactly that way. Only
    # `bank_mappings.file_type` is constrained — a *type* column no catalogue entry
    # covers, refusing a value from another document's vocabulary rather than a spelling
    # of this one's.
    # Slice 9 is merged. BANK-VER-001/-002/-003/-004/-006/-007 are discharged by
    # tests/integration/test_bank_version_resolution.py.
    #
    # BANK-VER-005 moved to RECORDED_GAPS above rather than being discharged: it requires
    # a mapping parser that does not exist until M8, and a validation step that always
    # passes reads as a check while proving nothing. It is also currently unreachable —
    # activation is denied to every role under DOC-CONFLICT-045.
    #
    # The slice's own correction: the two activation permissions are added here, together
    # with the migration that seeds them, which is what slice 8 deferred. Adding the
    # identifier without the seed row would have left the catalogue and the database
    # disagreeing.
    # Slice 10 is merged: UI-FILE-001 to -005 are discharged by
    # packages/ui/test/file-components.test.tsx and UI-FILE-006 by
    # apps/trader-pwa/test/evidence-screen.test.ts.
    #
    # The split is deliberate. UI-FILE-006 is the question no component test asks — does a
    # screen import this — and it belongs with the application rather than the package.
    # The rest are decisions rather than renderings, so the components expose them as
    # plain functions and the tests call those: this package renders to static markup and
    # has no DOM-interaction library, and adding one to assert a boolean would be a
    # dependency bought for a conditional.
    # Slice 11 is merged, and with it M4: all five are discharged by
    # tests/backend/test_m4_definition_of_done.py.
    #
    # **Nothing is owed for M4.** TRACE-M4-001 is the obligation that says so, and it reads
    # this dictionary — so it failed on its own five entries until they came out, which is
    # the gate working rather than a nuisance: an obligation cannot certify a milestone
    # complete while it is itself outstanding.
    #
    # Two of M4's obligations are in RECORDED_GAPS above rather than here, each with the
    # reason it will never be discharged in this milestone: SEC-FILEDL-008 (no signed URLs
    # are issued, so there is no expiry to test) and BANK-VER-005 (no mapping parser exists
    # until M8, and a validation step that always passes reads as a check).
    #
    # ---- M5, stated by `docs/handoff/M5_IMPLEMENTATION_PLAN.md` and not yet written ----
    #
    # The plan lands before its slices, so all 43 are owed. Each slice PR removes its own
    # entries; the milestone is over when the last one goes and TRACE-M5-001 can pass.
    #
    # Nothing is in RECORDED_GAPS for M5. That is worth stating rather than leaving to be
    # noticed: M5 builds its own tables, so unlike M4 there is no dependency on an
    # undecided ADR or an unwritten parser to excuse anything.
    # Slice 1 is merged: DB-BEN-001/-002/-003 and DB-TRADER-002 are discharged by
    # tests/backend/test_beneficiary_schema.py.
    #
    # DB-TRADER-002 is discharged in its *second* passing state, not its first. The
    # plan states two: the columns carry the approved CHECK, or they carry none and
    # `DELIBERATELY_UNCONSTRAINED` still records why. DOC-CONFLICT-024's values are
    # the owner's decision and it has not arrived, so the columns stay unconstrained
    # and slice 1 shipped the rest — §2.4's rule, applied rather than worked around.
    # The test asserts exactly one of the two holds, so when the CHECK is approved it
    # fails until the reserved-list entry comes out.
    #
    # The slice also raised DOC-CONFLICT-048: `beneficiaries.verification_status` has
    # four perfectly clear values in a Notes cell of document 04 and no approved
    # catalogue records them. It ships with no CHECK. Nothing about those values looks
    # uncertain, which is why the absence needed a test on both sides rather than a
    # comment — what is missing is approval, not clarity.
    # Slice 2 is merged. SVC-BEN-001/-002, SEC-BEN-001 and AUD-BEN-001 are discharged
    # by tests/integration/test_beneficiaries.py; SVC-BEN-003 and SEC-BEN-002 by
    # tests/backend/test_beneficiary_surface.py.
    #
    # The split is the same one M4 slice 10 made and for the same reason. The first
    # four are claims about behaviour and need a database and two real traders. The
    # last two are claims that something **does not exist** — no amount column, no
    # sharing mechanism — and a runtime test of an absence can only show that some
    # mechanism refused, which is the opposite of what is claimed.
    #
    # The slice also found that `beneficiary.read`, `beneficiary.create_own` and
    # `beneficiary.update_future` are catalogued under `trader_owner` while
    # `ActorContext` refuses, by invariant, to give a trader actor any permission at
    # all. Those rows describe intent rather than a runtime mechanism, so the routes
    # authorise through `owned_or_permitted` — a dependency, not an in-handler check,
    # because `test_permission_guards.py` reads the dependency graph and an in-handler
    # check would have had to be excused as needing no permission when it needs one
    # from half its callers. Raised as DOC-CONFLICT-049 together with the two
    # endpoints document 05 names and no permission covers.
    # Slice 3 is merged. DB-REQ-001 and DB-REV-001 are discharged by
    # tests/backend/test_payment_request_schema.py, which compares against document
    # 04 by **parsing** it rather than transcribing it — slice 1 transcribed one type
    # wrong and the test locked the mistake in. DB-REV-002 and DB-REV-003 by
    # tests/integration/test_request_revision_integrity.py, and CON-REQ-001 and
    # SEC-REQ-001 by tests/integration/test_payment_request_draft.py.
    #
    # CON-REQ-001 was **unprovable as the plan scoped it**. The obligation is that a
    # stale `If-Match` returns 412, and the slice's only listed command was
    # `create_draft` — a route that creates a resource has nothing for `If-Match` to
    # be stale against. `cancel_draft` was added because of that; it is already in
    # the milestone at 15_Agent_Implementation_Plan.md:766 and needs optimistic
    # concurrency for its own sake.
    #
    # Slice 3 also reversed SVC-REV-003, which slice 5 still owes: document 04's
    # UNIQUE(payment_request_id, content_hash) refuses identical content, where the
    # plan had claimed it must be permitted.
    # Slice 4 is merged. SVC-REQ-001/-002/-003 and API-REQ-001 are all discharged by
    # tests/integration/test_payment_request_money.py.
    #
    # The arithmetic was never the work. `app/core/money.py` has held `to_rial`, a
    # three-way consistency check and a strict wire parser since M2 — and **nothing
    # called any of it**. Slice 3 took `amount_irr` as an integer and the entered pair
    # as optional extras, so a caller could hand the command a canonical figure that did
    # not follow from what was typed. Fifth instance of a complete mechanism with no
    # caller; see the M4 plan's §1.3 for the first four.
    #
    # API-REQ-001 is asserted against the **raw JSON text** rather than the parsed body.
    # `json.loads` turns an emitted `34400000000` back into a Python int, so a test that
    # compared parsed values would pass on exactly the shape the money contract forbids —
    # the precision loss happens in the client's parser, not in ours.
    #
    # DOC-CONFLICT-050 came out of the slice: document 05's examples write monetary
    # values as JSON numbers where MONEY_TIME_CONTRACT.md rule 8 requires integer
    # strings. The nested `amount` shape is document 05's and is implemented as written;
    # only the encoding is in dispute, and the contract wins because it is approved M0
    # governance and the milestone authority agrees with it.
    # Reversed by slice 3, which read the constraints under the table the plan had only
    # cited by line range: 04_Database_Schema.md:901 is UNIQUE(payment_request_id,
    # content_hash), so identical content is refused rather than permitted.
    # Slice 5 is merged. All five are discharged by
    # tests/integration/test_payment_request_revisions.py.
    #
    # SVC-REV-001 is the milestone's central property and its test is the one to read:
    # every column of revision n is captured before a correction and compared after.
    # Asserting only that the amount is unchanged would pass on a revision whose
    # `content_hash` or `created_at` had been rewritten, and a row editable in any
    # field is not evidence of anything.
    #
    # `superseded_at` is left NULL rather than written, and that is asserted. Document
    # 04 defines the column; setting it would be an update to an immutable row, and
    # 'which revision is current' is already answered by
    # `payment_requests.current_revision_id`. Recording the fact twice, where one copy
    # needs a widened grant, trades the guarantee for a convenience.
    #
    # SVC-REV-003 is the reversed obligation slice 3 corrected: a byte-identical
    # correction is refused. Refused twice over, deliberately — the command compares
    # hashes and says what is wrong, and UNIQUE(payment_request_id, content_hash)
    # behind it is what makes the rule unbypassable. A description-only edit is *not*
    # identical and has its own test, because the description is submitted intent and
    # a reviewer read it.
    #
    # One gap is recorded inside the history test rather than here: it resets the
    # status with direct SQL between corrections, because a correction moves the
    # request to `submitted_to_center` and only the accountant's
    # `return_for_correction` — slice 7 — can send it back. Until that exists there is
    # no route to revision 3 at all. Slice 7 should replace the reset with the real
    # command; a test still writing status by hand afterwards has stopped exercising it.
    # Slice 6 is merged. All five are discharged by
    # tests/integration/test_payment_request_submission.py.
    #
    # **The plan's SVC-SUB-001 was not implementable as written** and slice 6 corrected
    # it. It said submission fills the snapshot columns from the beneficiary at that
    # instant. A revision cannot be updated, so submission has nothing to fill — and
    # filling it would mean submission creates a revision, which for a draft-then-submit
    # with no edits would be byte-identical to the first and refused by
    # UNIQUE(payment_request_id, content_hash). A trader could not submit an unmodified
    # draft. The snapshot is taken where content is stated, by create_draft and
    # create_revision, and submission verifies it is complete.
    #
    # That is the third plan correction this milestone: DOC-CONFLICT-005's real shape,
    # SVC-REV-003 reversed by document 04's uniqueness constraint, and this. All three
    # came from reading what a cited line actually says rather than from a gate.
    #
    # SVC-SUB-002 has two tests on purpose. One reads the table and proves the row did
    # not move; the other reads the history endpoint and proves the *reader* does not
    # see the new values either. A history that joined to `beneficiaries` instead of
    # reading the snapshot columns would pass the first and fail the second.
    #
    # AUD-REQ-001 is the first outbox event in this aggregate. Draft creation and
    # cancellation publish nothing — nothing outside the platform acts on a trader
    # opening or abandoning a draft — and submission is the moment the centre's queue
    # changes. The payload carries identifiers only: a consumer that needs the amount or
    # the beneficiary reads the aggregate rather than having a payment destination put
    # on a queue.
    # SVC-REVIEW-001 and SVC-REVIEW-003 are discharged by
    # `test_review_transitions.py`, which parses document 06's own state machine and §29.1
    # cancellation table rather than restating either. Their entries were removed from here
    # in the same commit, because this gate fails an obligation that is both pending and
    # covered — the ledger has to be honest in that direction too.
    # UI-REQ-001, -002 and -003 are discharged by `apps/trader-pwa/test/request-view.test.ts`
    # and `no-money-arithmetic.test.ts`; UI-REQ-004 by `screens-are-reachable.test.ts` in both
    # apps. This repository has no jsdom, so the screens' judgements live in
    # `src/request-view.ts` as functions and are tested there — asserting "the screen shows the
    # note" by grepping JSX would test a string rather than a behaviour. That the note reaches
    # the browser at all is proved server-side, in `test_payment_request_review.py`.
    #
    # API-REQ-002 and -003 arrived with them: the two reads the screens need did not exist, and
    # an endpoint whose only consumer does not exist yet is the defect this repository has
    # produced in every milestone.
    # TRACE-DOD-007 is discharged by `tests/integration/test_m5_journey.py` — one test, six
    # steps, two actors, through the API. Six steps proved separately can all pass while the
    # sequence is impossible, and slice 5's unmandated resubmission was exactly that: step 4
    # and step 5 were the same call and both had passing tests.
    # These two notes described the wrong obligations, and the mistake was the kind that
    # produces a green gate over unwritten work. The plan at
    # `M5_IMPLEMENTATION_PLAN.md:669-671` defines TRACE-DOD-009 as status-catalogue and
    # transition conformance — "every status the request aggregate can reach in M5 is one the
    # approved catalogue lists, and every M5 transition is one document 06 states". This
    # dictionary said "no request-scoped command consults one", which is the second half of
    # TRACE-DOD-008's sentence, not -009 at all.
    #
    # An implementer working from here would have written both halves of -008, never written
    # the status gate, and `test_nothing_is_owed_for_m5` would have passed regardless: the
    # obligation's *identity* comes from the plan, and only its description lived here. The
    # plan is the contract, so the plan's text stands and these notes now follow it.
    # TRACE-DOD-008 is discharged by `test_m5_definition_of_done.py`, which calls nothing:
    # it walks the live route table for declarations and ASTs the two request modules for the
    # enforcement a closure walk cannot see. It sits in `tests/backend` on purpose — in
    # `tests/integration` a missing PostgreSQL would turn the milestone's one prohibition
    # into a skip, and a skipped gate is a green gate.
    # TRACE-DOD-009 is discharged in the same file, against three authorities rather than
    # one: the approved status catalogue, document 06's diagram, and the code's own tables.
    # Cancellation is compared against §29.1 instead of the diagram, because the diagram
    # declares `cancelled` and draws no arrow into it — a comparison built on it would prove
    # that cancelling is never permitted.
    # TRACE-M5-001 was the last entry to go, and it had to be: it is the obligation that reads
    # this dictionary and asserts no M5 obligation remains in it. While its own line was here
    # it failed, which is the gate working rather than a bootstrap problem — and removing it is
    # the edit that ends M5.
    #
    # Slice 1 is discharged: the engine in tests/backend/test_splitting.py, where it is
    # pure, and the route in tests/integration/test_batch_preview.py. Its eight entries
    # left here in the same commit, because this gate fails an obligation that is both
    # pending and covered.
    # M6 — attempts, splitting and the immutable batch version. Thirty-nine obligations across
    # five slices: the plan shipped with thirty-six and slice 2 added three it had missed.
    # `docs/handoff/M6_IMPLEMENTATION_PLAN.md` §4 records the ten questions the owner must
    # settle, of which only G-2 blocked slice 1.
    # Added while writing slice 2, so the plan and this ledger stay one document. Each names
    # something the plan's original slice-2 list did not: a projection that can drift from what
    # it projects, a catalogued idempotency requirement with nothing calling the resolver, and
    # a number format M5 invented rather than read.
    "SVC-BATCH-005": "M6 slice 4 — a replacement supersedes and the superseded rows do not move",
    "SVC-BATCH-006": "M6 slice 4 — cancellation from exactly the states §29.2 permits",
    "SVC-BATCH-007": "M6 slice 4 — release leaves queryable evidence and keeps the history",
    "SVC-BATCH-008": "M6 slice 4 — the baseline's double-payment negative test",
    "AUD-BATCH-003": "M6 slice 4 — supersession is audited; blocked on G-8's missing action",
    "TRACE-DOD-010": "M6 slice 5 — the journey to a finalized version, in one test",
    "TRACE-DOD-011": "M6 slice 5 — the frozen snapshot is sufficient without a live profile",
    "TRACE-DOD-012": "M6 slice 5 — no manager-only permission reaches a finalized version",
    "SEC-BATCH-004": "M6 slice 5 — and no request-level route gained one while M6 was built",
    "TRACE-M6-001": "M6 slice 5 — nothing is owed for M6; it reads this dictionary",
}


def obligations_stated_by(plan: Path) -> set[str]:
    """The obligations one plan states, so a milestone gate can ask about its own.

    Added by the M5 plan, which found the M4 Definition-of-Done gate deciding what M4
    owed by prefix — `TRACE-` among them. M5 states `TRACE-DOD-007`, and M4's gate
    promptly reported it as an outstanding M4 obligation. The prefix was never the
    rule; it was a shorthand for one, and it stopped agreeing with the rule the moment
    a second milestone used the same family of identifiers.
    """

    found: set[str] = set()
    for section in _PROVES_SECTION.findall(plan.read_text(encoding="utf-8")):
        found.update(_ID.findall(section))
    return found


def plan_obligations() -> set[str]:
    found: set[str] = set()
    for plan in plans():
        found.update(obligations_stated_by(plan))
    return found


def _citation_files() -> list[Path]:
    """Every file that may cite an obligation.

    Python under `tests/`, and **TypeScript under `apps/` and `packages/`**. The
    second half was missing until slice 10: M3's `UI-*` obligations are proved by
    vitest files, so a Python-only scanner reported them uncovered no matter how
    thoroughly they were tested. A gate that cannot see half the suite reports the
    wrong half as the gap, which is worse than reporting nothing.
    """

    files = [path for path in TESTS.rglob("*.py") if path.name != "test_traceability.py"]

    for root in (REPOSITORY_ROOT / "apps", REPOSITORY_ROOT / "packages"):
        for pattern in ("*.ts", "*.tsx"):
            files.extend(
                path
                for path in root.rglob(pattern)
                if "node_modules" not in path.parts
                and ".next" not in path.parts
                # Only test files count as coverage. A `UI-NAV-001` in a comment in
                # `src/auth.ts` explaining *why* the code is shaped a certain way is
                # documentation, not a test — and counting it satisfied the gate for
                # an obligation nothing exercised. Found by the guard-the-guard
                # below, which reported the entry as "already covered".
                and (
                    path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
                    or "test" in path.parts
                    or "tests" in path.parts
                )
            )
    return sorted(files)


def cited_ids() -> dict[str, set[str]]:
    """Every obligation id cited in the suite, mapped to the files citing it.

    This file is excluded by `_citation_files`: it names ids in `RECORDED_GAPS` and
    `PENDING`, and counting those as coverage would let a gap register itself as
    discharged.
    """

    found: dict[str, set[str]] = {}
    for path in _citation_files():
        for identifier in _ID.findall(path.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(identifier, set()).add(str(path.relative_to(REPOSITORY_ROOT)))
    return found


@pytest.fixture(scope="module")
def obligations() -> set[str]:
    found = plan_obligations()
    assert found, "no obligations parsed from the plan; its section headings changed"
    return found


def test_the_plan_states_a_substantial_number_of_obligations(obligations: set[str]) -> None:
    """Guard the guard.

    Every assertion below passes vacuously if the plan parser returns nothing, which
    is exactly what a changed heading would cause.
    """

    assert len(obligations) > 50, f"only {len(obligations)} obligations parsed"


def test_every_obligation_is_cited_or_recorded_as_a_gap(obligations: set[str]) -> None:
    cited = cited_ids()
    uncovered = sorted(obligations - set(cited) - set(RECORDED_GAPS) - set(PENDING))

    assert uncovered == [], (
        "these plans claim the following are proved and no test names them:\n"
        + "\n".join(f"  {identifier}" for identifier in uncovered)
        + "\nAdd the id to the docstring of the test that proves it, record it in "
        "RECORDED_GAPS with the reason it will never be discharged, or list it in "
        "PENDING with the slice that owes it."
    )


def test_every_pending_obligation_names_a_slice_that_owes_it(obligations: set[str]) -> None:
    """A pending obligation with no owner is one nobody will write.

    The same rule the IDOR ledger and the ownership-scope exemptions follow: "not
    yet" has to name who, or it is indistinguishable from "not at all".
    """

    for identifier, owner in sorted(PENDING.items()):
        assert identifier in obligations, (
            f"{identifier} is listed as pending and no plan states it — a stale entry "
            "that exempts nothing while reading like a decision"
        )
        assert owner.strip(), f"{identifier} is pending with no owner"


def test_no_pending_obligation_is_already_covered(obligations: set[str]) -> None:
    """Guard the guard, in the other direction.

    An entry in PENDING for an obligation a test already cites is a licence nobody
    is using, and it would silently absorb the next real gap under the same id.
    """

    del obligations
    cited = cited_ids()
    stale = sorted(identifier for identifier in PENDING if identifier in cited)

    assert stale == [], f"pending obligations that are in fact cited: {stale}"


def test_no_recorded_gap_is_actually_covered(obligations: set[str]) -> None:
    """The other direction.

    A gap entry for something a test now proves understates the coverage, and it
    would let the obligation be quietly dropped later on the strength of a stale
    excuse.
    """

    cited = set(cited_ids())
    resolved = sorted(set(RECORDED_GAPS) & cited)

    assert resolved == [], (
        f"these are recorded as gaps but a test now cites them: {resolved}. Remove the entry."
    )


def test_every_recorded_gap_is_a_real_obligation(obligations: set[str]) -> None:
    """A gap for an id the plan does not require is an excuse for nothing."""

    invented = sorted(set(RECORDED_GAPS) - obligations)

    assert invented == [], f"recorded gaps that the plan does not require: {invented}"


@pytest.mark.parametrize("identifier", sorted(RECORDED_GAPS))
def test_each_gap_states_a_reason_not_a_placeholder(identifier: str) -> None:
    reason = RECORDED_GAPS[identifier]

    assert len(reason) > 80, f"{identifier} has no real reason recorded"
    assert "TODO" not in reason and "later" not in reason.lower()[:40]


def test_the_recorded_gap_matches_what_the_evidence_emitter_reports() -> None:
    """The gap must say the same thing in both places a reader might look.

    `PERF-QUEUE-001` is unfilled here and `performance_p95` is unfilled in the
    emitter's artifact. If those two disagreed, one of them would be reassuring
    somebody falsely.
    """

    from scripts.emit_evidence import UNFILLABLE_AT_M2

    assert "performance_p95" in UNFILLABLE_AT_M2
    assert "PERF-QUEUE-001" in RECORDED_GAPS
    for phrase in ("volume", "environment"):
        assert phrase in UNFILLABLE_AT_M2["performance_p95"].lower()
        assert phrase in RECORDED_GAPS["PERF-QUEUE-001"].lower()


def test_every_cited_id_uses_a_catalogue_prefix() -> None:
    """The extraction only matches catalogue prefixes, so this checks the inverse:
    that nothing shaped like an id is sitting in the suite under an invented
    category, which would look like traceability and provide none."""

    invented = re.compile(r"\b([A-Z]{2,6})-[A-Z0-9]+-\d+\b")
    offenders: dict[str, set[str]] = {}
    for path in sorted(TESTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for prefix in invented.findall(path.read_text(encoding="utf-8")):
            if prefix not in PREFIXES and prefix != "DOC":
                offenders.setdefault(prefix, set()).add(str(path.relative_to(REPOSITORY_ROOT)))

    assert offenders == {}, f"ids using a prefix outside the catalogue: {offenders}"


CRITICAL_OBLIGATIONS = ("SVC-ATOMIC-001", "CON-IDEM-001", "AUD-ROLLBACK-001", "DB-MIG-001")

# Which of the four are actually proved at two layers today. Written down because the
# test below used to be named for "more than one test" while checking `< 1` — a
# threshold that asks whether the obligation is cited at all, which is what the
# previous test in this file already asks. Renaming it to what it checked would have
# hidden the gap; recording which ones fall short keeps it visible and makes adding the
# second layer a deletion from this set.
SINGLY_CITED: dict[str, str] = {
    "CON-IDEM-001": (
        "One layer: the HTTP replay test. The resolver has no unit-level test of its "
        "own, so a canonical-hash mistake would have to be caught through a route."
    ),
    "AUD-ROLLBACK-001": (
        "One layer: the integration test that rolls a transaction back. Nothing asserts "
        "at the writer level that an audit row cannot outlive its command."
    ),
    "DB-MIG-001": (
        "One layer: the migration-head reconciliation. The second layer would be an "
        "upgrade/downgrade round trip, which the forward-fix policy makes moot for "
        "downgrades and which nothing exercises for upgrades beyond head equality."
    ),
}


def obligations_by_plan() -> dict[str, set[str]]:
    """Which plan states each obligation. Deliberately not merged into one set.

    `plan_obligations()` unions everything, which is what the coverage checks want and
    is exactly why the collisions below were invisible for two milestones.
    """

    found: dict[str, set[str]] = {}
    for plan in plans():
        name = plan.name.split("_")[0]
        text = plan.read_text(encoding="utf-8")
        for section in _PROVES_SECTION.findall(text):
            for identifier in _ID.findall(section):
                found.setdefault(identifier, set()).add(name)
    return found


# Identifiers two plans state deliberately, because they name the *same* obligation.
# Distinct from a collision, and the difference is not decidable by a machine: the check
# below reports every shared id, and each must be either renamed or recorded here with
# the reason it is one obligation rather than two.
#
# All of these have the same cause. M2's slice-10 section lists obligations for work M3
# actually executed, so the earlier plan promised what the later plan built. That is
# untidy rather than wrong — the citation discharges a claim both documents make — and
# rewriting a merged plan to remove a promise it kept would be worse.
SHARED_OBLIGATIONS: dict[str, str] = {
    "SEC-SOD-001": (
        "M2:926 lists `SEC-SOD-001..004` among its identity-and-RBAC obligations; M3:751 "
        "states the same thing concretely as the separation-of-duties refusal, which is "
        "where the code was written. One obligation, promised in the earlier plan and "
        "discharged in the later one."
    ),
}


def test_no_obligation_id_means_two_different_things() -> None:
    """One identifier, one obligation — the check that was missing.

    Coverage is keyed by exact string, so when two plans use one id the citations of
    either discharge both. Slice 8B found two live instances, and neither was catchable
    by any existing gate:

    `SEC-ROLE-001` was M2's "the app runtime role cannot UPDATE `audit_logs`" *and*
    M3's "a role change without recent auth is refused". M2's Postgres privilege test is
    cited by a merged test, so M3's obligation reported itself proved and the plan's own
    negative control could not fire no matter what the role-change code did.

    `SEC-STAMP-001` was stated by both plans the same way, and the mechanism it names —
    incrementing `security_stamp_version` — has no producer in the codebase at all.

    Both were renamed rather than merged, because they are different obligations that
    happened to collide. The failure mode this prevents is not a typo; it is a second
    plan reusing a plausible id and inheriting somebody else's evidence.
    """

    by_plan = obligations_by_plan()
    shared = {
        identifier: sorted(names)
        for identifier, names in sorted(by_plan.items())
        if len(names) > 1 and identifier not in SHARED_OBLIGATIONS
    }

    assert shared == {}, (
        "these obligation ids are stated by more than one plan, so a citation of either "
        f"discharges both:\n{shared}\n"
        "Rename one — and check the new name against every plan first, because two "
        "attempts at exactly this rename hit occupied names. If the two plans genuinely "
        "state the same obligation, record it in SHARED_OBLIGATIONS with the reason."
    )

    # Guard the guard: an entry recording a shared id that is no longer shared is a
    # stale exemption, and it would absorb a real collision later under the same string.
    stale = sorted(
        identifier for identifier in SHARED_OBLIGATIONS if len(by_plan.get(identifier, set())) <= 1
    )
    assert stale == [], (
        f"these are recorded as deliberately shared and only one plan states them: {stale}"
    )

    for identifier, reason in SHARED_OBLIGATIONS.items():
        assert len(reason) > 80, f"{identifier} needs a reason, not a placeholder"


def test_the_per_plan_parser_sees_every_plan() -> None:
    """Guard the guard. The check above is a comparison over a dict it builds itself."""

    by_plan = obligations_by_plan()
    assert by_plan, "no obligations parsed per plan; the section heading changed"

    seen = {name for names in by_plan.values() for name in names}
    expected = {plan.name.split("_")[0] for plan in plans()}
    assert seen == expected, (
        f"the per-plan parser found obligations in {sorted(seen)} but there are plans "
        f"for {sorted(expected)} — a plan contributing nothing is one this check cannot "
        "see collisions in"
    )


def test_every_critical_obligation_is_cited_at_all(obligations: set[str]) -> None:
    """The floor, separated from the ceiling it was pretending to be."""

    del obligations
    cited = cited_ids()
    uncited = sorted(name for name in CRITICAL_OBLIGATIONS if not cited.get(name))

    assert uncited == [], f"critical obligations with no citation: {uncited}"


def test_the_heaviest_obligations_are_cited_at_two_layers_or_recorded(
    obligations: set[str],
) -> None:
    """The integrity primitives the plan calls critical, proved at more than one layer.

    A single test can be wrong in the same way the code is wrong, which is why these
    four are singled out: their failures would be silent and financial.

    This test asserted `< 1` until slice 8B, so it was the previous test with a stronger
    name — three of the four have exactly one citing file, and nothing said so. The
    honest version keeps the two-layer requirement and records the three shortfalls with
    the reason, so each is a line somebody can delete rather than a claim nobody checked.
    """

    del obligations
    cited = cited_ids()
    thin = {
        identifier: sorted(cited.get(identifier, set()))
        for identifier in CRITICAL_OBLIGATIONS
        if len(cited.get(identifier, set())) < 2 and identifier not in SINGLY_CITED
    }

    assert thin == {}, (
        f"critical obligations proved at only one layer: {thin}. Add the second layer, "
        "or record it in SINGLY_CITED with the reason the single layer is what exists."
    )

    # Guard the guard, in the other direction: an entry here for an obligation that now
    # has two citations is a stale excuse, and it would absorb a real regression later.
    resolved = sorted(
        identifier for identifier in SINGLY_CITED if len(cited.get(identifier, set())) >= 2
    )
    assert resolved == [], (
        f"these are recorded as singly-cited and now have two or more: {resolved}. "
        "Remove the entry."
    )

    for identifier, reason in SINGLY_CITED.items():
        assert identifier in CRITICAL_OBLIGATIONS, f"{identifier} is not a critical obligation"
        assert len(reason) > 60, f"{identifier} needs a reason, not a placeholder"
