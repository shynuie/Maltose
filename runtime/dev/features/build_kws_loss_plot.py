from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "dev/features/kws_training_loss.log"
OUT = ROOT / "dev/features/kws-training-loss.html"
PATTERN = re.compile(
    r"Evaluate epoch:\s+(\d+), loss_train:\s+([0-9.]+), loss_val:\s+([0-9.]+)"
)

rows = []
for line in LOG.read_text().splitlines():
    match = PATTERN.search(line)
    if match:
        rows.append(
            {
                "epoch": int(match.group(1)),
                "train": float(match.group(2)),
                "validation": float(match.group(3)),
            }
        )

data = json.dumps(rows, separators=(",", ":"))
fragment = f'''<div id="kws-loss-plot" class="kws-loss-plot">
  <h2>Raw real+TTS 训练 loss</h2>
  <p class="text-muted">Epoch 1–{rows[-1]["epoch"]} · clean 35% · dynamic augmentation 65%</p>
  <svg role="img" aria-labelledby="kws-loss-title kws-loss-desc" viewBox="0 0 760 420">
    <title id="kws-loss-title">Training and validation loss by epoch</title>
    <desc id="kws-loss-desc">Two curves showing training loss and validation loss across {len(rows)} completed epochs.</desc>
  </svg>
</div>
<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
<script>
(() => {{
  const root = document.getElementById("kws-loss-plot");
  const svg = d3.select(root.querySelector("svg"));
  const data = {data};
  const width = 760, height = 420;
  const margin = {{top: 24, right: 28, bottom: 52, left: 64}};
  const x = d3.scaleLinear().domain(d3.extent(data, d => d.epoch)).range([margin.left, width - margin.right]);
  const y = d3.scaleLinear().domain([0, d3.max(data, d => Math.max(d.train, d.validation)) * 1.08]).nice().range([height - margin.bottom, margin.top]);
  const line = key => d3.line().x(d => x(d.epoch)).y(d => y(d[key])).curve(d3.curveMonotoneX);
  svg.selectAll(".axis").remove();
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${{height - margin.bottom}})`).call(d3.axisBottom(x).ticks(8).tickFormat(d3.format("d")));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${{margin.left}},0)`).call(d3.axisLeft(y).ticks(7));
  svg.append("text").attr("class", "axis-title").attr("data-axis", "x").attr("x", width / 2).attr("y", height - 10).attr("text-anchor", "middle").text("Epoch");
  svg.append("text").attr("class", "axis-title").attr("data-axis", "y").attr("transform", `translate(16,${{height / 2}}) rotate(-90)`).attr("text-anchor", "middle").text("Loss");
  const series = [
    {{key: "train", label: "Train loss", color: "var(--viz-series-1)"}},
    {{key: "validation", label: "Validation loss", color: "var(--viz-series-2)"}}
  ];
  svg.selectAll(".loss-line").data(series).join("path").attr("class", "loss-line")
    .attr("fill", "none").attr("stroke", d => d.color).attr("stroke-width", 2)
    .attr("d", d => line(d.key)(data));
  const last = data[data.length - 1];
  svg.selectAll(".end-label").data(series).join("text").attr("class", "end-label")
    .attr("x", width - margin.right - 4).attr("y", d => y(last[d.key]) - 7)
    .attr("text-anchor", "end").attr("fill", d => d.color).text(d => `${{d.label}} ${{last[d.key].toFixed(4)}}`);
  svg.selectAll(".point-group").data(series).join("g").attr("class", "point-group")
    .attr("fill", d => d.color).each(function(s) {{
      d3.select(this).selectAll("circle").data(data).join("circle").attr("cx", d => x(d.epoch)).attr("cy", d => y(d[s.key])).attr("r", 2.2)
        .attr("data-tooltip", d => `Epoch ${{d.epoch}} · ${{s.label}}: ${{d[s.key].toFixed(4)}}`);
    }});
}})();
</script>
<style>
#kws-loss-plot {{ color: var(--foreground); font-family: inherit; }}
#kws-loss-plot h2 {{ margin: 0 0 4px; font-weight: 500; }}
#kws-loss-plot p {{ margin: 0 0 8px; }}
#kws-loss-plot svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
#kws-loss-plot .axis path, #kws-loss-plot .axis line {{ stroke: var(--border); }}
#kws-loss-plot .axis text, #kws-loss-plot .axis-title, #kws-loss-plot .end-label {{ fill: var(--foreground); font-size: 12px; }}
</style>
'''
OUT.write_text(fragment)
print(f"wrote {{OUT}} with {{len(rows)}} epochs")
