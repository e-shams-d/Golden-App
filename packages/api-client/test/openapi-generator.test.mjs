import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

import { renderTypesFromSchema } from "../scripts/openapi-contract.mjs";

const fixtureUrl = new URL("./fixtures/openapi-generator.json", import.meta.url);

async function readFixture() {
  return JSON.parse(await readFile(fixtureUrl, "utf8"));
}

function reverseObject(value) {
  if (Array.isArray(value)) return value.map(reverseObject);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value)
      .reverse()
      .map(([key, member]) => [key, reverseObject(member)]),
  );
}

describe("local OpenAPI generator", () => {
  it("models path-level parameters and optional groups deterministically", async () => {
    const fixture = await readFixture();
    const generated = renderTypesFromSchema(fixture);

    expect(renderTypesFromSchema(reverseObject(fixture))).toBe(generated);
    expect(generated).toContain(
      'parameters: { header?: { "X-Trace"?: string | null }; path: { widget_id: string }; query?: { include_history?: boolean } }',
    );
    expect(generated).toContain(
      "parameters: { path: { widget_id: string }; query: { validate_only: boolean } }",
    );
    expect(generated).toContain(
      'requestBody: { content: { "application/json": components["schemas"]["Widget"] } }',
    );
    expect(generated).toContain(
      'security: Array<{ FixtureToken: Array<never> }>',
    );
    expect(generated).toContain('"204": { content: never }');
  });

  it("fails closed for unsupported schema constructs", async () => {
    const fixture = await readFixture();
    fixture.components.schemas.Widget.not = { type: "null" };

    expect(() => renderTypesFromSchema(fixture)).toThrow(
      "Unsupported OpenAPI schema keyword(s): not",
    );
  });

  it("fails closed for transport-unsafe response contracts", async () => {
    const withHeaders = await readFixture();
    withHeaders.paths["/api/v1/widgets/{widget_id}"].get.responses[
      "200"
    ].headers = {
      "X-Widget-Version": {
        schema: { type: "string" },
      },
    };
    expect(() => renderTypesFromSchema(withHeaders)).toThrow(
      "contains unsupported key(s): headers",
    );

    const withUnsupportedMedia = await readFixture();
    const response =
      withUnsupportedMedia.paths["/api/v1/widgets/{widget_id}"].get.responses[
        "200"
      ];
    response.content["text/plain"] = { schema: { type: "string" } };
    expect(() => renderTypesFromSchema(withUnsupportedMedia)).toThrow(
      "uses unsupported media type text/plain",
    );

    const withInt64 = await readFixture();
    withInt64.components.schemas.Widget.properties.sequence = {
      format: "int64",
      type: "integer",
    };
    expect(() => renderTypesFromSchema(withInt64)).toThrow(
      "int64 cannot be represented safely",
    );
  });

  it("rejects invalid path parameters and duplicate operation ids", async () => {
    const fixture = await readFixture();
    fixture.paths["/api/v1/widgets/{widget_id}"].parameters[0].required = false;
    expect(() => renderTypesFromSchema(fixture)).toThrow(
      "Path parameter widget_id must be required.",
    );

    const duplicate = await readFixture();
    duplicate.paths["/api/v1/widgets/{widget_id}"].post.operationId = "getWidget";
    expect(() => renderTypesFromSchema(duplicate)).toThrow(
      "Duplicate operationId: getWidget",
    );
  });
});
