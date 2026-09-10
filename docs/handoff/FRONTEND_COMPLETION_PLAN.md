# Completing the frontend

**Written 2026-09-08, after the M11 screens phase closed with eleven slices (PRs #156–#166).**

That phase discharged every obligation its plan carried. This one exists because *discharging the
plan* and *completing the frontend* are different things, and slice 8's Definition of Done gate is
what made the difference measurable: of **153 published operations, 27 have no screen**, and seven
of those never should.

This plan covers the twenty that should. It is ordered by what a person is unable to do without
it, not by what is easiest.

## How to read the tables

Each slice names the operations it makes reachable. When it is finished, its entries **leave**
`NO_SCREEN` in `tests/backend/test_every_operation_has_a_screen.py` — a deletion rather than an
edit, which is what a closed entry looks like there. `test_no_recorded_operation_has_quietly_gained
_a_screen` fails if one is left behind.

---

## Slice A — the publication correction

**Why first.** Without it a wrong published financial result cannot be corrected at all: not by a
screen, not by an API call, not by anybody. Every other gap is an inconvenience; this one is a
number a trader has been told that the centre cannot take back.

Unblocked by the owner's decision of 2026-09-08: **the accountant prepares, the manager approves.**

| operation | what it needs |
|---|---|
| `POST /payment-requests/{id}/publications/corrections` | the screen below, and the grants |

**What it changes**

1. **A new migration** granting `payment_attempt.correct_result` to `accountant` and
   `payment_publication.correct` to `manager`. Not an edit to `20260801_0008`, which is history.
2. **The catalogue**, exactly as `~/apply-owner-decisions.py` writes it — that script is written
   and its assertions pass. Then `python3 infra/scripts/m0_manifest.py --write`.
3. **The correction screen**, replacing the `publication.correctionBlocked` panel on
   `/requests/[requestId]/publication`. It is the **one screen in this application that needs the
   recent-auth dialog** §8.11 specifies: `command_catalog.yaml` puts
   `recent_auth: "required_for_approving_second_human"` on this command and on no other.

**Three tests will fail, and all three are correct**

- `test_result_screens_exist.py::test_the_correction_screen_is_absent_and_its_grant_is_still_
  unassigned` — **this is the deferral expiring exactly as designed.** Slice 4 wrote it so that the
  day a role holds the grant, somebody has to decide deliberately whether the screen should now
  exist. Rewrite it as "the screen exists and requires a step-up".
- `test_m5_definition_of_done.py` ×2 — the manager-only permission set moved.
- `test_rbac_seed_matches_catalogue.py` — the seed must reproduce the catalogue's defaults.

**What proves it.** The split is enforced by `_refuse_a_single_human`, which compares the two actor
ids — so a person holding both grants is still refused. `tests/integration/test_publication_
correction.py` has asserted that since M9; the screen must not reimplement it.

### What slice A actually cost, recorded 2026-09-10

Two commits, because building it found two blockers behind the one this plan knew about. They are
written here rather than only in the commits, because the plan's ordering argument assumed slice A
was self-contained and it was not.

**The step-up could not prove the right person.** `command_catalog.yaml` asks this command for
`recent_auth: "required_for_approving_second_human"`, and `app/security/step_up.py` binds a context
to the **calling** actor and session — so the mechanism that existed could only ever prove the
*preparer* was present, which in a dual-control command is the wrong human. This plan read the
requirement as "add the dialog §8.11 specifies"; it was "build a step-up that authenticates
somebody other than the session holder". The owner decided the shape on 2026-09-09: the manager
types their own username and password at the preparer's machine. `POST
/auth/admin/approver-reauthenticate` issues a context bound to the approver's identity and the
caller's session, and `rejection_for` grew one parameter — `on_behalf_of` — whose only caller is
the correction command.

**The screen had nothing to show.** A publication carries `primary_evidence_link_id` and nothing
could resolve it: the evidence surface was three POSTs, `GET /bank-result-bundles/{id}` returns
three segment *counts*, and `GET /queues/unresolved-bundles-segments` returns bundles despite its
name. So `GET /evidence-links/{link_id}` and `GET
/bank-result-bundles/{bundle_id}/receipt-segments` were built here. **By the tables below they
belong to slices C and E** — which would have put slice A's completion after slice E and
contradicted the reason given for putting it first. They are built once, in A, and C and E are
shorter for it.

**A gate was found wrong on the way.** `test_every_operation_has_a_screen.py` matched reachability
on path segments and ignored the HTTP method, so adding a `GET` on `/evidence-links/{id}` made
three unbuilt `POST`s look reached. Making it method-aware surfaced five operations it had been
excusing — three `PATCH` edit routes, `GET /meta/release`, and `PUT /roles/{id}/permissions`, which
the roles screen's own docstring says it deliberately does not call. All five are now recorded with
their reasons. None is urgent; all are honest gaps this plan did not know it had.

---

## Slice B — bank configuration

**Why second.** If the bank changes a transfer limit or a cutoff time, nobody can record it. The
profile, its versions and the accounts exist only because a seed created them.

Unblocked by the same decision: **`bank_profile.activate_version` to `business_admin`** — not the
accountant, because a profile version changes how *every* payment is built and the person who
creates payments should not change the rules they are built under.

| operation | note |
|---|---|
| `GET /bank-profiles`, `POST /bank-profiles` | |
| `GET /bank-accounts`, `POST /bank-accounts` | |
| `POST /bank-profile-versions/{id}/activate` | the grant arrives in slice A's migration |

**Care needed.** Activating a version is a state-guarded command with an `If-Match`. Check
`test_preconditions_have_a_source.py` before writing the screen: if the version read issues no
`ETag`, that gate will say so, and the fix belongs in the route rather than in the screen.

---

## Slice C — evidence links

**Why third.** Slice 4's payment confirmation offers *the reason evidence is unavailable* because
linking a file needs a browser nothing has built. Every confirmed payment therefore records an
excuse where it could record a document.

| operation |
|---|
| `POST /evidence-links` |
| `POST /evidence-links/{id}/replace` |
| `POST /evidence-links/{id}/void` |

**What it changes.** A file picker over the M4 file surface, and a link panel on the attempt
screen. The confirm-paid form then offers `primary_evidence_link_id` *or* the unavailable-reason,
which is what `evidence_policy_satisfied` has always meant.

---

## Slice D — the statement import, with a converter

**The owner's instruction, 2026-09-08:** assume the bank supplies an Excel file with the columns we
need. If it later does not, **a converter module maps the real input to the shape we expect** —
and that module is separate precisely so the day the format changes, only it changes.

| operation |
|---|
| `GET /bank-statements`, `POST /bank-statements` |
| `GET /bank-statements/{id}`, `GET /bank-statements/{id}/import-runs` |
| `POST /bank-statements/{id}/import-runs` |

**The converter is the point of this slice, not the screen.** Put it behind one named function with
one documented input shape, so a second bank — or the same bank after a change — is a new
implementation rather than an edit to the import path. The M11 screens plan already records the
bank question against slice 6; this replaces that record.

**Then the two recorded precondition gaps close**: `test_preconditions_have_a_source.py` lists
`POST /bank-statements` as having no read to take an `If-Match` from. Reading the routes while
building the screen is what will show whether that is still true — slice 5 recorded one of these
gaps against the wrong aggregate and slice 6 found it.

---

## Slice E — bundle segments and automatic matching

**Why last of the building slices.** The judgement it feeds — which bank row proves a claim — is
already reachable: slice 6 built the manual match surface. This adds the automatic candidates M8's
backend produces.

| operation |
|---|
| `GET /receipt-segments/{id}/matching-candidates` |
| `POST /receipt-segments/{id}/matching-candidates` |
| `POST /matching-candidates/{id}/accept-for-confirmation` |
| `POST /matching-candidates/{id}/reject` |
| `POST /bank-result-bundles/{id}/batch-links` |

**One decision belongs to the owner here**, and it is not urgent: whether a person should ever link
a result bundle to a batch by hand, or whether that stays the import path's job. Build the four
candidate operations; record the fifth with the question.

---

## Slice F — password recovery

**Left until last deliberately.** The route exists; what is missing is not a screen but a decision:
**how does a person receive a recovery token?** M3 left that to the operator. A form with nothing
to type into it is worse than no form.

| operation | blocked on |
|---|---|
| `POST /auth/admin/recover-password` | the owner deciding the delivery channel |

---

## What stays without a screen, permanently

Seven operations, and this list should not grow:

- `GET /health/live`, `/ready`, `/dependencies`, `/workers`
- `GET /operations/background-processing`, `/operations/release-evidence`
- `POST /center-profile/rename`

All are guarded by an operations token rather than a session — the caller is an operator with a
shell. `GET /reports/queue-summary` also stays: it is *superseded* rather than unbuilt, because the
dashboard reads `GET /queues`, which `report.read` does not gate and which therefore serves the
warehouse operator and the technical admin that report cannot.

---

## Three things this plan does not cover, and must not be mistaken for

**No screen has ever been driven against a live server by a person.** Every claim in the screens
phase rests on tests: structural checks, and an accessibility sweep that loads pages *with no
session*, so it sees their failure and empty states. Whether the flows work end to end is **M13's
question** and nothing here answers it.

**Statuses render as their raw codes.** `result_published` rather than a Persian phrase. This was
deliberate — the sixteen queues draw from eight tables with eight status vocabularies, and a
guessed translation of a financial state is a claim the software cannot support. Closing it needs
the state-names document, not a slice of screen work.

**The §27 design decisions are still open**: the brand name and logo, the final palette and whether
dark mode exists, and the Persian font with its licensing. The applications ship with defaults.

---

## Order, and why

A → B → C → D → E → F.

A first because it is the only one whose absence makes an error permanent. B second because a bank
that changes its rules currently stops the system. C third because it upgrades every confirmation
from an excuse to a document. D and E are throughput. F waits on a decision.

Each slice ends the way the screens slices did: negative controls with control 0 green first, the
full suite run the way the verifier invokes it, and the `NO_SCREEN` entries **deleted** rather than
edited.
