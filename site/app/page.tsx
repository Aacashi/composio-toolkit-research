import { ResultsTable, type Row } from "@/components/ResultsTable";
import data from "../public/data.json";

const rows = (Array.isArray(data) ? data : []) as Row[];

export default function Page() {
  return (
    <main>
      {/* 1. Headline */}
      <header className="mx-auto max-w-6xl px-5 pt-20 pb-12">
        <p className="text-accent font-semibold tracking-wide text-sm mb-4">
          Composio Toolkit Research
        </p>
        <h1 className="font-display text-4xl md:text-6xl leading-tight max-w-4xl">
          [PLACEHOLDER] Primary finding headline — one sentence after clustering.
        </h1>
        <p className="mt-5 text-lg text-mute max-w-2xl">
          Credential access gates across 100 apps: what blocks a Composio engineer from shipping a
          toolkit today.
        </p>
      </header>

      {/* RESERVED: public / distributed app path assumption — must appear in findings */}
      <aside
        id="assumption-public-app"
        className="mx-auto max-w-6xl px-5 pb-8"
        data-slot="public-distributed-assumption"
      >
        <div className="border-l-4 border-accent pl-4 py-2 bg-white/50">
          <h2 className="font-display text-xl mb-1">Stated assumption</h2>
          <p className="text-mute text-sm max-w-3xl">
            <strong className="text-ink">Public / distributed path.</strong> Verdicts assume Composio
            ships toolkits to many customers — not a single-tenant custom or private app. Vendor app
            review before multi-customer production use is tagged <code>needs_review</code> (or worse),
            even when a private key would be easy for one engineer. Applies especially to Shopify,
            Slack, Meta Ads, and similar platforms.
          </p>
          <p className="text-xs text-mute mt-2 italic">
            [FINDINGS SLOT] Expand with examples from the run once labels exist.
          </p>
        </div>
      </aside>

      {/* RESERVED: cli_only category finding */}
      <aside
        id="finding-cli-tools"
        className="mx-auto max-w-6xl px-5 pb-4"
        data-slot="cli-only-finding"
      >
        <div className="border-l-4 border-ink/40 pl-4 py-2 bg-white/40">
          <h2 className="font-display text-xl mb-1">Category note: CLI-only tools</h2>
          <p className="text-mute text-sm max-w-3xl">
            Entries with <code>api_type=cli_only</code> (e.g. Mermaid CLI, Sherlock) are local
            commands with no vendor-authenticated API. They are{" "}
            <strong className="text-ink">not Composio connector candidates</strong>.
          </p>
          <p className="text-xs text-mute mt-2 italic">
            [FINDINGS SLOT] Count and list after the pipeline run.
          </p>
        </div>
      </aside>

      {/* access_tier_rollup note */}
      <aside className="mx-auto max-w-6xl px-5 pb-8">
        <p className="text-xs text-mute max-w-3xl">
          Headline charts use <code>access_tier_rollup</code> (open | paid | gated), derived in
          Stage 2 from the nine-value <code>access_tier</code>. Detail tables keep the full enum.
        </p>
      </aside>

      {/* 2. Stat band */}
      <section className="section" aria-labelledby="stats">
        <h2 id="stats">At a glance</h2>
        <p className="text-mute mb-8">Placeholder metrics — filled after the 100-app run.</p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
          {["easy_win %", "needs_review %", "needs_outreach %", "blocked %", "unknown %", "Composio coverage"].map(
            (label) => (
              <div key={label}>
                <div className="font-display text-4xl text-accent">—</div>
                <div className="text-sm text-mute mt-1">{label}</div>
              </div>
            )
          )}
        </div>
      </section>

      {/* 3. Patterns */}
      <section className="section" aria-labelledby="patterns">
        <h2 id="patterns">Patterns</h2>
        <p className="text-mute mb-6">Cross-tabs after clustering (not implemented in this scaffold).</p>
        <div className="grid md:grid-cols-2 gap-4">
          {[
            "business_type × access_tier_rollup",
            "auth_primary × buildability",
            "unblocker × buildability",
            "category × buildability",
          ].map((t) => (
            <div key={t} className="placeholder">
              <p className="font-semibold text-ink mb-2">Takeaway: [placeholder]</p>
              <p>{t} visualisation placeholder</p>
            </div>
          ))}
        </div>
      </section>

      {/* 4. Table */}
      <section className="section" aria-labelledby="table">
        <h2 id="table">All apps</h2>
        <p className="text-mute mb-6">
          Sortable and filterable. Expand a row for evidence, auth_detail, blocker, and flags.
        </p>
        <ResultsTable rows={rows} />
      </section>

      {/* Machine-readable dataset */}
      <script
        type="application/json"
        id="dataset"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(rows) }}
      />

      {/* 5. How it was built */}
      <section className="section" aria-labelledby="method">
        <h2 id="method">How it was built</h2>
        <p className="text-mute mb-4">Architecture + where a human was required.</p>
        <div className="placeholder">
          [PLACEHOLDER] Pipeline diagram: discover → fetch → clean → extract → guard →
          derive_verdict. Human fills 10-app ground truth atoms; code derives verdicts.
        </div>
      </section>

      {/* 6. Verification */}
      <section className="section" aria-labelledby="verification">
        <h2 id="verification">Verification</h2>
        <p className="text-mute mb-4">
          Deep (10 hand labels) and shallow (Composio auth agreement) stay separate numbers.
        </p>
        <div className="grid md:grid-cols-2 gap-4">
          <div className="placeholder">Accuracy table placeholder (deep)</div>
          <div className="placeholder">Before/after across run_vN + miss table placeholder</div>
        </div>
      </section>

      {/* 7. What defeated the agent */}
      <section className="section" aria-labelledby="defeats">
        <h2 id="defeats">What defeated the agent</h2>
        <div className="placeholder">
          [PLACEHOLDER] Apps where the pipeline failed, with reasons (thin docs, paywalls, no
          first-party pages, schema_fail, etc.).
        </div>
      </section>

      {/* 8. Repo link */}
      <footer className="section border-b-0 pb-24">
        <h2>Repository</h2>
        <p className="text-mute">
          <a
            className="text-accent underline"
            href="https://github.com/Aacashi/composio-toolkit-research"
          >
            github.com/Aacashi/composio-toolkit-research
          </a>
          <span className="block text-xs mt-2">
            (Remote may be empty until code is published intentionally.)
          </span>
        </p>
      </footer>
    </main>
  );
}
