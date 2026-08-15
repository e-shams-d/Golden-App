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

  it("types a binary upload field as Blob and keeps responses JSON-only", async () => {
    // OpenAPI 3.1 dropped `format: binary`, so a multipart file field arrives as
    // `{"type": "string", "contentMediaType": ...}`. Emitting `string` would be worse
    // than refusing the keyword: a caller would reasonably pass a filename and get a
    // green type check followed by a runtime failure.
    const fixture = await readFixture();
    fixture.paths["/api/v1/widgets/{widget_id}"].post.requestBody = {
      required: true,
      content: {
        "multipart/form-data": {
          schema: {
            type: "object",
            required: ["file"],
            properties: {
              file: { type: "string", contentMediaType: "application/octet-stream" },
              purpose: { type: "string" },
            },
          },
        },
      },
    };

    const generated = renderTypesFromSchema(fixture);
    expect(generated).toContain("file: Blob");
    expect(generated).toContain('"multipart/form-data"');

    // A response may not be multipart. The transport parses every reply as JSON and
    // refuses any other media type, so a typed method returning multipart could not read
    // its own answer. Slice 5's download route needs a deliberate decision rather than
    // this exception widened by accident.
    const responseSide = await readFixture();
    responseSide.paths["/api/v1/widgets/{widget_id}"].post.responses["200"] = {
      description: "Bytes.",
      content: { "multipart/form-data": { schema: { type: "string" } } },
    };
    expect(() => renderTypesFromSchema(responseSide)).toThrow(
      /unsupported media type multipart\/form-data/,
    );
  });

  it("refuses a content encoding rather than guessing what to send", async () => {
    // `contentEncoding: base64` describes a string, not a Blob. Choosing either silently
    // produces a client that sends the wrong thing, so the generator stops instead.
    const fixture = await readFixture();
    fixture.paths["/api/v1/widgets/{widget_id}"].post.requestBody = {
      required: true,
      content: {
        "multipart/form-data": {
          schema: {
            type: "object",
            required: ["file"],
            properties: {
              file: {
                type: "string",
                contentMediaType: "application/octet-stream",
                contentEncoding: "base64",
              },
            },
          },
        },
      },
    };

    expect(() => renderTypesFromSchema(fixture)).toThrow(/contentEncoding is not supported/);
  });
});
