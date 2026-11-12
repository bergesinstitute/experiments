"""Shared setup for the notebooks: figures that match the site.

Import it in a hidden first code cell:

    #| include: false
    from lab import setup
    setup()
"""

import matplotlib.pyplot as plt
from cycler import cycler
from matplotlib_inline.backend_inline import set_matplotlib_formats

INK = "#212529"
ACCENT = "#860000"
MUTED = "#6c757d"


def setup() -> None:
    # SVG without a timestamp, so re-running a notebook only changes the
    # figures whose content changed.
    set_matplotlib_formats("svg", metadata={"Date": None})

    plt.rcParams.update({
        "svg.hashsalt": "experiments",
        "figure.figsize": (7.5, 4),
        "font.size": 11,
        "text.color": INK,
        "axes.edgecolor": INK,
        "axes.labelcolor": INK,
        "axes.prop_cycle": cycler(color=[ACCENT, MUTED, INK]),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#e9ecef",
        "xtick.color": INK,
        "ytick.color": INK,
        "legend.frameon": False,
        "lines.linewidth": 2,
    })
