"""What a technical administrator may see, and what they may not.
`15_Agent_Implementation_Plan.md:1289`.

M11 slice 5. §19.2 names six technical queues, less `ai-status` which the document admits "only
when enabled" and no AI path exists to enable. **One is built here and four are blocked** — see
`app/queues/registry.py`'s `BLOCKED`.

That ratio is the slice's finding, and it is not a shortfall. Two things are missing, and they are
different things:

- **`failed-jobs` and `stale-outbox-records` have no session permission** — the catalogue holds
  none for jobs or outbox records — and the surface that already serves them,
  `GET /operations/background-processing`, is guarded by an **operations token** rather than a
  session. Building session-guarded twins would either need an invented permission or would
  duplicate an existing surface under weaker authority.
- **`storage-reconciliation` and `backup-health-warnings` have no table at all.** There is no
  mapped model for either, so there are no rows for a predicate to select. `backup_status.read`
  exists as a grant, which is the tell: M0 approved who may look before anything was built to look
  at.

Neither is unblocked by trying harder, which is why both are recorded rather than approximated.

**§19 `:1298`'s last rule is this slice's whole subject**: "technical admin does not receive full
financial detail by default." It is not a filter added on top of these queues — it is the reason
they draw from the tables they do and are guarded by the grants they are.

The catalogue says it too, in the grant itself: `file.quarantine_review` carries
`assignment: financial_content_access_is_not_implied` (`permission_catalog.yaml:677`), and
`backup_status.read` carries `read_only_masked`. Doc 12 `:616` describes `technical_admin` as
having "no implicit financial authority" and `:664` lists what the role does not automatically
receive. So the redaction is not this module's invention; it is three approved documents agreeing,
and `SEC-QUEUE-003` asserts it over the **response body** rather than over the query — a redaction
applied after serialisation is one a later serialiser change removes silently.

**`trader_id` is `None` on every row here**, and that is the concrete form the rule takes. The
queue is about an *artefact* — a file that failed a scan — and naming whose business it belongs to
would tell a technical administrator which trader is having trouble, which is exactly the financial
detail the grant withholds. `file_objects` carries no `trader_id` column either, so the omission is
enforced by the table as well as by the renderer.
"""

from __future__ import annotations

from sqlalchemy import Select

from app.db.models.file_object import FileObject
from app.db.pagination import ListSpec, SortField
from app.queues.contract import QueueDefinition, QueueRow
from app.security.actor import ActorContext

# `file_objects.scan_status`. A file the scanner rejected, or could not finish.
SCAN_QUARANTINED = "quarantined"



def _internal[T](statement: Select[tuple[T]], actor: ActorContext) -> Select[tuple[T]]:
    """No trader reaches these, so there is nobody to scope.

    `file.quarantine_review` and `backup_status.read` are `technical_admin`'s (the second shared
    with `read_only_auditor`), and no trader role holds either.
    """

    del actor
    return statement


def _quarantined_file(
    statement: Select[tuple[FileObject]], actor: ActorContext
) -> Select[tuple[FileObject]]:
    """§19.2's "quarantined files/exports", the file half.

    A quarantined file is one the scanner would not clear, and ADR-008's interim rule is that an
    unchecked file is never treated as available evidence. The queue is the work of deciding what
    to do with each — which is what `file.quarantine_review` names.

    `clean` and `pending` are excluded: one is answered and the other is the scanner's work rather
    than a person's.
    """

    return _internal(statement, actor).where(FileObject.scan_status == SCAN_QUARANTINED)


def _render_file(row: FileObject) -> QueueRow:
    """**The filename, not the contents, and no trader.**

    `original_filename` is what a technical administrator needs to find the file in storage, and it
    is metadata the `technical_metadata_only` conditional grant at `permission_catalog.yaml:485`
    already contemplates. `category` and `size_bytes` are deliberately absent — the row shape has
    nowhere for them, which is the point of one shape for twenty-four queues.
    """

    return QueueRow(
        id=row.id,
        reference=row.original_filename,
        status=row.scan_status,
        created_at=row.created_at,
        # Never the owner. A file belongs to a business, and saying which one would tell a
        # technical administrator whose evidence failed a scan.
        trader_id=None,
    )


QUARANTINED_FILES: QueueDefinition[FileObject] = QueueDefinition(
    name="quarantined-files-exports",
    permission="file.quarantine_review",
    spec=ListSpec(
        sorts=(
            SortField("created_at", FileObject.created_at),
            SortField("id", FileObject.id, unique=True),
        ),
        default_sort="created_at",
    ),
    predicate=_quarantined_file,
    source="15_Agent_Implementation_Plan.md:1293",
    entity=FileObject,
    render=_render_file,
)


# --- The export half of §19.2's phrase, and why it is not a second queue -------------------
#
# §19.2 writes "quarantined files/exports" as one line, and two tables cannot be one query without
# a union this contract's `entity` cannot express. The first draft of this module built a second
# queue named `quarantined-exports` — which is **not a name §19.2 gives**, and adding it would have
# made the registry's own invariant (BUILT | PLANNED | BLOCKED equals the document's list) false by
# one, quietly, in the direction nobody checks.
#
# It is also unnecessary. A quarantined export already reaches a person: M7's integrity check opens
# a `manual_review_tasks` row with `task_type = 'bank_export_integrity'`, which is a value the
# approved catalogue has held since M0 and which M8 slice 3 built the surface for. A second queue
# over `bank_excel_exports.status = 'quarantined'` would be a different route to the same work,
# and two lists of one thing is how one of them stops being read.
#
# So this queue is the files, under §19.2's own name, and the exports are where they already are.
