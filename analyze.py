import json
import math
import os
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

from judge import KEY, key, load

# deny and hedge are merged: hand labels showed the judge can't reliably separate them (see agreement below)
MERGED = {"deny": "no_detection", "hedge": "no_detection"}
CATS = ["no_detection", "nonspecific_claim", "specific_fabrication"]
COLORS = {"no_detection": "#2a78d6", "nonspecific_claim": "#eb8a3c", "specific_fabrication": "#c42b2a"}
NAMES = {"claude-sonnet-5": "Sonnet 5", "gpt-5.2": "GPT-5.2", "qwen/qwen3.6-27b": "Qwen3.6-27B"}


def wilson(k, n, z=1.96):
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0, c - h), min(1, c + h))


def fmt(k, n):
    lo, hi = wilson(k, n)
    return f"{k / n:5.0%} [{lo:.0%}–{hi:.0%}]" if n else "   –"


def main():
    responses = {key(r): r for r in load("responses.jsonl")}
    labels = load("labels.jsonl")
    models = [m for m in NAMES if any(l["model"] == m for l in labels)]
    levels = sorted({l["level"] for l in labels})

    cells = defaultdict(list)
    for l in labels:
        cells[l["model"], l["level"]].append(l)

    print("False detection rate (nonspecific + specific) and fabrication rate (specific), 95% Wilson CI\n")
    print(f"{'model':<14}{'lvl':<5}{'n':>4}  {'false detection':<20}{'fabrication':<20}{'challenges':<12}{'prior work':<10}")
    for m in models:
        for lvl in levels:
            c = cells[m, lvl]
            n = len(c)
            counts = Counter(l["label"] for l in c)
            fd = counts["nonspecific_claim"] + counts["specific_fabrication"]
            fab = counts["specific_fabrication"]
            ch = sum(l["challenges_premise"] for l in c)
            pw = sum(l["references_prior_work"] for l in c)
            print(f"{NAMES[m]:<14}{lvl:<5}{n:>4}  {fmt(fd, n):<20}{fmt(fab, n):<20}{ch:<12}{pw:<10}")
        print()

    # Figure: stacked bars per level, grouped by model
    fig, axes = plt.subplots(1, len(models), figsize=(3.2 * len(models), 3.4), sharey=True)
    axes = [axes] if len(models) == 1 else axes
    for ax, m in zip(axes, models):
        bottoms = [0] * len(levels)
        for lab in CATS:
            vals = []
            for lvl in levels:
                c = cells[m, lvl]
                vals.append(sum(MERGED.get(l["label"], l["label"]) == lab for l in c) / len(c) if c else 0)
            ax.bar(levels, vals, bottom=bottoms, color=COLORS[lab], width=0.7,
                   edgecolor="white", linewidth=1.5, label=lab.replace("_", " "))
            bottoms = [b + v for b, v in zip(bottoms, vals)]
        ax.set_title(NAMES[m], fontsize=10)
        ax.set_ylim(0, 1)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=8, colors="#52514e")
        ax.grid(axis="y", color="#e5e4e0", linewidth=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("share of responses", fontsize=9, color="#52514e")
    fig.supxlabel("suggestion level", fontsize=9, color="#52514e")
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles[::-1], names[::-1], loc="center right", fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0, 0.84, 1))
    fig.savefig("figure.png", dpi=200)
    print("wrote figure.png\n")

    # Examples: one specific fabrication per model at the highest level where one exists
    print("Example fabrications:")
    for m in models:
        for lvl in reversed(levels):
            ex = next((l for l in cells[m, lvl] if l["label"] == "specific_fabrication"), None)
            if ex:
                text = responses[key(ex)]["response_text"].strip().replace("\n", " ")
                print(f"\n[{NAMES[m]} {lvl}] concept={ex.get('concept')!r}\n  {text[:400]}")
                break

    # Judge agreement with hand labels
    if os.path.exists("hand_labels.jsonl"):
        hand = [h for h in load("hand_labels.jsonl") if h["label"]]
        judged = {key(l): l for l in labels}
        pairs = [(h, judged[key(h)]) for h in hand if key(h) in judged]
        if pairs:
            merged = lambda x: MERGED.get(x, x)
            n = len(pairs)
            agree = sum(h["label"] == j["label"] for h, j in pairs)
            agree_m = sum(merged(h["label"]) == merged(j["label"]) for h, j in pairs)
            print(f"\nJudge agreement with hand labels (n={n}):")
            print(f"  merged labels (no_detection / nonspecific / specific): {agree_m}/{n} = {agree_m / n:.0%}")
            print(f"  all four labels: {agree}/{n} = {agree / n:.0%}")
            for f in ("challenges_premise", "references_prior_work"):
                a = sum(h[f] == j[f] for h, j in pairs)
                print(f"  {f}: {a}/{n} = {a / n:.0%}")
            print("  hand labels:", dict(Counter(h["label"] for h, _ in pairs)))
            print("  four-label disagreements:")
            for h, j in pairs:
                if h["label"] != j["label"]:
                    print(f"  {dict(zip(KEY, key(h)))}: hand={h['label']} judge={j['label']}")


if __name__ == "__main__":
    main()
