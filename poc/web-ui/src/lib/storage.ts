// Préférences du navigateur seulement (thème, dernier modèle, dernières données) : jamais de donnée sensible.

export const stored = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(`diagagent.${key}`);
    } catch {
      return null;
    }
  },
  set(key: string, value: string): void {
    try {
      localStorage.setItem(`diagagent.${key}`, value);
    } catch {
      // stockage indisponible (navigation privée) : la préférence n'est simplement pas retenue
    }
  },
};
