// État d'une investigation ou d'une source : couleur, icône et libellé ensemble (jamais la couleur seule).
import { CircleCheck, CircleHelp, CircleSlash, CircleX, HalfCircle, LoaderCircle, Square } from "./icons";
import { statusLabel } from "../lib/format";

const ICONS = {
  running: LoaderCircle,
  stopping: Square,
  completed: CircleCheck,
  partial: HalfCircle,
  stopped: Square,
  failed: CircleX,
  needs_clarification: CircleHelp,
  ok: CircleCheck,
  bad: CircleX,
  off: CircleSlash,
} as const;

export type BadgeState = keyof typeof ICONS;

export function StateBadge({
  state,
  label,
  hideLabel = false,
}: {
  state: string;
  label?: string;
  hideLabel?: boolean;
}) {
  const key = (state in ICONS ? state : "off") as BadgeState;
  const Icon = ICONS[key];
  const text = label ?? statusLabel(state);
  return (
    <span className="state" data-state={key} title={hideLabel ? text : undefined}>
      <Icon size={14} strokeWidth={1.75} className={key === "running" ? "spin" : undefined} aria-hidden="true" />
      {hideLabel ? <span className="visually-hidden">{text}</span> : text}
    </span>
  );
}
