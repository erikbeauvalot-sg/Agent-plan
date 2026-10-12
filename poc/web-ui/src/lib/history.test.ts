import { describe, expect, it } from "vitest";
import { apiQuery, filtersFromHash, filtersToHash, hasFilters, NO_FILTERS } from "./history";

describe("filtres de l'historique", () => {
  it("font l'aller-retour par l'adresse", () => {
    const f = {
      ...NO_FILTERS,
      period: "7j" as const,
      category: "performance",
      status: ["completed", "partial"],
      q: "lent",
    };
    const hash = filtersToHash(f);
    expect(hash).toBe("#?periode=7j&categorie=performance&statut=completed,partial&q=lent");
    expect(filtersFromHash(hash)).toEqual(f);
    expect(filtersToHash(NO_FILTERS)).toBe("#");
    expect(hasFilters(NO_FILTERS)).toBe(false);
  });

  it("ignorent une adresse qui n'est pas un filtre et les valeurs invalides", () => {
    expect(filtersFromHash("#20261011T172737Z-b959")).toEqual(NO_FILTERS);
    expect(filtersFromHash("#?periode=hier&du=demain").period).toBe("");
    expect(filtersFromHash("#?periode=dates&du=demain").since).toBe("");
  });

  it("se traduisent en paramètres de l'API", () => {
    const now = new Date("2026-10-12T08:00:00Z");
    expect(apiQuery({ ...NO_FILTERS, period: "7j" }, now).toString()).toBe("since=2026-10-06");
    expect(apiQuery({ ...NO_FILTERS, period: "jour" }, now).get("since")).toBe("2026-10-12");
    const dates = apiQuery(
      { ...NO_FILTERS, period: "dates", since: "2026-10-01", until: "2026-10-03", host: " pay " },
      now,
    );
    expect(Object.fromEntries(dates)).toEqual({ since: "2026-10-01", until: "2026-10-03", host: "pay" });
  });
});
