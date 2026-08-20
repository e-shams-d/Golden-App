"""Turning eligible requests into the rows a bank file will carry.

M6. The splitting engine lives here and takes no database session, because the rules it
applies are a *version* of a bank profile rather than the current state of one — the
preview an accountant saw last week must still be reproducible from the version it named.
"""
