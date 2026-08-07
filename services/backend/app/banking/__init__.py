"""Bank configuration support that is not schema.

Only the identifier allowlist so far. The importers and exporters that consume a
mapping arrive in M4, M6 and M7; the guard they must use exists first so that the
first one written does not solve it inline.
"""
