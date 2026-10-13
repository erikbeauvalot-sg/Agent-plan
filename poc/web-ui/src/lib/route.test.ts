import { describe, expect, it } from "vitest";
import { parseRoute } from "./route";

describe("routage par fragment", () => {
  it("reconnaît les vues, dont le lien d'activation", () => {
    expect(parseRoute("#20261011T172737Z-b959")).toEqual({ view: "run", runId: "20261011T172737Z-b959" });
    expect(parseRoute("#admin")).toEqual({ view: "admin" });
    const token = "AbC_def-123456789012345678901234567890";
    expect(parseRoute(`#activation/${token}`)).toEqual({ view: "activation", token });
    expect(parseRoute("#activation/court")).toEqual({ view: "home" });
    expect(parseRoute("#?periode=7j")).toEqual({ view: "home" });
  });
});
