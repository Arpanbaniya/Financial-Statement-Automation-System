import assert from "node:assert/strict";
import test from "node:test";
import {
  metricSourceCurrency,
  metricSourceLinks,
} from "./metric-provenance.ts";

const statements = new Map([
  [
    "statement-1",
    { id: "statement-1", document_id: "document-1", currency: "USD" },
  ],
]);

test("source links lead to the exact accepted line", () => {
  const metadata = {
    source_refs: [{ statement_id: "statement-1", line_item_id: "line-2" }],
  };
  assert.deepEqual(metricSourceLinks(metadata, statements), [
    {
      href: "/dashboard/documents/document-1#line-line-2",
      label: "Source line 1",
    },
  ]);
  assert.equal(metricSourceCurrency(metadata, statements), "USD");
});

test("unresolved references do not produce misleading links", () => {
  const metadata = {
    source_refs: [
      { statement_id: "other-user-statement", line_item_id: "line-2" },
    ],
  };
  assert.deepEqual(metricSourceLinks(metadata, statements), []);
  assert.equal(metricSourceCurrency(metadata, statements), null);
});
