/**
 * Three views, and the argument for each (M7).
 *
 * **Define** — the study file, validated as it is typed, with the digest and the
 * pre-registration diff shown before anything is stored. The digest is the point:
 * a researcher should see the identity of what they are about to run change as
 * they edit it.
 *
 * **Monitor** — one cell per planned trial, filled in by SSE as trials finish,
 * each carrying its own verify badge. A trial that failed the evidence gate is
 * red here for the same reason it is ERROR in the report: it is not a failure,
 * it is a trial nobody can read.
 *
 * **Analyze** — per-axis ranking tables, banded where the digests disagree, with
 * the noise floor above every contrast and a link into the ADP run behind each
 * row. Nothing is computed in the browser; the server hands over the same report
 * the CLI prints.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  subscribe,
  type AxisBlock,
  type Interval,
  type PlannedTrial,
  type Report,
  type Status,
  type StudyDetail,
  type StudySummary,
  type TrialFrame,
} from "./api";

type View = "define" | "monitor" | "analyze";

export default function App() {
  const [view, setView] = useState<View>("define");
  const [studies, setStudies] = useState<StudySummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setStudies(await api.studies());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="app">
      <header className="top">
        <span className="brand">duva-bench</span>
        <span className="dim mono" data-testid="selected-digest">
          {selected ?? "no study selected"}
        </span>
        <nav className="tabs">
          {(["define", "monitor", "analyze"] as View[]).map((name) => (
            <button
              key={name}
              className="tab"
              aria-current={view === name}
              data-testid={`tab-${name}`}
              onClick={() => setView(name)}
            >
              {name}
            </button>
          ))}
        </nav>
      </header>

      {view === "define" && (
        <Define
          studies={studies}
          onStored={async (digest) => {
            setSelected(digest);
            await refresh();
            setView("monitor");
          }}
          onSelect={(digest) => setSelected(digest)}
        />
      )}
      {view === "monitor" && <Monitor digest={selected} onAnalyze={() => setView("analyze")} />}
      {view === "analyze" && <Analyze digest={selected} />}
    </div>
  );
}

// --- Define -----------------------------------------------------------------

function Define({
  studies,
  onStored,
  onSelect,
}: {
  studies: StudySummary[];
  onStored: (digest: string) => void | Promise<void>;
  onSelect: (digest: string) => void;
}) {
  const [source, setSource] = useState(EXAMPLE);
  const [validation, setValidation] = useState<
    ({ ok: boolean; error?: string } & Partial<StudySummary>) | null
  >(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Debounced: validation is a round trip, and one per keystroke would be a
    // request per keystroke for an answer nobody reads that fast.
    const timer = setTimeout(() => {
      void api.validate(source).then(setValidation);
    }, 250);
    return () => clearTimeout(timer);
  }, [source]);

  return (
    <div className="split">
      <section>
        <h2>Define</h2>
        <p>
          A study is a file. Its digest is its identity and rides on every ADP run, so a result is
          permanently bound to the definition that produced it.
        </p>
        <textarea
          value={source}
          spellCheck={false}
          data-testid="study-source"
          onChange={(event) => setSource(event.target.value)}
        />
        <div className="row" style={{ marginTop: 10 }}>
          <button
            disabled={busy || !validation?.ok}
            data-testid="store-study"
            onClick={async () => {
              setBusy(true);
              try {
                const stored = await api.upload(source);
                await onStored(stored.digest);
              } finally {
                setBusy(false);
              }
            }}
          >
            Store and open
          </button>
          <span className="mono dim" data-testid="digest">
            {validation?.ok ? validation.digest : ""}
          </span>
        </div>
      </section>

      <aside>
        <h3>validation</h3>
        {validation === null && <p className="na">checking…</p>}
        {validation?.ok === false && (
          <div className="warn" data-testid="validation-error">
            <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
              {validation.error}
            </pre>
          </div>
        )}
        {validation?.ok && (
          <div className="panel" data-testid="validation-ok">
            <div>
              <strong>{validation.title}</strong>
            </div>
            <div className="dim">
              {validation.trials} trials — {validation.tasks?.length} tasks ×{" "}
              {validation.arms?.length} arms × {validation.repetitions} repetitions
            </div>
            <h3>pre-registration</h3>
            <div className="mono" style={{ fontSize: 12 }}>
              <div>primary: {validation.pre_registration?.primary_metric}</div>
              <div>control: {validation.pre_registration?.control_arm ?? "—"}</div>
              <div className="dim">{validation.pre_registration?.digest}</div>
            </div>
            {validation.pre_registration?.amended && (
              <div className="band" data-testid="amended">
                Amended. The pre-amendment reading is still computable, and its digest is{" "}
                <span className="mono">{validation.pre_registration.original_digest}</span>. The
                report prints both.
              </div>
            )}
          </div>
        )}

        <h3>stored studies</h3>
        <div className="scroll">
          <table>
            <tbody>
              {studies.map((study) => (
                <tr key={study.digest}>
                  <td>
                    <button className="tab" onClick={() => onSelect(study.digest)}>
                      {study.title}
                    </button>
                  </td>
                  <td className="num dim mono">{study.trials}</td>
                </tr>
              ))}
              {studies.length === 0 && (
                <tr>
                  <td className="na">nothing stored yet</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </aside>
    </div>
  );
}

// --- Monitor ----------------------------------------------------------------

function Monitor({ digest, onAnalyze }: { digest: string | null; onAnalyze: () => void }) {
  const [study, setStudy] = useState<StudyDetail | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [frames, setFrames] = useState<Record<string, TrialFrame>>({});
  const unsubscribe = useRef<null | (() => void)>(null);

  useEffect(() => {
    if (!digest) return;
    void api.study(digest).then(setStudy);
    void api.status(digest).then(setStatus);
  }, [digest]);

  useEffect(() => {
    if (!digest) return;
    // Frames are keyed by external_ref, so a replayed row after a reconnect
    // overwrites rather than duplicating.
    unsubscribe.current = subscribe(
      digest,
      (frame) => setFrames((current) => ({ ...current, [frame.external_ref]: frame })),
      (final) => setStatus(final),
    );
    return () => unsubscribe.current?.();
  }, [digest]);

  if (!digest) return <Empty what="a study" />;

  const planned: PlannedTrial[] = study?.trials ?? [];
  const done = Object.values(frames);
  const errors = done.filter((frame) => frame.verdict === "ERROR").length;

  return (
    <section>
      <h2>Monitor</h2>
      <div className="row">
        <button
          data-testid="run-study"
          disabled={status?.running}
          onClick={async () => {
            await api.run(digest);
            setStatus(await api.status(digest));
          }}
        >
          {status?.running ? "running…" : "Run"}
        </button>
        <button onClick={onAnalyze} data-testid="go-analyze">
          Analyze
        </button>
        <span className="mono dim" data-testid="progress">
          {done.length}/{planned.length || status?.planned || 0} trials
          {errors > 0 ? ` · ${errors} ERROR` : ""}
        </span>
      </div>

      {errors > 0 && (
        <div className="warn">
          A trial whose ADP <span className="mono">/verify</span> is not <span className="mono">ok</span>{" "}
          is an ERROR, never a failure: it is excluded from every statistic and counted separately.
        </div>
      )}

      <div className="grid" style={{ marginTop: 14 }} data-testid="trial-grid">
        {planned.map((trial) => {
          const frame = frames[trial.external_ref];
          const state = frame ? (frame.verdict === "VERIFIED" ? "verified" : "error") : "pending";
          return (
            <div className={`cell ${state}`} key={trial.external_ref} data-testid={`cell-${state}`}>
              <div>
                {trial.task} · {trial.arm}
              </div>
              <div className="dim">
                rep {trial.repetition}
                {frame?.events !== undefined ? ` · ${frame.events} events` : ""}
              </div>
              <div className={`badge ${state}`}>{state}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// --- Analyze ----------------------------------------------------------------

function Analyze({ digest }: { digest: string | null }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!digest) return;
    setReport(null);
    setError(null);
    api.report(digest).then(setReport, (failure: Error) => setError(failure.message));
  }, [digest]);

  const axes = useMemo(() => Object.entries(report?.axes ?? {}), [report]);

  if (!digest) return <Empty what="a study" />;
  if (error) return <div className="warn">{error}</div>;
  if (!report) return <p className="na">reading the study back out of ADP…</p>;

  return (
    <section>
      <h2>Analyze</h2>
      <p>
        Every number below was read back out of ADP at request time. Nothing is cached, and nothing
        is blended: each axis is ranked on its own.
      </p>

      {report.warnings.map((warning) => (
        <div className="warn" key={warning} data-testid="report-warning">
          {warning}
        </div>
      ))}

      <div className="row">
        <span className="mono dim">
          {report.evidence.verified} verified · {report.evidence.errors} ERROR ·{" "}
          ${report.cost.total_usd.toFixed(4)}
        </span>
      </div>

      {axes.map(([name, block]) => (
        <Axis key={name} name={name} block={block} />
      ))}

      <h3>process</h3>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th>arm</th>
              <th className="num">tool calls</th>
              <th className="num">error rate</th>
              <th className="num">hallucinated</th>
              <th className="num">metaprogramming</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(report.process).map(([arm, row]) => (
              <tr key={arm}>
                <td>{arm}</td>
                <td className="num">{num(row.tool_calls)}</td>
                <td className="num">{num(row.tool_error_rate)}</td>
                <td className="num">{num(row.hallucinated_call_rate)}</td>
                <td className="num">{num(row.metaprogramming_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>trials</h3>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th>external ref</th>
              <th>verdict</th>
              <th>axes</th>
              <th>run</th>
            </tr>
          </thead>
          <tbody>
            {report.trials.map((trial) => (
              <tr key={trial.run_id}>
                <td className="mono">{trial.external_ref}</td>
                <td className={trial.verdict === "VERIFIED" ? "ok" : "bad"}>{trial.verdict}</td>
                <td className="mono dim">
                  {Object.entries(trial.axes)
                    .map(([axis, result]) =>
                      result.score === null ? `${axis}=unscored` : `${axis}=${result.score}`,
                    )
                    .join(", ") || "unscored"}
                </td>
                <td className="mono dim">{trial.run_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Axis({ name, block }: { name: string; block: AxisBlock }) {
  return (
    <div data-testid={`axis-${name}`}>
      <h3>axis: {name}</h3>

      {block.banded && (
        <div className="band" data-testid="banded">
          Banded — not ranked. Two arms on one task were scored under different grader spec digests.
          Those are different instruments, and ranking across them would produce a number whose
          meaning depends on which rows were included.
        </div>
      )}

      <p data-testid={`noise-${name}`}>
        {block.noise_floor.pooled_sd !== undefined ? (
          <>
            Noise floor: pooled within-cell sd{" "}
            <span className="mono">{block.noise_floor.pooled_sd.toFixed(4)}</span>. A contrast
            smaller than this is one the design cannot tell from a rerun.
          </>
        ) : (
          <span className="na">Noise floor: {block.noise_floor.unavailable}</span>
        )}
      </p>

      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th>arm</th>
              <th className="num">n</th>
              <th className="num">mean</th>
              <th className="num">95% CI</th>
              <th className="num">unscored</th>
            </tr>
          </thead>
          <tbody>
            {block.arms.map((arm) => (
              <tr key={arm.arm}>
                <td>{arm.arm}</td>
                <td className="num">{arm.n}</td>
                <td className="num">{num(arm.mean)}</td>
                <td className="num">{interval(arm.ci)}</td>
                <td className="num">{arm.unscored}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {"unavailable" in block.contrasts ? (
        <p className="na">Contrasts: {block.contrasts.unavailable}</p>
      ) : (
        <div className="scroll" style={{ marginTop: 10 }}>
          <table>
            <thead>
              <tr>
                <th>vs {block.contrasts.control}</th>
                <th className="num">Δ</th>
                <th className="num">95% CI</th>
                <th className="num">Δ in sd</th>
                <th className="num">Holm p</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(block.contrasts.arms).map(([arm, row]) => (
                <tr key={arm}>
                  <td>{arm}</td>
                  <td className="num">{num(row.delta)}</td>
                  <td className="num">{row.ci ? interval(row.ci) : "—"}</td>
                  <td className="num">
                    {typeof row.delta_in_sd === "number" ? row.delta_in_sd.toFixed(2) : "—"}
                  </td>
                  <td className="num">{num(row.holm_p, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --- helpers ----------------------------------------------------------------

function Empty({ what }: { what: string }) {
  return <p className="na">Select {what} on the Define tab first.</p>;
}

/** An em dash, never a zero: a missing measurement is not a measurement of zero. */
function num(value: unknown, digits = 3): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(digits);
}

function interval(value: Interval): string {
  if ("unavailable" in value) return "—";
  return `[${value.low.toFixed(3)}, ${value.high.toFixed(3)}]`;
}

const EXAMPLE = `title: paste or edit a study here

adp:
  owner: duva
  repo: bench-smoke

tasks: []
arms: []
repetitions: 1
budget_usd_cap: "1.00"
concurrency: 1

pre_registration:
  primary_metric: acceptance
  repetitions: 1
`;
