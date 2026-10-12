// Popover ancré sous son bouton : options de la question, filtres de l'historique, menu du compte.
// Échap ou un clic ailleurs le ferment et rendent le focus au bouton ; les flèches parcourent ses choix.
import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronDown, X } from "./icons";

export function usePopover() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);
  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  };
  return { open, setOpen, close, rootRef, triggerRef };
}

/** Flèches haut et bas entre les éléments activables du menu. */
export function onMenuKeys(e: React.KeyboardEvent<HTMLElement>) {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const items = [...e.currentTarget.querySelectorAll<HTMLElement>("[data-item]:not(:disabled)")];
  if (!items.length) return;
  e.preventDefault();
  const i = items.indexOf(document.activeElement as HTMLElement);
  const next = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
  items[next]?.focus();
}

export interface ChipOption {
  value: string;
  label: string;
  disabled?: boolean;
  hint?: string | null;
}

interface ChipProps {
  label: string;
  /** Valeur affichée sur la puce ; vide = puce inactive (valeur par défaut). */
  display: string;
  options?: ChipOption[];
  selected?: string[];
  multiple?: boolean;
  onSelect?: (value: string) => void;
  onClear?: () => void;
  active?: boolean;
  children?: ReactNode;
}

/** Puce « Libellé : valeur ▾ » qui ouvre un choix (simple ou multiple) ou un contenu libre. */
export function ChipSelect({
  label,
  display,
  options,
  selected = [],
  multiple,
  onSelect,
  onClear,
  active,
  children,
}: ChipProps) {
  const { open, setOpen, close, rootRef, triggerRef } = usePopover();
  const id = useId();
  // Ouverture : focus sur le choix courant, sinon le premier.
  useEffect(() => {
    if (!open) return;
    const menu = document.getElementById(id);
    (
      menu?.querySelector<HTMLElement>('[aria-checked="true"]') ?? menu?.querySelector<HTMLElement>("[data-item]")
    )?.focus();
  }, [open, id]);
  return (
    <div className="chip-wrap" ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className="chip"
        data-active={active ? "" : undefined}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        <span className="chip-label">{label}</span>
        {display && <strong>{display}</strong>}
        <ChevronDown size={13} aria-hidden="true" />
      </button>
      {active && onClear && (
        <button type="button" className="chip-clear" aria-label={`Retirer le filtre ${label}`} onClick={onClear}>
          <X size={12} aria-hidden="true" />
        </button>
      )}
      {open && (
        <div className="chip-menu" id={id} role="menu" aria-label={label} onKeyDown={onMenuKeys}>
          {options?.map((o) => (
            <button
              key={o.value}
              type="button"
              role={multiple ? "menuitemcheckbox" : "menuitemradio"}
              aria-checked={selected.includes(o.value)}
              data-item=""
              disabled={o.disabled}
              title={o.hint ?? undefined}
              onClick={() => {
                onSelect?.(o.value);
                if (!multiple) close();
              }}
            >
              <span className="tick" aria-hidden="true" />
              <span>{o.label}</span>
              {o.hint && <span className="faint">{o.hint}</span>}
            </button>
          ))}
          <CloseContext.Provider value={close}>{children}</CloseContext.Provider>
        </div>
      )}
    </div>
  );
}

const CloseContext = createContext<(refocus?: boolean) => void>(() => {});

/** Ferme le popover qui contient ce composant (contenu libre d'une puce : dates, host). */
export const useClosePopover = () => useContext(CloseContext);
