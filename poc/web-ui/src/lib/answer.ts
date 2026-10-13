// Réponse de l'agent principal découpée en rubriques (## Synthèse, ## Cause probable…) pour la révéler dans
// l'ordre utile : la synthèse d'abord, en grand, avec le niveau de confiance ; le reste ensuite.

export interface AnswerSection {
  title: string;
  body: string;
}

export interface ParsedAnswer {
  /** Texte avant la première rubrique (rare) et rubrique Synthèse. */
  summary: string;
  sections: AnswerSection[];
  confidence: "faible" | "moyenne" | "élevée" | null;
}

const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

/** Rubriques déjà affichées ailleurs dans la page (les actions ont leurs cartes) : gardées, mais repliées. */
export const FOLDED = ["actions proposees", "actions proposees (non executees)"];

export function parseAnswer(text: string): ParsedAnswer {
  const parts = text.split(/^##\s+/m);
  const head = parts.shift()?.trim() ?? "";
  const sections: AnswerSection[] = parts.map((p) => {
    const [title = "", ...body] = p.split("\n");
    return { title: title.trim(), body: body.join("\n").trim() };
  });
  const i = sections.findIndex((s) => fold(s.title).startsWith("synthese"));
  const summary = [head, i >= 0 ? sections[i]!.body : ""].filter(Boolean).join("\n\n");
  if (i >= 0) sections.splice(i, 1);
  const cause = sections.find((s) => fold(s.title).startsWith("cause"));
  const m = (cause?.body ?? text).match(/confiance\s*:?\s*(faible|moyenne|[ée]lev[ée]e)/i);
  const level = m ? fold(m[1]!) : null;
  const confidence = level === "faible" ? "faible" : level === "moyenne" ? "moyenne" : level ? "élevée" : null;
  return { summary, sections, confidence };
}
