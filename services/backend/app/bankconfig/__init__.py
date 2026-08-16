"""Reading bank configuration, and the only way to do it.

M4's Definition of Done requires that "every later module can reference ... a stable bank
configuration version without directly handling ... mutable bank settings". Half of that
is already structural: `bank_profiles` carries `code`, `name`, `status` and a pointer, and
every operational rule lives on an immutable version row. This package is the other half —
the boundary that keeps it true at the service level.

**Nothing here returns an operational value without its version id.** There is no
`get_transfer_limit(profile_id)`, deliberately: a caller holding a limit without the
version it came from cannot reproduce the decision it made, and reproducing a decision is
the entire reason bank configuration is versioned. Slice 11's gate asserts the absence.
"""
