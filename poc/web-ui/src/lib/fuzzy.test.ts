import { describe, expect, it } from "vitest";
import { fuzzyFilter, fuzzyScore } from "./fuzzy";

describe("recherche floue", () => {
  it("trouve les lettres dans l'ordre, sans casse ni accents", () => {
    expect(fuzzyScore("adm", "Administration")).not.toBeNull();
    expect(fuzzyScore("theme", "Thème sombre")).not.toBeNull();
    expect(fuzzyScore("xyz", "Administration")).toBeNull();
  });

  it("classe le début de mot et la saisie exacte en premier", () => {
    const items = ["Lenteurs sur srv-pay-01", "Thème clair", "Paiement lent depuis hier"];
    expect(fuzzyFilter(items, "pay", (s) => s)[0]).toBe("Lenteurs sur srv-pay-01");
    expect(fuzzyFilter(items, "", (s) => s)).toEqual(items);
  });
});
