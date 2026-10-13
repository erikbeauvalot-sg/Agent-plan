// Tableau triable : un clic sur l'en-tête trie la colonne, un second inverse l'ordre ; l'en-tête annonce le
// tri (aria-sort). Nombres comparés comme nombres, textes selon le français.
import { useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  num?: boolean;
  value: (row: T) => string | number | null | undefined;
  render?: (row: T) => ReactNode;
}

const collator = new Intl.Collator("fr", { numeric: true, sensitivity: "base" });

export function sortRows<T>(rows: T[], col: Column<T> | undefined, dir: 1 | -1): T[] {
  if (!col) return rows;
  return [...rows].sort((a, b) => {
    const x = col.value(a);
    const y = col.value(b);
    if (x === y) return 0;
    if (x === null || x === undefined) return 1; // valeurs absentes en dernier, quel que soit le sens
    if (y === null || y === undefined) return -1;
    const c = typeof x === "number" && typeof y === "number" ? x - y : collator.compare(String(x), String(y));
    return c * dir;
  });
}

export function SortTable<T>({
  rows,
  columns,
  rowKey,
  initial,
  caption,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T, i: number) => string;
  initial?: { key: string; dir: 1 | -1 };
  caption?: string;
}) {
  const [sort, setSort] = useState(initial ?? { key: "", dir: 1 as 1 | -1 });
  const col = columns.find((c) => c.key === sort.key);
  const shown = sortRows(rows, col, sort.dir);
  return (
    <div className="table-wrap">
      <table>
        {caption && <caption className="visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => {
              const active = c.key === sort.key;
              return (
                <th
                  key={c.key}
                  className={c.num ? "num" : undefined}
                  aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                >
                  <button
                    type="button"
                    className="sort"
                    onClick={() => setSort({ key: c.key, dir: active ? (-sort.dir as 1 | -1) : c.num ? -1 : 1 })}
                  >
                    {c.label}
                    <span aria-hidden="true" className="sort-mark">
                      {active ? (sort.dir === 1 ? "▲" : "▼") : ""}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={rowKey(r, i)}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? "num" : undefined}>
                  {c.render ? c.render(r) : (c.value(r) ?? "–")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
