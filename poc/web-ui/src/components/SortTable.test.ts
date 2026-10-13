import { describe, expect, it } from "vitest";
import { sortRows, type Column } from "./SortTable";

type Row = { name: string; runs: number | null };
const name: Column<Row> = { key: "name", label: "Nom", value: (r) => r.name };
const runs: Column<Row> = { key: "runs", label: "Investigations", num: true, value: (r) => r.runs };
const rows: Row[] = [
  { name: "Étienne", runs: 3 },
  { name: "alice", runs: null },
  { name: "bob", runs: 12 },
];

describe("tri des tableaux", () => {
  it("trie les textes selon le français et les nombres comme des nombres", () => {
    expect(sortRows(rows, name, 1).map((r) => r.name)).toEqual(["alice", "bob", "Étienne"]);
    expect(sortRows(rows, runs, -1).map((r) => r.runs)).toEqual([12, 3, null]);
    expect(sortRows(rows, runs, 1).map((r) => r.runs)).toEqual([3, 12, null]); // absents toujours en dernier
    expect(sortRows(rows, undefined, 1)).toBe(rows);
  });
});
