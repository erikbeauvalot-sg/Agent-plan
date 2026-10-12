// Recherche floue de la palette : les lettres tapées apparaissent dans l'ordre, sans casse ni accents ;
// un début de mot ou une suite de lettres collées comptent plus qu'une lettre isolée.

export const fold = (s: string): string => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Score de `query` dans `text` (plus haut = meilleur), ou null si les lettres n'y sont pas dans l'ordre. */
export function fuzzyScore(query: string, text: string): number | null {
  const q = fold(query).replace(/\s+/g, "");
  if (!q) return 0;
  const t = fold(text);
  let score = 0;
  let from = 0;
  let prev = -2;
  for (const ch of q) {
    const i = t.indexOf(ch, from);
    if (i < 0) return null;
    score += 1;
    if (i === prev + 1) score += 2; // lettres consécutives
    if (i === 0 || /[\s\-_/.:«(]/.test(t[i - 1] ?? "")) score += 3; // début de mot
    prev = i;
    from = i + 1;
  }
  if (t.includes(fold(query).trim())) score += 5; // la saisie telle quelle
  return score - t.length / 100; // à score égal, le texte le plus court
}

export function fuzzyFilter<T>(items: T[], query: string, text: (item: T) => string): T[] {
  if (!query.trim()) return items;
  return items
    .map((item, i) => ({ item, i, s: fuzzyScore(query, text(item)) }))
    .filter((x): x is { item: T; i: number; s: number } => x.s !== null)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.item);
}
