"""Generate SLR-Engine pipeline flow PNG for social sharing."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# Brand palette
BG = "#0a0e14"
BOX_FILL = "#141c28"
BOX_EDGE = "#4a6fa5"
ACCENT = "#6eb5ff"
TEXT = "#ffffff"
SUBTEXT = "#d0dce8"
LOOP = "#8ec5ff"

W, H = 1920, 1080
DPI = 150

# Short labels only â€” must read on a phone
STAGES = [
    ("1", "Scope", "Topic & seeds"),
    ("2", "Find", "Search papers"),
    ("3", "Dedupe", "Merge dupes"),
    ("4", "Screen", "Keep or drop"),
    ("5", "Access", "Get full text"),
    ("6", "Read", "Extract data"),
    ("7", "Export", "CSV & audit"),
]

BOX_W, BOX_H = 2.55, 1.7
COL_GAP = 0.28
ROW1_Y = 5.45
ROW2_Y = 2.85
START_X = 0.45


def draw_box(ax, x, y, num, title, subtitle):
    box = FancyBboxPatch(
        (x, y),
        BOX_W,
        BOX_H,
        boxstyle="round,pad=0.06,rounding_size=0.14",
        facecolor=BOX_FILL,
        edgecolor=BOX_EDGE,
        linewidth=2.4,
        zorder=2,
    )
    ax.add_patch(box)
    ax.text(
        x + BOX_W / 2,
        y + BOX_H - 0.38,
        num,
        ha="center",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=ACCENT,
        zorder=3,
    )
    ax.text(
        x + BOX_W / 2,
        y + BOX_H / 2 + 0.05,
        title,
        ha="center",
        va="center",
        fontsize=24,
        fontweight="bold",
        color=TEXT,
        zorder=3,
    )
    ax.text(
        x + BOX_W / 2,
        y + 0.38,
        subtitle,
        ha="center",
        va="center",
        fontsize=16,
        color=SUBTEXT,
        zorder=3,
    )
    cx = x + BOX_W / 2
    return cx, y, y + BOX_H


def arrow_h(ax, x1, y, x2, color=BOX_EDGE, lw=3.0):
    patch = FancyArrowPatch(
        (x1, y),
        (x2, y),
        arrowstyle="-|>",
        mutation_scale=22,
        linewidth=lw,
        color=color,
        zorder=1,
    )
    ax.add_patch(patch)


def arrow_v(ax, x, y1, y2, color=BOX_EDGE, lw=3.0):
    patch = FancyArrowPatch(
        (x, y1),
        (x, y2),
        arrowstyle="-|>",
        mutation_scale=22,
        linewidth=lw,
        color=color,
        zorder=1,
    )
    ax.add_patch(patch)


def main() -> Path:
    fig, ax = plt.subplots(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 17.2)
    ax.set_ylim(0, 9.2)
    ax.axis("off")

    # Title
    ax.text(
        8.25,
        8.35,
        "SLR-Engine",
        ha="center",
        va="center",
        fontsize=56,
        fontweight="bold",
        color=TEXT,
        family="monospace",
    )
    ax.text(
        8.25,
        7.55,
        "Research question  â†’  traceable paper shortlist",
        ha="center",
        va="center",
        fontsize=22,
        color=SUBTEXT,
    )

    positions = []
    # Row 1: steps 1â€“4
    for i in range(4):
        x = START_X + i * (BOX_W + COL_GAP)
        num, title, subtitle = STAGES[i]
        positions.append(draw_box(ax, x, ROW1_Y, num, title, subtitle))
        if i > 0:
            prev_x = START_X + (i - 1) * (BOX_W + COL_GAP)
            arrow_h(
                ax,
                prev_x + BOX_W + 0.08,
                ROW1_Y + BOX_H / 2,
                x - 0.08,
            )

    # Row 1 â†’ row 2 connector (Screen down to Access)
    arrow_v(ax, positions[3][0], ROW1_Y, ROW2_Y + BOX_H, lw=3.0)

    # Row 2: steps 5â€“7
    row2_positions = []
    for i in range(3):
        x = START_X + i * (BOX_W + COL_GAP)
        num, title, subtitle = STAGES[4 + i]
        row2_positions.append(draw_box(ax, x, ROW2_Y, num, title, subtitle))
        if i > 0:
            prev_x = START_X + (i - 1) * (BOX_W + COL_GAP)
            arrow_h(
                ax,
                prev_x + BOX_W + 0.08,
                ROW2_Y + BOX_H / 2,
                x - 0.08,
            )

    # Snowball loop: Export â†’ Dedupe
    export_right = START_X + 2 * (BOX_W + COL_GAP) + BOX_W
    dedupe_left = START_X + 2 * (BOX_W + COL_GAP)
    loop_right = START_X + 4 * (BOX_W + COL_GAP) + 0.55
    loop_mid_y = ROW1_Y + BOX_H / 2

    ax.text(
        loop_right + 0.25,
        loop_mid_y,
        "Snowball\nloop",
        ha="left",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=LOOP,
        linespacing=1.25,
        zorder=4,
    )
    arrow_h(ax, export_right + 0.08, ROW2_Y + BOX_H / 2, loop_right - 0.08, color=LOOP, lw=3.5)
    patch = FancyArrowPatch(
        (loop_right, ROW2_Y + BOX_H / 2),
        (loop_right, ROW1_Y + BOX_H / 2),
        arrowstyle="-|>",
        mutation_scale=22,
        linewidth=3.5,
        color=LOOP,
        zorder=1,
    )
    ax.add_patch(patch)
    arrow_h(
        ax,
        loop_right,
        ROW1_Y + BOX_H / 2,
        dedupe_left - 0.08,
        color=LOOP,
        lw=3.5,
    )

    # Footer â€” clear band, no overlap
    ax.add_patch(
        FancyBboxPatch(
            (0.4, 0.25),
            15.7,
            1.55,
            boxstyle="round,pad=0.04,rounding_size=0.12",
            facecolor="#0f1520",
            edgecolor=BOX_EDGE,
            linewidth=1.5,
            zorder=0,
        )
    )
    ax.text(
        8.25,
        1.15,
        "Agent decides  Â·  SLR-Engine runs the pipeline  Â·  Every step logged",
        ha="center",
        va="center",
        fontsize=18,
        color=SUBTEXT,
    )
    ax.text(
        8.25,
        0.65,
        "github.com/tuirk/SLR-Engine",
        ha="center",
        va="center",
        fontsize=17,
        color=ACCENT,
    )

    out = Path(__file__).resolve().parents[1] / "docs" / "assets" / "slr-engine-flow-linkedin.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BG, edgecolor="none", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")
    return out


if __name__ == "__main__":
    main()
