/**
 * The API client (M7).
 *
 * Every network call the UX makes lives here, and every one of them goes to the
 * duva-bench server. Nothing in `web/` talks to ADP directly, and nothing holds
 * a credential: the server reads ADP on the browser's behalf through six
 * literal paths, and a browser that could reach ADP itself would be a browser
 * that had been given a token.
 *
 * There is also no computation here. The server returns the same report the CLI
 * prints, and this layer's job is to carry it, not to recompute a mean.
 */

export type StudySummary = {
  digest: string;
  slug: string;
  title: string;
  tasks: string[];
  arms: string[];
  repetitions: number;
  trials: number;
  budget_usd_cap: string;
  pre_registration: {
    digest: string;
    original_digest: string;
    amended: boolean;
    primary_metric: string;
    control_arm: string | null;
  };
};

export type PlannedTrial = {
  task: string;
  arm: string;
  repetition: number;
  external_ref: string;
};

export type StudyDetail = StudySummary & {
  document: unknown;
  source: string;
  trials: PlannedTrial[];
};

export type Status = {
  study: string;
  study_digest: string;
  planned: number;
  verified: number;
  errors: number;
  remaining: string[];
  running: boolean;
};

export type TrialFrame = {
  external_ref: string;
  verdict: "VERIFIED" | "ERROR";
  run_id?: string;
  task?: string;
  arm?: string;
  repetition?: number;
  events?: number;
  error?: string;
};

/** What `report.json` holds. Typed loosely on purpose: the report grows, and a
 * type that had to be widened for every new field would make the UX the reason
 * a report cannot carry something new. */
export type Report = {
  study: { title: string; digest: string; arms: Record<string, Record<string, string>> };
  pre_registration: {
    digest: string;
    original_digest: string;
    amended: boolean;
    amendments: { date: string; field: string; previous: unknown; rationale: string }[];
  };
  evidence: {
    trials: number;
    verified: number;
    errors: number;
    error_refs: string[];
    digests: { split_axes: string[]; split_cells: string[]; split_arms: string[] };
  };
  axes: Record<string, AxisBlock>;
  process: Record<string, Record<string, number | null | string[]>>;
  cost: { total_usd: number; tokens_in: number; tokens_out: number; unpriced_trials: number };
  trials: ReportTrial[];
  warnings: string[];
};

export type AxisBlock = {
  axis: string;
  banded: boolean;
  noise_floor: { pooled_sd?: number; cells?: number; unavailable?: string };
  arms: { arm: string; n: number; mean: number | null; ci: Interval; unscored: number }[];
  cells: Record<string, { n: number; mean: number | null; values: number[] }>;
  contrasts: Contrasts;
  icc: { icc?: number; unavailable?: string };
};

export type Interval = { low: number; high: number; confidence: number } | { unavailable: string };

export type Contrasts =
  | { unavailable: string }
  | {
      control: string;
      correction: string;
      arms: Record<string, ContrastRow>;
    };

export type ContrastRow = {
  vs?: string;
  delta?: number;
  ci?: Interval;
  delta_in_sd?: number | { unavailable: string };
  holm_p?: number;
  mcnemar?: { p: number; control_only: number; arm_only: number };
  unavailable?: string;
};

export type ReportTrial = {
  run_id: string;
  external_ref: string | null;
  task: string;
  arm: string;
  repetition: number | null;
  verdict: string;
  failures: string[];
  axes: Record<string, { score: number | null; passed: boolean | null }>;
  process: Record<string, number | null | string[]>;
};

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    // The server's own message, not a generic one: a study file is a user's
    // document and "422" alone is not something anybody can act on.
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  async validate(source: string): Promise<{ ok: boolean; error?: string } & Partial<StudySummary>> {
    return json(
      await fetch("/api/studies/validate", {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: source,
      }),
    );
  },

  async upload(source: string): Promise<StudySummary> {
    return json(
      await fetch("/api/studies", {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: source,
      }),
    );
  },

  async studies(): Promise<StudySummary[]> {
    return json(await fetch("/api/studies"));
  },

  async study(digest: string): Promise<StudyDetail> {
    return json(await fetch(`/api/studies/${encodeURIComponent(digest)}`));
  },

  async run(digest: string): Promise<{ status: string; planned?: number }> {
    return json(await fetch(`/api/studies/${encodeURIComponent(digest)}/run`, { method: "POST" }));
  },

  async status(digest: string): Promise<Status> {
    return json(await fetch(`/api/studies/${encodeURIComponent(digest)}/status`));
  },

  async report(digest: string): Promise<Report> {
    return json(await fetch(`/api/studies/${encodeURIComponent(digest)}/report`));
  },

  /** The ADP link for a run, through the server's read-proxy.
   *
   * A link rather than a fetch: the point is that a reader can go and check the
   * run themselves, which is the whole claim duva-bench makes. */
  adpVerifyUrl(owner: string, repo: string, runId: string): string {
    const query = new URLSearchParams({ owner, repo, run_id: runId });
    return `/api/adp/run_verify?${query.toString()}`;
  },
};

/**
 * Subscribe to a study's progress.
 *
 * `EventSource` re-sends `Last-Event-ID` on reconnect by itself, and the server
 * replays from that byte offset — so a laptop that slept does not leave a hole
 * in the grid. Frames are deduplicated by `external_ref` here anyway, because
 * replaying one row twice is the cheap side of that trade and the browser
 * should not care.
 */
export function subscribe(
  digest: string,
  onTrial: (frame: TrialFrame) => void,
  onDone: (status: Status) => void,
): () => void {
  const source = new EventSource(`/api/studies/${encodeURIComponent(digest)}/stream`);
  source.addEventListener("trial", (event) => {
    onTrial(JSON.parse((event as MessageEvent).data) as TrialFrame);
  });
  source.addEventListener("done", (event) => {
    onDone(JSON.parse((event as MessageEvent).data) as Status);
    source.close();
  });
  return () => source.close();
}
