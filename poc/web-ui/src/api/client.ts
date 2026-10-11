// Appels à la passerelle : en-tête anti-falsification (X-Diagagent), erreurs lisibles, session expirée.

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};

/** Appelé quand la session est absente ou expirée (401) : l'application affiche la connexion. */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Diagagent": "1",
      ...(options.headers ?? {}),
    },
  });
  if (res.status === 401 && path !== "/api/login") {
    onUnauthorized();
    throw new ApiError("Session expirée", 401);
  }
  const body: unknown = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(typeof detail === "string" ? detail : `Erreur ${res.status}`, res.status);
  }
  return body as T;
}

export const post = <T>(path: string, body?: unknown): Promise<T> =>
  api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
