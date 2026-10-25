#!/usr/bin/env python3
"""Compare dynamic (SDN reroute) vs static baseline: prints a table, saves results/loss_comparison.png"""
import csv, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

R = "results"


def load(mode):
    try:
        return (list(csv.DictReader(open(f"{R}/{mode}_windows.csv"))),
                json.load(open(f"{R}/{mode}_summary.json")),
                json.load(open(f"{R}/{mode}_sender.json")))
    except FileNotFoundError:
        return None


data = {m: load(m) for m in ("static", "dynamic")}
data = {m: d for m, d in data.items() if d}

fig, ax = plt.subplots(figsize=(9, 4.5))
for m, (rows, summ, _) in data.items():
    ax.plot([float(r["t"]) for r in rows], [100 * float(r["loss"]) for r in rows],
            marker="o", ms=3, label=f"{m} ({'SDN reroute' if m == 'dynamic' else 'no reroute'})")
    if summ.get("alert_at_s"):
        ax.axvline(summ["alert_at_s"], ls="--", color="gray", label="controller alerted")
ax.set_xlabel("time since first packet (s)")
ax.set_ylabel("first-transmission loss per window (%)")
ax.set_title("Packet loss before and after SDN rerouting")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(f"{R}/loss_comparison.png", dpi=150)

rows = [
    ("Loss while degraded (%)", "r", "loss_degraded_pct"),
    ("Loss after recovery (%)", "r", "loss_after_recovery_pct"),
    ("Detection time (s)", "r", "detection_time_s"),
    ("Recovery time (s)", "r", "recovery_time_s"),
    ("Retransmissions", "s", "retransmissions"),
    ("Failed packets", "s", "failed"),
    ("Mean latency (ms)", "s", "mean_latency_ms"),
    ("p95 latency (ms)", "s", "p95_latency_ms"),
    ("Total time (s)", "s", "duration_s"),
]
print(f"{'metric':28s}" + "".join(f"{m:>12s}" for m in data))
for label, src, key in rows:
    vals = [str(d[1 if src == 'r' else 2].get(key)) for d in data.values()]
    print(f"{label:28s}" + "".join(f"{v:>12s}" for v in vals))
print(f"\nplot saved to {R}/loss_comparison.png")
