# duva-bench web UX

Three views over the JSON API: **Define** (edit and digest a study), **Monitor** (watch the trial
grid fill in over SSE), **Analyze** (per-axis tables read back out of ADP).

It is a *client* of the API, never a second path. Every number it shows came from a route in
`src/duva_bench/server/app.py`, which calls the same functions the CLI calls. Nothing here computes
a mean, and nothing here holds an ADP token — the server reads ADP on the browser's behalf through
six literal paths.

```sh
npm install
python3 ../scripts/dev-server.py     # the API, with the in-memory ADP double
npm run dev                          # the UX, proxying /api to it
```

For the real thing, run the API with `DUVA_LIVE=1` and the ADP credentials in the environment.

## The walk

```sh
npm run ui-check
```

`tests/walk.spec.ts` drives define → run → analyze in a real browser against a real server. It
passes against the in-memory ADP double, which is what CI runs. That is evidence the three views
work; it is not evidence that a real study runs — that is gate G1, and gate G1 is blocked
(`docs/blockers.md`).

On a machine that cannot download a browser but already has one, point Playwright at it:

```sh
PLAYWRIGHT_CHROMIUM=/path/to/chrome npm run ui-check
```
