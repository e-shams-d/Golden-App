"""Control 2: the publish command asks for a recent-auth step-up.

This is the sabotage that reproduces **the obligation's original wording**, which is why it is
worth a control rather than a comment: `UI-RESULT-001` first said "the publish button requires the
recent-auth dialog §8.11 specifies", and a screen written to satisfy that sentence would look more
careful, not less.

`command_catalog.yaml` puts `recent_auth: "required_for_approving_second_human"` on the publication
*correction* and no such field on the publish. So the header would be ignored by the server and the
dialog would be a ritual — and the harm is a habit rather than a bug: somebody taught to
reauthenticate whenever a screen asks will do it for the screen that should not have asked.
"""

import pathlib

MODULE = pathlib.Path("apps/admin-web/src/payment-results.ts")

BEFORE = """    idempotencyKey: commandKey(),
    ifMatch,
  });
  return response.data;
}

/**
 * Every publication for a request, superseded ones included."""

AFTER = """    idempotencyKey: commandKey(),
    ifMatch,
    recentAuthToken: "step-up-context",
  });
  return response.data;
}

/**
 * Every publication for a request, superseded ones included."""

text = MODULE.read_text(encoding="utf-8")
assert BEFORE in text, "the publish call is no longer written this way; this control does not apply"
assert "recentAuthToken" not in text, "already applied"

MODULE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "recentAuthToken:" in after, "THE EDIT DID NOT LAND"
print("control 2 applied: publish now sends a step-up token")
