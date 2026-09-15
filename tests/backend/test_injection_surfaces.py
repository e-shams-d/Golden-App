"""Two protections that exist and had no test: escaping in the browser, and log-line structure.

M12 slice 5. §20.2 lists "XSS and log-injection tests" and the survey found neither.

**Both controls are real; neither was asserted.** React escapes interpolated text by default, and
`app/core/logging.py:89` emits one JSON object per line. So this file is not closing a hole — it is
making two properties that happen to be true into properties that stay true. The day somebody adds
`dangerouslySetInnerHTML` to render a bank's message, or replaces a structured log call with an
f-string, nothing else in this repository would notice.

## Why these two, and why they matter here

The admin panel renders **operator-supplied and bank-supplied** strings: bundle notes, rejection
reasons, beneficiary names, a bank's own failure text. A trader chooses their display name. None of
it is trusted input, and all of it reaches a screen.

The logs are read during an incident, by a person deciding whether money moved. `incident.md`'s
first instruction is to read the audit trail and then the logs, and a value that could inject a
newline could fabricate a log line — an attacker's claim indistinguishable from the platform's.

Covers: SEC-XSS-001, SEC-LOGINJ-001.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.core.logging import JsonFormatter, redact_text, sanitize_log_value

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APPS = REPOSITORY_ROOT / "apps"
PACKAGES = REPOSITORY_ROOT / "packages"


def frontend_sources() -> list[Path]:
    found: list[Path] = []
    for root in (APPS, PACKAGES):
        for path in root.rglob("*.ts*"):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            found.append(path)
    return found


def test_nothing_renders_unescaped_html() -> None:
    """`dangerouslySetInnerHTML` is React's own name for the decision, and nothing takes it.

    **The escape is the whole defence.** There is no sanitiser in this codebase and there should not
    be one: a sanitiser is a list of things somebody thought of, and React's default is a rule with
    no list. Reaching for `dangerouslySetInnerHTML` is what would replace the second with the first.
    """

    offenders = [
        f"{path.relative_to(REPOSITORY_ROOT)}"
        for path in frontend_sources()
        if "dangerouslySetInnerHTML" in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], (
        f"these render unescaped HTML: {offenders}. The admin panel shows operator-supplied and "
        "bank-supplied strings — bundle notes, rejection reasons, a bank's own failure text — and "
        "React's default escaping is the only thing between those and a script tag."
    )


def test_nothing_writes_to_innerhtml_directly() -> None:
    """The same hole reached without React's warning label.

    `element.innerHTML = value` bypasses the framework entirely, and carries no name that makes a
    reviewer stop. `crop-canvas.tsx` manipulates DOM geometry, which is exactly the kind of file
    where this appears for a reason that seemed good at the time.
    """

    pattern = re.compile(r"\.innerHTML\s*=|insertAdjacentHTML|outerHTML\s*=")
    offenders = [
        f"{path.relative_to(REPOSITORY_ROOT)}"
        for path in frontend_sources()
        if pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"these write HTML directly into the DOM: {offenders}"


def test_a_newline_in_a_logged_value_cannot_forge_a_log_line() -> None:
    """**The log-injection property, asserted on the output rather than on the design.**

    One record must produce one line. A value carrying `\\n` would otherwise let anything that
    reaches a log field — a beneficiary name, a rejection reason, a bank's failure text — write what
    looks like a second log entry, at whatever level and with whatever message it chooses. An
    incident is then read from a file containing an attacker's sentences.

    `json.dumps` escapes the newline; this asserts that it is *still* doing so, which is the part a
    refactor to f-string logging would silently lose.
    """

    forged = 'ok"}\n{"level":"ERROR","message":"payment reversed by admin'
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="an ordinary message", args=(), exc_info=None,
    )
    record.event_data = sanitize_log_value({"beneficiary_name": forged})

    line = JsonFormatter().format(record)

    assert "\n" not in line, (
        "a logged value put a newline into the output, so one record produced two lines and the "
        "second is whatever the value said"
    )
    # And the escaped text survives as *data*, which is the other half: a defence that dropped the
    # value would lose the evidence of the attempt.
    parsed = json.loads(line)
    assert parsed["beneficiary_name"] == forged
    assert parsed["level"] == "INFO", "the forged level reached the parsed record"


def test_a_control_character_cannot_break_the_line_either() -> None:
    """Carriage return and the ANSI escape, which newline-only checks miss.

    `\\r` alone rewrites a terminal line, so a log tailed in a console can be made to show
    something other than what was written — without ever containing a newline.
    """

    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="ordinary", args=(), exc_info=None,
    )
    record.event_data = sanitize_log_value({"note": "before\r\x1b[2Kafter\u2028also"})

    line = JsonFormatter().format(record)

    for character in ("\n", "\r", "\u2028", "\u2029"):
        assert character not in line, f"{character!r} reached the log output unescaped"


def test_the_message_itself_is_redacted_not_only_the_fields() -> None:
    """A secret interpolated into the message text, rather than passed as a field.

    `log_event` sanitises `**fields`; the message is a separate path through
    `JsonFormatter.format`, and it is the one somebody uses when they are in a hurry.
    """

    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="connecting to postgresql://gold:hunter2@db:5432/x", args=(), exc_info=None,
    )

    line = JsonFormatter().format(record)

    assert "hunter2" not in line, "a credential in the message text reached the log"
    assert "[REDACTED]" in line


def test_an_iban_in_free_text_is_masked() -> None:
    """POL-003 is open and its safe default is least disclosure.

    A bank's own failure text carries IBANs routinely, and that text is logged when an import
    fails — the moment somebody is most likely to paste a log into a chat window.
    """

    masked = redact_text("transfer to IR060120000000000000000066 failed")

    assert "IR060120000000000000000066" not in masked
    assert "[REDACTED]" in masked
