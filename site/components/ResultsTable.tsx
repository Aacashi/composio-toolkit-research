"use client";

import { Fragment, useMemo, useState } from "react";

export type Row = {
  app_name: string;
  category?: string;
  business_type?: string;
  access_tier?: string;
  access_tier_rollup?: string;
  buildability?: string;
  auth_primary?: string;
  auth_detail?: string;
  blocker?: string;
  flags?: string[];
  evidence?: Record<string, string>;
};

const FILTERS = ["business_type", "access_tier", "access_tier_rollup", "buildability", "auth_primary"] as const;

export function ResultsTable({ rows }: { rows: Row[] }) {
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sortKey, setSortKey] = useState<string>("app_name");
  const [asc, setAsc] = useState(true);
  const [open, setOpen] = useState<string | null>(null);

  const options = useMemo(() => {
    const o: Record<string, string[]> = {};
    for (const f of FILTERS) {
      o[f] = Array.from(new Set(rows.map((r) => String(r[f] ?? "")).filter(Boolean))).sort();
    }
    return o;
  }, [rows]);

  const filtered = useMemo(() => {
    let list = rows.slice();
    if (q.trim()) {
      const needle = q.toLowerCase();
      list = list.filter((r) => r.app_name.toLowerCase().includes(needle));
    }
    for (const f of FILTERS) {
      if (filters[f]) list = list.filter((r) => String(r[f] ?? "") === filters[f]);
    }
    list.sort((a, b) => {
      const av = String((a as Record<string, unknown>)[sortKey] ?? "");
      const bv = String((b as Record<string, unknown>)[sortKey] ?? "");
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    return list;
  }, [rows, q, filters, sortKey, asc]);

  function toggleSort(key: string) {
    if (sortKey === key) setAsc(!asc);
    else {
      setSortKey(key);
      setAsc(true);
    }
  }

  if (!rows.length) {
    return (
      <div className="placeholder">
        Table placeholder — commit a populated <code>public/data.json</code> after a pipeline run.
        Sortable/filterable columns: business_type, access_tier, buildability, auth_primary.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-end">
        <label className="text-sm">
          Search
          <input
            className="ml-2 border border-line rounded px-2 py-1 bg-white"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="app name"
          />
        </label>
        {FILTERS.map((f) => (
          <label key={f} className="text-sm">
            {f}
            <select
              className="ml-2 border border-line rounded px-2 py-1 bg-white"
              value={filters[f] || ""}
              onChange={(e) => setFilters({ ...filters, [f]: e.target.value })}
            >
              <option value="">all</option>
              {options[f].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <div className="overflow-x-auto border border-line rounded bg-white/70">
        <table className="min-w-full text-sm">
          <thead className="bg-ink/5 text-left">
            <tr>
              {["app_name", "business_type", "access_tier", "buildability", "auth_primary"].map(
                (h) => (
                  <th key={h} className="px-3 py-2 font-semibold">
                    <button type="button" onClick={() => toggleSort(h)}>
                      {h}
                      {sortKey === h ? (asc ? " ↑" : " ↓") : ""}
                    </button>
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <Fragment key={r.app_name}>
                <tr
                  className="border-t border-line cursor-pointer hover:bg-accent/5"
                  onClick={() => setOpen(open === r.app_name ? null : r.app_name)}
                >
                  <td className="px-3 py-2 font-medium">{r.app_name}</td>
                  <td className="px-3 py-2">{r.business_type}</td>
                  <td className="px-3 py-2">{r.access_tier}</td>
                  <td className="px-3 py-2">{r.buildability}</td>
                  <td className="px-3 py-2">{r.auth_primary}</td>
                </tr>
                {open === r.app_name && (
                  <tr className="bg-paper/80">
                    <td colSpan={5} className="px-3 py-3 text-mute">
                      <div className="grid gap-2 md:grid-cols-2">
                        <div>
                          <strong className="text-ink">blocker:</strong> {r.blocker || "—"}
                        </div>
                        <div>
                          <strong className="text-ink">auth_detail:</strong> {r.auth_detail || "—"}
                        </div>
                        <div>
                          <strong className="text-ink">flags:</strong>{" "}
                          {(r.flags || []).join(", ") || "—"}
                        </div>
                        <div>
                          <strong className="text-ink">evidence:</strong>
                          <ul className="list-disc ml-5">
                            {Object.entries(r.evidence || {}).map(([k, v]) => (
                              <li key={k}>
                                {k}:{" "}
                                <a className="text-accent underline" href={v} target="_blank" rel="noreferrer">
                                  {v}
                                </a>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-mute">{filtered.length} rows</p>
    </div>
  );
}
