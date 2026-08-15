"""The private-file service: the one place that knows a storage address.

M4's Definition of Done says every later module must be able to reference a stable
`FileObject` "without directly handling storage paths". That is a boundary, and this
package is the inside of it — `app/storage/` holds the backend, this package holds the
commands and policy that use it, and nothing else in `app/` imports either. Slice 11's
gate enforces exactly that, with an allowlist of the two modules that legitimately touch
the backend for other reasons: the runtime container that constructs it and the health
probe that pings it.
"""
