"""One-file report: a robustness campaign as ONE self-contained HTML file (no server, no internet needed to open it).

Everything is inside the file: the summary, the cost, a success chart (inline SVG), the table per strength and the
table per trial. Trial videos are left out by default (they make the file large); with videos=True each recorded
trial video is embedded as base64 and plays in the file.
"""

from __future__ import annotations

import base64
import html
import json
import time
from pathlib import Path

from .monitor import OUTCOMES

CSS = """
:root { --bg:#ffffff; --text:#1b1b1b; --muted:#666; --line:#dde2e8; --ok:#1f8a4c; --bad:#c0392b; --bar:#438dd5; }
@media (prefers-color-scheme: dark) { :root { --bg:#111; --text:#eee; --muted:#9a9a9a; --line:#2c2c2c; } }
body { background:var(--bg); color:var(--text); font:15px/1.5 "Segoe UI", system-ui, sans-serif; margin:0; }
main { max-width:1000px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:24px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 8px; }
.muted { color:var(--muted); } .ok { color:var(--ok); } .bad { color:var(--bad); }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:10px; margin-top:14px; }
.card { border:1px solid var(--line); border-radius:6px; padding:10px 12px; }
.card b { display:block; font-size:20px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:400; }
.scroll { overflow-x:auto; }
video { width:100%; max-width:640px; display:block; margin:6px 0 16px; }
svg text { fill:var(--muted); font-size:12px; }
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _pct(rate) -> str:
    return "-" if rate is None else f"{rate * 100:.0f} %"


def _usd(value) -> str:
    return "-" if value is None else f"${value:.4f}"


def _chart(per_value: list[dict], unit: str) -> str:
    """Bars: success rate per strength."""
    if not per_value:
        return ""
    w, h, pad = 720, 220, 36
    step = (w - 2 * pad) / len(per_value)
    bars = []
    for i, p in enumerate(per_value):
        rate = p.get("rate")
        x = pad + i * step + step * 0.15
        bw = step * 0.7
        bh = 0 if rate is None else rate * (h - 2 * pad)
        bars.append(f'<rect x="{x:.1f}" y="{h - pad - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="#438dd5"/>')
        bars.append(f'<text x="{x + bw / 2:.1f}" y="{h - pad + 16}" text-anchor="middle">{_e(p["value"])}{_e(unit)}'
                    f'</text>')
        label = "-" if rate is None else f"{p['successes']}/{p['n']}"
        bars.append(f'<text x="{x + bw / 2:.1f}" y="{h - pad - bh - 6:.1f}" text-anchor="middle">{label}</text>')
    axis = (f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#999"/>'
            f'<text x="4" y="{pad}">100 %</text><text x="4" y="{h - pad}">0 %</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Success rate per strength">'
            f'{axis}{"".join(bars)}</svg>')


def render(result: dict, folder: Path, videos: bool = False) -> str:
    cfg = result.get("config", {})
    analysis = result.get("analysis", {})
    verdict = analysis.get("verdict", {}).get("text", "")
    cost = result.get("cost") or {}
    started = result.get("started")
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(started)) if started else ""
    title = (f"{result.get('perturbation', {}).get('label', 'Random mix')}: {cfg.get('task', '')}"
             if result.get("mode") == "sweep" else f"Random mix: {cfg.get('task', '')}")
    rows = result.get("rows", [])
    successes = sum(1 for r in rows if r.get("success"))
    parts = [f"<h1>{_e(title)}</h1>",
             f'<p class="muted">Campaign {_e(result.get("id"))}, {_e(when)}. Policy: {_e(result.get("policy"))}. '
             f'State: {_e(result.get("state"))}.</p>',
             f"<p><b>{_e(verdict)}</b></p>",
             '<div class="grid">',
             f'<div class="card"><span class="muted">Trials</span><b>{_e(result.get("done"))} of '
             f'{_e(result.get("total"))}</b></div>',
             f'<div class="card"><span class="muted">Successes</span><b>{successes}</b></div>',
             f'<div class="card"><span class="muted">Dream-1 calls</span><b>{_e(cost.get("calls", 0))}</b></div>',
             f'<div class="card"><span class="muted">Cost</span><b>{_usd(cost.get("usd"))}</b>'
             f'<span class="muted">{_e(cost.get("note", ""))}</span></div>',
             "</div>"]

    if result.get("mode") == "sweep":
        unit = result.get("perturbation", {}).get("unit", "")
        per_value = analysis.get("per_value", [])
        parts += ["<h2>Success per strength</h2>", _chart(per_value, unit),
                  '<div class="scroll"><table><tr><th>Strength</th><th>Counted trials</th><th>Successes</th>'
                  "<th>Success rate</th><th>Outcomes</th></tr>"]
        for p in per_value:
            outcomes = ", ".join(f"{OUTCOMES.get(k, k)}: {v}" for k, v in (p.get("outcomes") or {}).items())
            parts.append(f"<tr><td>{_e(p['value'])} {_e(unit)}</td><td>{p['n']}</td><td>{p['successes']}</td>"
                         f"<td>{_pct(p.get('rate'))}</td><td>{_e(outcomes)}</td></tr>")
        parts.append("</table></div>")
    else:
        parts += ["<h2>Factors</h2>", '<div class="scroll"><table><tr><th>Factor</th><th>Rank correlation with '
                  "progress</th><th>Weak half: success</th><th>Strong half: success</th></tr>"]
        for f in analysis.get("per_factor", []):
            parts.append(f"<tr><td>{_e(f['id'])}</td><td>{_e(f.get('rho'))}</td><td>{_pct(f['weak'].get('rate'))}"
                         f"</td><td>{_pct(f['strong'].get('rate'))}</td></tr>")
        parts.append("</table></div>")

    parts += ["<h2>Every trial</h2>", '<div class="scroll"><table><tr><th>No.</th><th>Setting</th><th>Outcome</th>'
              "<th>Simulated seconds</th><th>Calls</th><th>Cost</th><th>Prompt</th></tr>"]
    for r in rows:
        setting = ", ".join(f"{k} {v:g}" if isinstance(v, (int, float)) else f"{k} {v}"
                            for k, v in (r.get("params") or {}).items())
        cls = "ok" if r.get("success") else "bad"
        parts.append(f"<tr><td>{r['index']}</td><td>{_e(setting)}</td>"
                     f'<td class="{cls}">{_e(OUTCOMES.get(r.get("outcome"), r.get("outcome")))}</td>'
                     f"<td>{_e(r.get('seconds'))}</td><td>{_e(r.get('calls', 0))}</td><td>{_usd(r.get('cost_usd'))}</td>"
                     f"<td>{_e(r.get('prompt'))}</td></tr>")
    parts.append("</table></div>")

    if videos:
        clips = [(r, folder / r["video"]) for r in rows if r.get("video") and (folder / r["video"]).is_file()]
        parts.append("<h2>Videos</h2>" if clips else "")
        for r, path in clips:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            parts.append(f'<p class="muted">Trial {r["index"]}</p>'
                         f'<video controls preload="none" src="data:video/mp4;base64,{data}"></video>')

    parts.append(f'<h2>Settings</h2><pre class="muted">{_e(json.dumps(cfg, indent=2))}</pre>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>Robustness report</title><style>{CSS}</style>'
            f'</head><body><main>{"".join(parts)}</main></body></html>')
