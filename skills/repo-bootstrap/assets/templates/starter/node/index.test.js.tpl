import test from "node:test";
import assert from "node:assert/strict";
import { main } from "../src/index.js";

test("returns the application name", () => {
  assert.equal(main(), "{{PROJECT_NAME}}");
});
