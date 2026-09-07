"""Control 3: the trader bundle learns the centre's matching path.

`permission_catalog.yaml` gives a trader neither `incoming_payment.match` nor
`incoming_receipt.read`, and the reason is not only authorisation: which bank row proves a claim is
the centre's judgement, and a trader who could propose one would be deciding their own case.

The server refuses. **The point is that the path should not be in that bundle to try** — the same
argument `UI-ISO-001` makes everywhere, and the strongest instance of it in this application.

Written as the helpful-looking version: let a trader see which candidates the centre is
considering, so they can chase it up.
"""

import pathlib

MODULE = pathlib.Path("apps/trader-pwa/src/incoming-receipts.ts")

ADDITION = """

export async function listMatches(receiptId: string): Promise<readonly unknown[]> {
  const response = await transport.request<readonly unknown[]>({
    method: "GET",
    path: `/incoming-payment-receipts/${receiptId}/matches`,
  });
  return response.data;
}
"""

text = MODULE.read_text(encoding="utf-8")
assert "/matches" not in text, "the trader module already names the matching path"

MODULE.write_text(text + ADDITION, encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "/matches`" in after, "THE EDIT DID NOT LAND"
print("control 3 applied: the trader bundle names the matching path")
