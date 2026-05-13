"""
BCI Drone Experiment Analysis
Computes per-method and average metrics, then plots bar charts:
  1. Accuracy
  2. False Command Execution Rate
  3. Agreement Rate (Voice vs SSVEP)
  4. Average Response Latency
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -------------------------------------------------------------------
# 1. Load data
# -------------------------------------------------------------------
CSV_PATH = "/Users/jaelee/Downloads/combined.csv"   # <-- change to your file path
df = pd.read_csv(CSV_PATH)

# Normalize string columns (strip whitespace, upper-case for safe compare)
str_cols = ["Experiment_Type", "Target_Command", "Voice_Input",
            "SSVEP_Command", "Final_Executed_Command"]
for c in str_cols:
    if c in df.columns:
        df[c] = df[c].astype(str).str.strip().str.upper()
        df[c] = df[c].replace({"NAN": np.nan, "": np.nan, "NONE": np.nan})

methods = sorted(df["Experiment_Type"].dropna().unique().tolist())
print(f"Detected methods: {methods}")

# -------------------------------------------------------------------
# 2. Compute metrics per method
# -------------------------------------------------------------------
def compute_metrics(sub: pd.DataFrame) -> dict:
    total = len(sub)
    if total == 0:
        return dict(accuracy=0, false_rate=0, agreement=0, latency=0, n=0)

    # Accuracy: executed command matches target
    correct = (sub["Final_Executed_Command"] == sub["Target_Command"]).sum()
    accuracy = correct / total * 100

    # False Command Execution Rate:
    # a command WAS executed but it did NOT match the target
    executed = sub["Final_Executed_Command"].notna()
    wrong = executed & (sub["Final_Executed_Command"] != sub["Target_Command"])
    false_rate = wrong.sum() / total * 100

    # Agreement Rate: Voice and SSVEP both present and equal
    both_present = sub["Voice_Input"].notna() & sub["SSVEP_Command"].notna()
    matched = both_present & (sub["Voice_Input"] == sub["SSVEP_Command"])
    agreement = matched.sum() / total * 100

    # Average latency (skip NaN)
    latency = sub["Latency_sec"].mean()

    return dict(accuracy=accuracy, false_rate=false_rate,
                agreement=agreement, latency=latency, n=total)

results = {m: compute_metrics(df[df["Experiment_Type"] == m]) for m in methods}

# Overall average across methods (macro-average so each method weighs equally)
avg_row = {
    "accuracy":  np.mean([results[m]["accuracy"]  for m in methods]),
    "false_rate":np.mean([results[m]["false_rate"]for m in methods]),
    "agreement": np.mean([results[m]["agreement"] for m in methods]),
    "latency":   np.mean([results[m]["latency"]   for m in methods]),
    "n":         sum(results[m]["n"] for m in methods),
}
results["AVG"] = avg_row

# -------------------------------------------------------------------
# 3. Print summary table
# -------------------------------------------------------------------
summary = pd.DataFrame(results).T[
    ["n", "accuracy", "false_rate", "agreement", "latency"]
]
summary.columns = ["Trials", "Accuracy (%)", "False Cmd Rate (%)",
                   "Agreement (%)", "Avg Latency (s)"]
print("\n=== Summary ===")
print(summary.round(2).to_string())
summary.round(2).to_csv("summary_metrics.csv")

# -------------------------------------------------------------------
# 4. Plot helpers
# -------------------------------------------------------------------
def bar_plot(labels, values, title, ylabel, color, fname,
             value_fmt="{:.1f}", ylim=None):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar(labels, values, color=color, edgecolor="black")
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Method")
    if ylim:
        ax.set_ylim(ylim)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v,
                value_fmt.format(v), ha="center", va="bottom", fontsize=10)
    plt.tight_layout()
    plt.savefig(fname, dpi=160)
    plt.show()

method_labels = methods + ["AVG"]

# (1) Accuracy
bar_plot(
    method_labels,
    [results[m]["accuracy"] for m in method_labels],
    "Accuracy Comparison Across Methods",
    "Accuracy (%)", "#4C9AFF", "fig_accuracy.png",
    ylim=(0, 105),
)

# (2) False Command Execution Rate
bar_plot(
    method_labels,
    [results[m]["false_rate"] for m in method_labels],
    "False Command Execution Rate",
    "False Cmd Rate (%)", "#FF6B6B", "fig_false_rate.png",
    ylim=(0, max(20, max(results[m]["false_rate"] for m in method_labels) * 1.3)),
)

# (3) Agreement Rate
bar_plot(
    method_labels,
    [results[m]["agreement"] for m in method_labels],
    "Voice / SSVEP Agreement Rate",
    "Agreement (%)", "#6BCB77", "fig_agreement.png",
    ylim=(0, 105),
)

# (4) Average Response Latency
bar_plot(
    method_labels,
    [results[m]["latency"] for m in method_labels],
    "Average Response Latency",
    "Latency (s)", "#FFA94D", "fig_latency.png",
    value_fmt="{:.2f}",
)

print("\nSaved: summary_metrics.csv, fig_accuracy.png, fig_false_rate.png, "
      "fig_agreement.png, fig_latency.png")