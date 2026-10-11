// Confirmation d'une action à portée importante (arrêt d'un agent, de l'investigation) : <dialog> natif,
// focus piégé, Échap annule, le focus revient sur l'élément d'origine.
import { useCallback, useRef, useState, type ReactNode } from "react";

interface Pending {
  title: string;
  body: ReactNode;
  confirm: string;
  danger?: boolean;
  resolve: (ok: boolean) => void;
}

export function useConfirm(): [ReactNode, (p: Omit<Pending, "resolve">) => Promise<boolean>] {
  const ref = useRef<HTMLDialogElement>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const origin = useRef<Element | null>(null);

  const ask = useCallback((p: Omit<Pending, "resolve">) => {
    origin.current = document.activeElement;
    return new Promise<boolean>((resolve) => {
      setPending({ ...p, resolve });
      requestAnimationFrame(() => ref.current?.showModal());
    });
  }, []);

  const close = (ok: boolean) => {
    pending?.resolve(ok);
    ref.current?.close();
    setPending(null);
    (origin.current as HTMLElement | null)?.focus?.();
  };

  const element = (
    <dialog ref={ref} className="dialog" onCancel={() => close(false)} aria-labelledby="confirm-title">
      {pending && (
        <form method="dialog" onSubmit={(e) => (e.preventDefault(), close(true))}>
          <h2 id="confirm-title">{pending.title}</h2>
          <div className="muted">{pending.body}</div>
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={() => close(false)} autoFocus>
              Annuler
            </button>
            <button type="submit" className={`btn ${pending.danger ? "danger" : "primary"}`}>
              {pending.confirm}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
  return [element, ask];
}
