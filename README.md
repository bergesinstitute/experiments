# Experiments

Small experiments from learning how neural networks work. Each notebook is written up as a page on [berges.ai/experiments](https://berges.ai/experiments).

## Run a notebook

```bash
uv sync
uv run jupyter lab
```

## Publish a notebook

```bash
uv run export.py formatting-test.ipynb
```

This runs the notebook from the top, saves the fresh outputs back into it, and writes the page and its figures into the berges-website checkout next to this folder (`--website` points elsewhere, `--no-execute` keeps the saved outputs). The slug is the file name.

## Notebook conventions

The first cell is a raw cell with the frontmatter:

```
---
title: Formatting test
description: One sentence for the index and search results.
published: 2026-11-12
updated: 2026-11-20
draft: true
---
```

`updated`, `draft` and `guides` are optional. Drafts show on a local site only. `guides` is a comma-separated list of berges.ai guide slugs (for example `backpropagation, how-a-neural-network-works`); those guide pages then link back to the experiment.

Markdown cells:

- Start sections at `##`. The title is the page's only `#` heading.
- Math is `$...$` inline and `$$...$$` on its own line, including `\begin{aligned}` blocks. The export turns it into MathML and stops if some LaTeX does not convert.
- Draw figures from code cells. Pasted images are rejected.

Code cells take options as `#|` lines at the top:

| Option | Effect |
|---|---|
| `#\| include: false` | Leave the whole cell out (setup, imports). |
| `#\| echo: false` | Show the output only. |
| `#\| alt: ...` | Describes the figure. Required for every figure. |
| `#\| caption: ...` | Text under the figure. |
| `#\| name: ...` | Figure file name. Defaults to `figure-1`, `figure-2`. |

Printed text and the cell's last value become an output block. Matplotlib plots and Graphviz graphs become SVG figures. End a plotting cell with `plt.show()` so no object repr leaks into the page.

Start each notebook with a hidden setup cell so plots match the site:

```python
#| include: false
from lab import setup
setup()
```
