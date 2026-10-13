import { describe, expect, it } from "vitest";
import { parseAnswer } from "./answer";

describe("découpage de la réponse", () => {
  it("met la synthèse à part et lit la confiance de la cause probable", () => {
    const a = parseAnswer(
      "## Synthèse\nCHG0034567 a saturé le pool.\n\n## Chronologie\n- 21:50 : début\n\n## Cause probable\nConfiance : élevée\nLe pool…\n\n## Limites\nPas de logs DB.",
    );
    expect(a.summary).toBe("CHG0034567 a saturé le pool.");
    expect(a.sections.map((s) => s.title)).toEqual(["Chronologie", "Cause probable", "Limites"]);
    expect(a.confidence).toBe("élevée");
  });

  it("accepte une confiance écrite autrement et une réponse sans rubrique", () => {
    expect(parseAnswer("## Cause probable\nHypothèse retenue, confiance moyenne.").confidence).toBe("moyenne");
    const plain = parseAnswer("srv-pay-01 est CI0012345.");
    expect(plain).toEqual({ summary: "srv-pay-01 est CI0012345.", sections: [], confidence: null });
  });
});
