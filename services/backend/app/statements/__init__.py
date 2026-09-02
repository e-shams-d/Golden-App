"""Reading a bank's statement file. `08_Bank_File_and_Result_Processing.md` §8.

Separate from `app/exports/`, which writes files a bank reads. This reads files a bank wrote, and
the two have opposite failure modes: an export that is wrong produces a bad payment, an import that
is wrong produces a wrong belief about money that already moved.
"""
