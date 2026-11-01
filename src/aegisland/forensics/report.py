"""Self-contained evidence replay; exports are never flight inputs."""

from __future__ import annotations

import html
import json
import os
import tempfile
from pathlib import Path

from .analysis import Analysis

REPORT_FILES = ("report.html", "summary.json", "findings.md")


def _md(value: object) -> str:
    text = html.escape(str(value)).replace("\n", " ").replace("\r", " ")
    for char in ("\\", "|", "`", "[", "]", "(", ")", "*", "_"):
        text = text.replace(char, "\\" + char)
    return text


def ledger(summary: dict) -> str:
    lines = [
        "# Flight Forensics finding ledger",
        "",
        "Offline / post-flight evidence only. **executed=False**.",
        "Local sensing plane only. **3D traversability: UNKNOWN**; no traversal support.",
        "",
        summary["validation"],
        "",
        (
            "`observed`: recorded value; `inferred`: review rule/model; "
            "`unknown`: insufficient evidence. None establishes flight truth or causality."
        ),
        "",
        f"Clock alignment: **{summary['alignment']['status']}**. "
        + _md(summary["alignment"]["reason"]),
        "",
        "## Sources",
        "",
        "| Source | SHA-256 of input bytes | Samples | Complete |",
        "| --- | --- | ---: | --- |",
    ]
    for name, source in summary["sources"].items():
        lines.append(
            f"| {name} | {source['sha256'] or 'unknown'} | {source['samples']} "
            f"| {source['complete']} |"
        )
    lines += [
        "",
        "## Findings",
        "",
        "| ID | Category | Knowledge | Source / stream / record | Native time | Detail / evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in summary["findings"]:
        reference = f"{item['source']} / {item['stream']} / {item['index']}"
        timestamp = f"{item['timestamp']} {item['clock']}"
        detail = item["detail"] + " " + json.dumps(item["evidence"], ensure_ascii=False)
        lines.append(
            "| "
            + " | ".join(
                _md(v)
                for v in (
                    item["id"],
                    item["category"],
                    item["knowledge"],
                    reference,
                    timestamp,
                    detail,
                )
            )
            + " |"
        )
    lines += ["", "## Rule coverage", ""]
    lines += [
        f"- {_md(name)}: {value['status']}. {_md(value['detail'])}"
        for name, value in summary["coverage"].items()
    ]
    lines += [
        "",
        "## Analysis thresholds (review only)",
        "",
        "```json",
        json.dumps(summary["thresholds"], indent=2, allow_nan=False),
        "```",
        "",
        "## Limits",
        "",
    ]
    lines += ["- " + _md(text) for text in summary["limitations"]]
    return "\n".join(lines) + "\n"


def render_html(summary: dict) -> str:
    # Escaping '<' prevents a decision string from closing the application/json tag.
    data = json.dumps(summary, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    rows = []
    for item in summary["findings"]:
        cells = [
            item["id"],
            item["category"],
            item["knowledge"],
            f"{item['source']} / {item['stream']} / {item['index']}",
            f"{item['timestamp']} {item['clock']}",
            item["detail"],
            json.dumps(item["evidence"], ensure_ascii=False),
        ]
        rows.append(
            '<tr data-knowledge="'
            + item["knowledge"]
            + '">'
            + "".join("<td>" + html.escape(str(cell)) + "</td>" for cell in cells)
            + "</tr>"
        )
    limitations = "".join("<li>" + html.escape(text) + "</li>" for text in summary["limitations"])
    source_rows = "".join(
        "<tr>"
        + "".join(
            "<td>" + html.escape(str(value)) + "</td>"
            for value in (
                name,
                source["sha256"] or "unknown",
                source["samples"],
                source["complete"],
                source["parser"],
            )
        )
        + "</tr>"
        for name, source in summary["sources"].items()
    )
    coverage_rows = "".join(
        "<tr><td>"
        + html.escape(name)
        + "</td><td>"
        + value["status"]
        + "</td><td>"
        + html.escape(value["detail"])
        + "</td></tr>"
        for name, value in summary["coverage"].items()
    )
    return (
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>DroneHacks · Flight Forensics &amp; Replay</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#0b1320;color:#dae4f2}
body{max-width:1440px;margin:auto;padding:32px}h1{font-size:clamp(24px,4vw,40px);margin:10px 0}
h2{font-size:20px}p,li{line-height:1.6}header{border-bottom:1px solid #345;padding-bottom:24px}
.badge{color:#8de8c3;letter-spacing:.12em;font-size:12px}.panel{background:#131f30;border:1px solid #31425a;border-radius:12px;padding:20px;margin:24px 0}
.muted{color:#a6b9d2}select,button{padding:8px;border:1px solid #8195af;border-radius:4px;background:#15283d;color:white}
label{display:inline-block;margin-right:12px}input[type=range]{width:100%;margin:20px 0}pre{overflow:auto;background:#0b1320;padding:16px;border-radius:6px;max-height:360px}
.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #31425a;overflow-wrap:anywhere;min-width:90px}
th{color:#a6b9d2}#timeline{width:100%;height:100px;background:#0b1320;border-radius:6px}
tr[data-knowledge=unknown] td:nth-child(3){color:#bbc4d2}tr[data-knowledge=inferred] td:nth-child(3){color:#ffd582}
tr[data-knowledge=observed] td:nth-child(3){color:#8de8c3}.status{font-weight:bold;color:#ffd582}
</style></head><body>
<header><span class="badge">DRONEHACKS / OFFLINE EVIDENCE WORKBENCH</span>
<h1>Flight Forensics &amp; Replay</h1>
<p>Read-only post-flight evidence review · <strong>executed=False</strong></p>
<p>Local sensing plane only · <strong>3D traversability: UNKNOWN</strong></p>
<p class="muted">Synthetic fixture tests do not validate real PX4 behavior. Replay displays recorded diagnostic values only.</p></header>
<section class="panel"><h2>Clock evidence</h2><p id="alignment"></p>
<p>Physical synchronization: <strong>unknown</strong>. A supported mapping is an inferred, bounded interpolation conditional on supplied paired observations. No extrapolation or causal ordering between clocks is claimed.</p></section>
<section class="panel"><h2>Evidence replay</h2>
<label for="stream">Source / stream <select id="stream"></select></label>
<button id="previous" type="button">Previous</button> <button id="next" type="button">Next</button>
<p class="muted">Select a stream and scrub its original record order. Each stream uses its native clock. Orange points mark findings; timestamp decreases remain visible.</p>
<svg id="timeline" viewBox="0 0 1000 100" role="img" aria-label="Selected stream native timestamp timeline"></svg>
<label for="replay">Record in selected stream</label><input id="replay" type="range" min="0" max="0" value="0" step="1">
<p id="position" aria-live="polite"></p><pre id="sample"></pre></section>
<section class="panel"><h2>Inputs and provenance</h2><div class="scroll"><table>
<thead><tr><th>Source</th><th>Input SHA-256</th><th>Samples</th><th>Complete</th><th>Parser</th></tr></thead>
<tbody>"""
        + source_rows
        + """</tbody></table></div></section>
<section class="panel"><h2>Findings</h2>
<p>Observed = recorded input; inferred = review rule/model; unknown = insufficient evidence. A finding is not an instruction for a flight.</p>
<label for="knowledge">Evidence class <select id="knowledge"><option value="all">All</option><option>observed</option><option>inferred</option><option>unknown</option></select></label>
<div class="scroll"><table id="findings"><thead><tr><th>ID</th><th>Category</th><th>Knowledge</th><th>Source / stream / record</th><th>Native time</th><th>Finding</th><th>Evidence</th></tr></thead>
<tbody>"""
        + "".join(rows)
        + """</tbody></table></div></section>
<section class="panel"><h2>Rule coverage</h2><div class="scroll"><table><thead><tr><th>Rule</th><th>Input coverage</th><th>Meaning</th></tr></thead><tbody>"""
        + coverage_rows
        + """</tbody></table></div>
<h2>Review thresholds</h2><pre id="thresholds"></pre></section>
<section class="panel"><h2>Limits</h2><ul>"""
        + limitations
        + """</ul></section>
<script type="application/json" id="evidence">"""
        + data
        + """</script>
<script>
'use strict';
const report=JSON.parse(document.getElementById('evidence').textContent,(_key,value)=>{
  if(value&&typeof value==='object'&&'timestamp_text' in value)value.timestamp=value.timestamp_text;
  return value;
});
const byId=id=>document.getElementById(id), selector=byId('stream'), slider=byId('replay');
byId('alignment').textContent=report.alignment.status+': '+report.alignment.reason;
byId('thresholds').textContent=JSON.stringify(report.thresholds,null,2);
const groups=new Map();
for(const sample of report.samples){const key=sample.source+' / '+sample.stream;
  if(!groups.has(key))groups.set(key,[]);groups.get(key).push(sample);}
for(const key of groups.keys()){const option=document.createElement('option');option.value=key;option.textContent=key;selector.append(option);}
let selected=[];
function show(){
  const index=Number(slider.value), sample=selected[index];
  byId('position').textContent=sample?'Record '+(index+1)+' / '+selected.length+' · '+sample.clock+' = '+sample.timestamp:'No valid samples. Behavior unknown.';
  byId('sample').textContent=sample?JSON.stringify(sample,null,2):'unknown';
  byId('previous').disabled=!sample||index===0;byId('next').disabled=!sample||index>=selected.length-1;
  for(const node of byId('timeline').children)node.setAttribute('r',Number(node.dataset.index)===index?'7':'4');
}
function choose(){
  selected=groups.get(selector.value)||[];slider.max=String(Math.max(0,selected.length-1));slider.value='0';slider.disabled=!selected.length;
  const svg=byId('timeline');svg.replaceChildren();
  const times=selected.filter(s=>s.timestamp!==null).map(s=>BigInt(s.timestamp));
  let lo=times[0]??0n,hi=lo;for(const time of times){if(time<lo)lo=time;if(time>hi)hi=time;}
  const flagged=new Set(report.findings.filter(f=>f.source+' / '+f.stream===selector.value).map(f=>f.index));
  selected.forEach((sample,index)=>{if(sample.timestamp===null)return;
    const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
    dot.setAttribute('cx',String(20+960*Number(BigInt(sample.timestamp)-lo)/Number(hi-lo||1n)));
    dot.setAttribute('cy',String(20+60*index/Math.max(1,selected.length-1)));
    dot.setAttribute('fill',flagged.has(sample.index)?'#ffd582':'#8de8c3');dot.dataset.index=String(index);
    dot.addEventListener('click',()=>{slider.value=String(index);show();});svg.append(dot);
  });show();
}
selector.addEventListener('change',choose);slider.addEventListener('input',show);
byId('previous').addEventListener('click',()=>{slider.value=String(Math.max(0,Number(slider.value)-1));show();});
byId('next').addEventListener('click',()=>{slider.value=String(Math.min(selected.length-1,Number(slider.value)+1));show();});
byId('knowledge').addEventListener('change',event=>{for(const row of document.querySelectorAll('#findings tbody tr'))row.hidden=event.target.value!=='all'&&row.dataset.knowledge!==event.target.value;});
choose();
</script></body></html>
"""
    )


def write_reports(analysis: Analysis, output: Path) -> dict:
    summary = analysis.to_dict()
    # Never overwrite an input, including evidence supplied for clock alignment.
    inputs = [
        analysis.px4.path,
        analysis.jetson.path,
        analysis.alignment.provenance.get("descriptor"),
        analysis.alignment.provenance.get("evidence_file"),
    ]
    input_paths = {Path(path).resolve() for path in inputs if path}
    for name in REPORT_FILES:
        if (output / name).resolve() in input_paths:
            raise ValueError(f"Report output would overwrite an evidence input: {name}")
    payloads = {
        "summary.json": json.dumps(summary, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        "findings.md": ledger(summary),
        "report.html": render_html(summary),
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, text in payloads.items():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=output, prefix=".forensics-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(text)
            os.replace(temporary, output / name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return summary
