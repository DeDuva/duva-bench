"""Rendering a report as one self-contained HTML file (M6).

Self-contained means exactly that: no scripts, no fonts fetched at load, no
stylesheet next door. A report is evidence that has to keep working when it is
mailed as an attachment, opened from a USB stick in five years, or served from a
directory nobody maintains. Anything it needs from the network is a way for it
to stop being readable.

The palette and typography are copied from ``docs/html/index.html`` — same
tokens, same monospace numerals — so a report looks like the project that
produced it. IBM Plex is *requested* and system fonts are the stated fallback,
because embedding a webfont would multiply the file size by an order of
magnitude to change nothing about what the numbers say.

Nothing here computes. Every number rendered was computed in ``build.py`` and
appears in ``report.json`` unchanged; a reader who distrusts this page can read
the JSON, and a reader who distrusts both can re-derive it from ADP.
"""

from __future__ import annotations

import html
import json
from typing import Any

from duva_bench.report.build import Report

STYLE = """
:root{--bg:#0d0e10;--panel:#16181b;--panel2:#1d2024;--line:#2a2e33;--fg:#e9e7e2;
--sub:#b9bcc1;--dim:#8b9098;--cyan:#4fd1d9;--amber:#e0a458;--red:#e4695e;--green:#57d9a3;
--mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
--sans:'IBM Plex Sans',system-ui,-apple-system,sans-serif}
html,body{margin:0;padding:0;background:var(--bg)}
body{-webkit-font-smoothing:antialiased;color:var(--fg);font:400 16px/1.6 var(--sans);
padding-bottom:120px}
*{box-sizing:border-box}
.wrap{max-width:1180px;margin:0 auto;padding:64px 32px 0}
h1{font:600 34px/1.15 var(--sans);letter-spacing:-.015em;margin:0 0 8px}
h2{font:600 22px/1.2 var(--sans);margin:56px 0 6px}
h3{font:500 15px/1.3 var(--mono);letter-spacing:.04em;color:var(--cyan);margin:28px 0 10px}
p{color:var(--sub);max-width:78ch;margin:0 0 14px}
.kick{font:500 12px/1 var(--mono);letter-spacing:.18em;color:var(--dim);margin-bottom:18px}
.mono{font-family:var(--mono)}
.dim{color:var(--dim)}
code{font-family:var(--mono);font-size:.92em;color:var(--sub)}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0 8px}
.card{border:1px solid var(--line);background:var(--panel);border-radius:4px;padding:16px 18px;
flex:1;min-width:170px}
.cardv{font:500 26px var(--mono);letter-spacing:-.02em;margin-bottom:6px}
.cardk{font:400 12px/1.4 var(--sans);color:var(--dim)}
table{border-collapse:collapse;width:100%;margin:12px 0 8px;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{font:500 12px/1.3 var(--mono);letter-spacing:.06em;color:var(--dim);text-transform:uppercase}
td.num,th.num{text-align:right;font-family:var(--mono)}
tr:hover td{background:var(--panel)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:4px;background:var(--panel)}
.scroll table{margin:0}
.band{border:1px solid var(--amber);border-left-width:3px;background:rgba(224,164,88,.07);
border-radius:4px;padding:14px 16px;margin:16px 0;color:var(--sub)}
.warn{border:1px solid var(--red);border-left-width:3px;background:rgba(228,105,94,.07);
border-radius:4px;padding:14px 16px;margin:16px 0;color:var(--sub)}
.ok{color:var(--green)}.bad{color:var(--red)}.na{color:var(--dim);font-style:italic}
.pre{font-family:var(--mono);font-size:13px;white-space:pre-wrap;color:var(--sub);
border:1px solid var(--line);background:var(--panel);border-radius:4px;padding:14px 16px}
.foot{color:var(--dim);font-size:13px;margin-top:64px;border-top:1px solid var(--line);
padding-top:18px}
@media (max-width:720px){.wrap{padding:40px 18px 0}h1{font-size:26px}}
"""


def render_html(report: Report) -> str:
    payload = report.as_dict()
    study = payload["study"]
    title = f"duva-bench — {study['title']}"

    sections = [
        _header(payload),
        _warnings(payload),
        _pre_registration(payload["pre_registration"]),
        _evidence(payload["evidence"]),
        *[_axis(name, block) for name, block in sorted(payload["axes"].items())],
        _process(payload["process"]),
        _cost(payload["cost"]),
        _trials(payload["trials"]),
        _footer(study),
    ]

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n"
        f'<div class="wrap">\n{"".join(sections)}</div>\n</body>\n</html>\n'
    )


# --- sections ---------------------------------------------------------------


def _header(payload: dict[str, Any]) -> str:
    study = payload["study"]
    evidence = payload["evidence"]
    return (
        '<div class="kick">DUVA-BENCH REPORT</div>'
        f"<h1>{esc(study['title'])}</h1>"
        f'<p class="mono dim">{esc(study["digest"])}</p>'
        '<div class="cards">'
        + _card(str(evidence["trials"]), "trials recorded")
        + _card(str(evidence["verified"]), "verified")
        + _card(
            str(evidence["errors"]),
            "ERROR — excluded from every statistic",
            tone="bad" if evidence["errors"] else "",
        )
        + _card(str(len(study["arms"])), "arms")
        + _card(str(len(study["tasks"])), "tasks")
        + _card(str(study["repetitions"]), "repetitions per cell")
        + "</div>"
    )


def _warnings(payload: dict[str, Any]) -> str:
    if not payload["warnings"]:
        return ""
    items = "".join(f"<li>{esc(warning)}</li>" for warning in payload["warnings"])
    return f'<div class="warn"><strong>Read these first.</strong><ul>{items}</ul></div>'


def _pre_registration(block: dict[str, Any]) -> str:
    rows = [
        "<h2>Pre-registration</h2>",
        "<p>The analysis block as it was registered before execution, and as it reads now. "
        "Both are printed whether or not they differ.</p>",
    ]
    if block["amended"]:
        amendments = "".join(
            f'<li><span class="mono">{esc(a["date"])}</span> — '
            f"<code>{esc(a['field'])}</code> was "
            f"<code>{esc(json.dumps(a['previous']))}</code>: {esc(a['rationale'])}</li>"
            for a in block["amendments"]
        )
        rows.append(
            '<div class="band"><strong>This pre-registration was amended.</strong> '
            f"The pre-amendment reading is still computable and its digest is "
            f'<span class="mono">{esc(block["original_digest"])}</span>.<ul>{amendments}</ul></div>'
        )
    registered = _pre(block["as_registered"])
    analyzed = _pre(block["as_analyzed"])
    rows.append(
        '<div class="scroll"><table><tr><th>reading</th><th>digest</th><th>block</th></tr>'
        f'<tr><td>as registered</td><td class="mono">{esc(block["original_digest"])}</td>'
        f"<td>{registered}</td></tr>"
        f'<tr><td>as analyzed</td><td class="mono">{esc(block["digest"])}</td>'
        f"<td>{analyzed}</td></tr>"
        "</table></div>"
    )
    return "".join(rows)


def _evidence(block: dict[str, Any]) -> str:
    digests = block["digests"]
    rows = [
        "<h2>Evidence</h2>",
        "<p>Every trial below was verified against ADP's <code>/verify</code> at report time. "
        "A trial that does not verify is an ERROR: it is excluded from every statistic and "
        "counted here, and it never becomes a failure or a zero.</p>",
    ]
    if block["error_refs"]:
        rows.append(
            '<div class="warn">Excluded: '
            + ", ".join(f'<span class="mono">{esc(ref)}</span>' for ref in block["error_refs"])
            + "</div>"
        )
    grader = digests["grader_spec_digests"]
    if grader:
        banded = '<span class="bad">banded</span>'
        single = '<span class="ok">single instrument</span>'
        body = "".join(
            f'<tr><td>{esc(axis)}</td><td class="mono">{esc(", ".join(values))}</td>'
            f"<td>{banded if len(values) > 1 else single}</td></tr>"
            for axis, values in sorted(grader.items())
        )
        rows.append(
            '<h3>grader identity</h3><div class="scroll"><table>'
            "<tr><th>axis</th><th>spec digest</th><th></th></tr>" + body + "</table></div>"
        )
    return "".join(rows)


def _axis(name: str, block: dict[str, Any]) -> str:
    rows = [f"<h2>Axis: {esc(name)}</h2>"]

    if block["banded"]:
        rows.append(
            '<div class="band"><strong>Banded — not ranked.</strong> The trials on this axis '
            "were scored under more than one grader spec digest. They are different "
            "instruments, and ranking across them would produce a number whose meaning "
            "depends on which rows happened to be included.</div>"
        )

    noise = block["noise_floor"]
    if "pooled_sd" in noise:
        rows.append(
            "<h3>noise floor</h3>"
            f'<p>Pooled within-cell standard deviation is <span class="mono">'
            f"{noise['pooled_sd']:.4f}</span> over {noise['cells']} cell(s), "
            f"{noise['degrees_of_freedom']} degrees of freedom. A contrast smaller than this "
            "is a contrast this design cannot distinguish from a rerun.</p>"
        )
    else:
        rows.append(f'<h3>noise floor</h3><p class="na">{esc(noise["unavailable"])}</p>')

    header = '<tr><th>arm</th><th class="num">n</th><th class="num">mean</th>'
    header += '<th class="num">95% CI</th><th class="num">unscored</th></tr>'
    body = "".join(
        f"<tr><td>{esc(arm['arm'])}</td>"
        f'<td class="num">{arm["n"]}</td>'
        f'<td class="num">{_number(arm["mean"])}</td>'
        f'<td class="num">{_interval(arm["ci"])}</td>'
        f'<td class="num">{arm["unscored"]}</td></tr>'
        for arm in block["arms"]
    )
    rows.append(f'<h3>per arm</h3><div class="scroll"><table>{header}{body}</table></div>')

    rows.append(_contrasts(block["contrasts"]))
    rows.append(_cells(block["cells"]))

    variance = block["icc"]
    if "icc" in variance:
        rows.append(
            f'<h3>variance</h3><p>ICC(1) = <span class="mono">{variance["icc"]:.3f}</span> over '
            f"{variance['tasks']} task(s) and {variance['observations']} observation(s): the "
            "share of variance that is between tasks rather than between repetitions.</p>"
        )
    else:
        rows.append(f'<h3>variance</h3><p class="na">ICC: {esc(variance["unavailable"])}</p>')

    return "".join(rows)


def _contrasts(block: dict[str, Any]) -> str:
    if "unavailable" in block:
        return f'<h3>contrasts</h3><p class="na">{esc(block["unavailable"])}</p>'

    header = (
        f'<tr><th>arm vs {esc(block["control"])}</th><th class="num">Δ</th>'
        '<th class="num">95% CI</th><th class="num">Δ in sd</th>'
        '<th class="num">McNemar p</th><th class="num">Holm p</th><th>discordance</th></tr>'
    )
    body = ""
    for arm, row in sorted(block["arms"].items()):
        if "unavailable" in row:
            body += (
                f"<tr><td>{esc(arm)}</td>"
                f'<td colspan="6" class="na">{esc(row["unavailable"])}</td></tr>'
            )
            continue
        mcnemar = row["mcnemar"]
        # A rate has no discordance table — see build.py. The cell says so
        # rather than showing a p-value the design did not earn.
        if "unavailable" in mcnemar:
            discordance = f'<span class="na">{esc(mcnemar["unavailable"])}</span>'
            p_cell = '<span class="na">—</span>'
        else:
            paired = (
                mcnemar["both_pass"]
                + mcnemar["both_fail"]
                + mcnemar["control_only"]
                + mcnemar["arm_only"]
            )
            discordance = f"{mcnemar['control_only']}/{mcnemar['arm_only']} discordant of {paired}"
            p_cell = _number(mcnemar["p"], digits=4)
        body += (
            f"<tr><td>{esc(arm)}</td>"
            f'<td class="num">{_number(row["delta"])}</td>'
            f'<td class="num">{_interval(row["ci"])}</td>'
            f'<td class="num">{_number(row["delta_in_sd"])}</td>'
            f'<td class="num">{p_cell}</td>'
            f'<td class="num">{_number(row.get("holm_p"), digits=4)}</td>'
            f'<td class="mono dim">{discordance}</td></tr>'
        )
    return (
        "<h3>contrasts</h3>"
        "<p>Pairwise against the pre-registered control, corrected across arms with Holm. "
        "Read Δ against the noise floor above before reading its p-value.</p>"
        f'<div class="scroll"><table>{header}{body}</table></div>'
    )


def _cells(cells: dict[str, Any]) -> str:
    header = (
        '<tr><th>task / arm</th><th class="num">n</th><th class="num">mean</th><th>values</th></tr>'
    )
    body = "".join(
        f"<tr><td>{esc(key)}</td>"
        f'<td class="num">{cell["n"]}</td>'
        f'<td class="num">{_number(cell["mean"])}</td>'
        f'<td class="mono dim">{esc(", ".join(f"{value:g}" for value in cell["values"]))}</td></tr>'
        for key, cell in sorted(cells.items())
    )
    return f'<h3>per cell</h3><div class="scroll"><table>{header}{body}</table></div>'


def _process(block: dict[str, Any]) -> str:
    if not block:
        return ""
    header = (
        '<tr><th>arm</th><th class="num">trials</th><th class="num">tool calls</th>'
        '<th class="num">error rate</th><th class="num">hallucinated</th>'
        '<th class="num">metaprogramming</th><th class="num">retries</th>'
        "<th>unknown names</th></tr>"
    )
    body = "".join(
        f"<tr><td>{esc(arm)}</td>"
        f'<td class="num">{row["trials"]}</td>'
        f'<td class="num">{row["tool_calls"]}</td>'
        f'<td class="num">{_number(row["tool_error_rate"])}</td>'
        f'<td class="num">{_number(row["hallucinated_call_rate"])}</td>'
        f'<td class="num">{_number(row["metaprogramming_rate"])}</td>'
        f'<td class="num">{_number(row["retry_rate"])}</td>'
        f'<td class="mono dim">{esc(", ".join(row["unknown_names"]))}</td></tr>'
        for arm, row in sorted(block.items())
    )
    return (
        "<h2>Process</h2>"
        "<p>What the arms did, rather than how they scored. A rate is blank where its "
        "denominator is zero — an arm that made no tool calls has no tool-error rate, which "
        "is not the same as a rate of zero.</p>"
        f'<div class="scroll"><table>{header}{body}</table></div>'
    )


def _cost(block: dict[str, Any]) -> str:
    header = (
        '<tr><th>arm</th><th class="num">trials</th><th class="num">tokens in</th>'
        '<th class="num">tokens out</th><th class="num">cost (USD)</th></tr>'
    )
    body = "".join(
        f'<tr><td>{esc(arm)}</td><td class="num">{row["trials"]}</td>'
        f'<td class="num">{row["tokens_in"]:,}</td>'
        f'<td class="num">{row["tokens_out"]:,}</td>'
        f'<td class="num">{row["cost_micro_usd"] / 1_000_000:.4f}</td></tr>'
        for arm, row in sorted(block.get("by_arm", {}).items())
    )
    unpriced = (
        f'<div class="band">{block["unpriced_trials"]} trial(s) carry no cost in ADP. They are '
        "reported as unpriced rather than folded in as zero.</div>"
        if block.get("unpriced_trials")
        else ""
    )
    cards = (
        _card(f"${block['total_usd']:.4f}", "total")
        + _card(f"{block['tokens_in']:,}", "tokens in")
        + _card(f"{block['tokens_out']:,}", "tokens out")
    )
    return (
        "<h2>Cost</h2>"
        f'<div class="cards">{cards}</div>'
        f'{unpriced}<div class="scroll"><table>{header}{body}</table></div>'
    )


def _trials(trials: list[dict[str, Any]]) -> str:
    header = (
        '<tr><th>external ref</th><th>task</th><th>arm</th><th class="num">rep</th>'
        "<th>verdict</th><th>axes</th><th>run</th></tr>"
    )
    body = ""
    for trial in trials:
        verdict = trial["verdict"]
        axes = ", ".join(
            f"{name}={_number(result['score']) if result['score'] is not None else 'unscored'}"
            for name, result in sorted(trial["axes"].items())
        )
        # An empty cell would read as a zero-scored trial. It is neither.
        axes_cell = esc(axes) if axes else '<span class="na">unscored</span>'
        failures = (
            f'<div class="dim">{esc("; ".join(trial["failures"]))}</div>'
            if trial["failures"]
            else ""
        )
        body += (
            f'<tr><td class="mono">{esc(trial["external_ref"] or "")}</td>'
            f"<td>{esc(trial['task'])}</td><td>{esc(trial['arm'])}</td>"
            f'<td class="num">{trial["repetition"] if trial["repetition"] is not None else ""}</td>'
            f'<td class="{"ok" if verdict == "VERIFIED" else "bad"}">{esc(verdict)}{failures}</td>'
            f'<td class="mono dim">{axes_cell}</td>'
            f'<td class="mono dim">{esc(trial["run_id"])}</td></tr>'
        )
    return (
        "<h2>Trials</h2>"
        "<p>Every recorded trial, verified or not. The run id is the pointer into ADP; "
        "nothing in this report was computed from anywhere else.</p>"
        f'<div class="scroll"><table>{header}{body}</table></div>'
    )


def _footer(study: dict[str, Any]) -> str:
    where = f"{esc(study['adp']['owner'])}/{esc(study['adp']['repo'])}"
    return (
        '<div class="foot">'
        f'Study digest <span class="mono">{esc(study["digest"])}</span> · '
        f'recorded to ADP <span class="mono">{where}</span> · '
        f'bootstrap seed <span class="mono">{study["bootstrap_seed"]}</span>. '
        "Every number here is re-derivable from ADP; report.json carries the same values "
        "unrounded."
        "</div>"
    )


# --- helpers ----------------------------------------------------------------


def _pre(payload: Any) -> str:
    return f'<div class="pre">{esc(json.dumps(payload, indent=2, sort_keys=True))}</div>'


def _card(value: str, label: str, *, tone: str = "") -> str:
    return (
        f'<div class="card"><div class="cardv {tone}">{esc(value)}</div>'
        f'<div class="cardk">{esc(label)}</div></div>'
    )


def _number(value: Any, *, digits: int = 3) -> str:
    """Format a number, or say plainly that there is not one.

    An empty cell rather than a zero: this is the rendering half of the
    unscored-is-not-zero rule, and a dash that looks like a number would undo
    everything the analysis side is careful about.
    """
    if isinstance(value, dict):
        return f'<span class="na">{esc(str(value.get("unavailable", "n/a")))}</span>'
    if value is None:
        return '<span class="na">—</span>'
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def _interval(interval: Any) -> str:
    if not isinstance(interval, dict) or "low" not in interval:
        return _number(interval)
    return f"[{interval['low']:.3f}, {interval['high']:.3f}]"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
