"""Export a notebook as an experiment page on berges.ai.

    uv run export.py formatting-test.ipynb

Runs the notebook top to bottom, saves the fresh outputs back into it (so the
copy on GitHub matches the page), then writes into the website checkout:

    resources/experiments/<slug>.md
    public/img/experiments/<slug>/<figure>.svg

The slug is the notebook's file name. See the README for the cell conventions.
"""

import argparse
import base64
import hashlib
import html
import re
import shutil
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from latex2mathml.converter import convert
from nbclient import NotebookClient

REPO_URL = "https://github.com/bergesinstitute/experiments"
BRANCH = "master"
ROOT = Path(__file__).resolve().parent
DEFAULT_WEBSITE = ROOT.parent / "berges-website"
IMAGE_URL = "/img/experiments"

REQUIRED_KEYS = ("title", "description", "published")
OPTIONAL_KEYS = ("updated", "draft", "guides")
CELL_OPTIONS = ("include", "echo", "alt", "caption", "name")

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
OPTION = re.compile(r"^#\|\s*([\w-]+)\s*:\s*(.*)$")
CODE = re.compile(r"(^```.*?^```[ \t]*$|`[^`\n]*`)", re.S | re.M)
DISPLAY_MATH = re.compile(r"\$\$(.+?)\$\$", re.S)
INLINE_MATH = re.compile(r"(?<![\\$])\$(?=\S)([^$\n]*?\S)\$(?![\d$])")
OBJECT_REPR = re.compile(r"^\[?<[^>]* at 0x[0-9a-f]+>\]?$")


class ExportError(Exception):
    pass


@dataclass
class Figure:
    name: str
    extension: str
    content: bytes
    width: int
    height: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a notebook as an experiment page.")
    parser.add_argument("notebook", type=Path)
    parser.add_argument("--website", type=Path, default=DEFAULT_WEBSITE, help="berges-website checkout")
    parser.add_argument("--no-execute", action="store_true", help="use the outputs already saved in the notebook")
    args = parser.parse_args()

    try:
        export(args.notebook.resolve(), args.website.resolve(), execute=not args.no_execute)
    except ExportError as error:
        sys.exit(f"export failed: {error}")


def export(path: Path, website: Path, execute: bool) -> None:
    slug = path.stem
    if not SLUG.fullmatch(slug):
        raise ExportError(f"'{slug}' is not a valid slug: use lowercase letters, digits and hyphens")
    if not (website / "artisan").exists():
        raise ExportError(f"{website} is not the berges-website checkout (pass --website)")

    notebook = nbformat.read(path, as_version=4)

    if execute:
        print(f"running {path.name} ...")
        # IPC keeps the kernel on local sockets (in a temp folder) instead of TCP ports.
        sockets = tempfile.mkdtemp(prefix="experiments-kernel-")
        manager = KernelManager(kernel_name="python3", transport="ipc", ip=f"{sockets}/kernel")
        client = NotebookClient(notebook, km=manager, timeout=600,
                                resources={"metadata": {"path": str(path.parent)}})
        try:
            client.execute()
        except Exception as error:
            raise ExportError(f"the notebook failed to run:\n{error}") from error
        finally:
            # nbclient leaves a kernel it was handed running, so stop it here.
            if manager.has_kernel:
                manager.shutdown_kernel()
            shutil.rmtree(sockets, ignore_errors=True)
        nbformat.write(notebook, path)

    meta, cells = read_frontmatter(notebook)
    parts: list[str] = []
    figures: list[Figure] = []

    for number, cell in enumerate(cells, start=2):
        if cell.cell_type == "markdown":
            parts.append(markdown_cell(cell, number))
        elif cell.cell_type == "code":
            parts.extend(code_cell(cell, number, slug, figures))

    page = website / "resources" / "experiments" / f"{slug}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    notebook_url = f"{REPO_URL}/blob/{BRANCH}/{path.relative_to(ROOT).as_posix()}"
    page.write_text(frontmatter_block(meta, notebook_url) + "\n\n".join(p for p in parts if p) + "\n")

    images = website / "public" / "img" / "experiments" / slug
    shutil.rmtree(images, ignore_errors=True)
    if figures:
        images.mkdir(parents=True)
        for figure in figures:
            (images / f"{figure.name}.{figure.extension}").write_bytes(figure.content)

    print(f"wrote {page.relative_to(website)}")
    if figures:
        print(f"wrote {len(figures)} figure(s) to {images.relative_to(website)}/")


def read_frontmatter(notebook) -> tuple[dict[str, str], list]:
    cells = notebook.cells
    first = cells[0] if cells else None
    source = first.source.strip() if first is not None else ""

    if first is None or first.cell_type != "raw" or not source.startswith("---") or not source.endswith("---"):
        raise ExportError("the first cell must be a raw cell with the frontmatter between --- lines")

    meta: dict[str, str] = {}
    for line in source.strip("-").strip().splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not separator or key not in REQUIRED_KEYS + OPTIONAL_KEYS:
            raise ExportError(f"unknown frontmatter line: {line!r}")
        meta[key] = value

    for key in REQUIRED_KEYS:
        if not meta.get(key):
            raise ExportError(f"frontmatter is missing {key}")
    for key in ("published", "updated"):
        if key in meta and not DATE.fullmatch(meta[key]):
            raise ExportError(f"{key} must be a YYYY-MM-DD date")
    if meta.get("draft", "false") not in ("true", "false"):
        raise ExportError("draft must be true or false")
    if "guides" in meta:
        guides = [guide.strip() for guide in meta["guides"].split(",")]
        if not all(SLUG.fullmatch(guide) for guide in guides):
            raise ExportError("guides must be a comma-separated list of guide slugs")
        meta["guides"] = ", ".join(guides)

    return meta, cells[1:]


def frontmatter_block(meta: dict[str, str], notebook_url: str) -> str:
    lines = [f"{key}: {meta[key]}" for key in REQUIRED_KEYS]
    if meta.get("updated"):
        lines.append(f"updated: {meta['updated']}")
    if meta.get("draft") == "true":
        lines.append("draft: true")
    if meta.get("guides"):
        lines.append(f"guides: {meta['guides']}")
    lines.append(f"notebook: {notebook_url}")

    return "---\n" + "\n".join(lines) + "\n---\n\n"


# Markdown cells ------------------------------------------------------------

def markdown_cell(cell, number: int) -> str:
    if cell.get("attachments"):
        raise ExportError(f"cell {number}: pasted images are not supported, draw figures from a code cell")

    pieces = CODE.split(cell.source.strip())
    out = []
    for index, piece in enumerate(pieces):
        if index % 2:  # code span or fenced block: leave untouched
            out.append(piece)
            continue
        if re.search(r"^# ", piece, re.M):
            raise ExportError(f"cell {number}: the page title is the h1, start sections at ##")
        piece = DISPLAY_MATH.sub(lambda m: display_math(m.group(1), number), piece)
        piece = INLINE_MATH.sub(lambda m: checked(convert(m.group(1).strip()), m.group(1), number), piece)
        out.append(piece)

    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()


def display_math(latex: str, number: int) -> str:
    latex = latex.strip()
    aligned = re.fullmatch(r"\\begin\{aligned\}(.*)\\end\{aligned\}", latex, re.S)
    if aligned:
        latex = aligned.group(1).strip()
    if r"\begin{" in latex:
        raise ExportError(f"cell {number}: only the aligned environment is supported in math")

    # On its own line, lim, max and min take their subscript underneath.
    latex = re.sub(r"\\(lim|max|min|sup|inf)(?=\s*_)", r"\\\1\\limits", latex)
    rows = [row.strip() for row in re.split(r"\\\\", latex) if row.strip()]

    if len(rows) == 1 and "&" not in rows[0]:
        mathml = checked(convert(rows[0], display="block"), rows[0], number)
    else:
        # MathML Core has no aligned environment: build the table by hand,
        # right-aligned before each &, left-aligned after. Cells default to
        # the compact inline style, so each one asks for full-size fractions.
        table = ""
        for row in rows:
            cells = row.split("&")
            table += "<mtr>"
            for index, cell in enumerate(cells):
                align = "right" if index % 2 == 0 else "left"
                inner = inner_mathml(checked(convert(cell.strip()), cell, number)) if cell.strip() else ""
                # Chrome aligns MathML cell content only with the -webkit- value;
                # Firefox reads columnalign.
                style = f"text-align: {align}; text-align: -webkit-{align}; padding: 0.3em 0;"
                table += f'<mtd columnalign="{align}" style="{style}"><mstyle displaystyle="true">{inner}</mstyle></mtd>'
            table += "</mtr>"
        mathml = f'<math xmlns="http://www.w3.org/1998/Math/MathML" display="block"><mtable>{table}</mtable></math>'

    # A div makes it an HTML block, so the markdown parser leaves it alone.
    return f'\n\n<div class="math-display">{mathml}</div>\n\n'


def inner_mathml(mathml: str) -> str:
    return re.sub(r"^<math[^>]*>|</math>$", "", mathml)


def checked(mathml: str, latex: str, number: int) -> str:
    if "\\" in mathml or "<mi>&</mi>" in mathml:
        raise ExportError(f"cell {number}: this LaTeX does not convert to MathML: {latex.strip()!r}")
    return mathml


# Code cells ----------------------------------------------------------------

def code_cell(cell, number: int, slug: str, figures: list[Figure]) -> list[str]:
    lines = cell.source.splitlines()
    options: dict[str, str] = {}
    while lines and (match := OPTION.match(lines[0])):
        if match.group(1) not in CELL_OPTIONS:
            raise ExportError(f"cell {number}: unknown option #| {match.group(1)}")
        options[match.group(1)] = match.group(2).strip()
        lines.pop(0)

    if options.get("include") == "false":
        return []

    parts = []
    code = "\n".join(lines).strip("\n")
    if code and options.get("echo") != "false":
        parts.append(fenced(code, "python"))

    text: list[str] = []

    def flush() -> None:
        joined = "".join(text).strip("\n")
        if joined:
            parts.append(fenced(joined, "output"))
        text.clear()

    for output in cell.get("outputs", []):
        kind = output.output_type
        if kind == "error":
            raise ExportError(f"cell {number} raised {output.ename}: {output.evalue}")
        if kind == "stream":
            if output.name == "stdout":
                text.append(output.text)
            continue
        if kind not in ("execute_result", "display_data"):
            continue

        data = output.data
        if "image/svg+xml" in data or "image/png" in data:
            flush()
            parts.append(figure_html(data, options, number, slug, figures))
        elif "text/plain" in data:
            value = data["text/plain"]
            if OBJECT_REPR.match(value.strip()):
                print(f"cell {number}: skipped an object repr, end the cell with ; or plt.show()")
                continue
            text.append(value + "\n")

    flush()

    return parts


def figure_html(data, options: dict[str, str], number: int, slug: str, figures: list[Figure]) -> str:
    alt = options.get("alt")
    if not alt:
        raise ExportError(f"cell {number}: a figure needs a '#| alt: ...' line describing it")

    name = options.get("name") or f"figure-{len(figures) + 1}"
    taken = {figure.name for figure in figures}
    if name in taken:
        suffix = 2
        while f"{name}-{suffix}" in taken:
            suffix += 1
        name = f"{name}-{suffix}"
    if not SLUG.fullmatch(name):
        raise ExportError(f"cell {number}: figure name '{name}' must be lowercase letters, digits and hyphens")

    if "image/svg+xml" in data:
        svg = data["image/svg+xml"]
        figure = Figure(name, "svg", svg.encode(), *svg_size(svg))
    else:
        png = base64.b64decode(data["image/png"])
        width, height = struct.unpack(">II", png[16:24])
        figure = Figure(name, "png", png, width, height)
    figures.append(figure)

    version = hashlib.sha1(figure.content).hexdigest()[:8]
    src = f"{IMAGE_URL}/{slug}/{figure.name}.{figure.extension}?v={version}"
    lines = [
        '<figure class="experiment-figure">',
        f'<img src="{src}" alt="{html.escape(alt)}" width="{figure.width}" height="{figure.height}" loading="lazy">',
    ]
    if options.get("caption"):
        lines.append(f"<figcaption>{html.escape(options['caption'])}</figcaption>")
    lines.append("</figure>")

    return "\n".join(lines)


def svg_size(svg: str) -> tuple[int, int]:
    root = re.search(r"<svg\b[^>]*>", svg)
    if root is None:
        raise ExportError("an SVG output has no <svg> element")

    def dimension(attribute: str) -> int:
        match = re.search(rf'\b{attribute}="([\d.]+)(pt|px)?"', root.group(0))
        if match is None:
            raise ExportError(f"an SVG output has no {attribute}")
        value = float(match.group(1))
        return round(value * 4 / 3 if match.group(2) == "pt" else value)

    return dimension("width"), dimension("height")


def fenced(text: str, info: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{info}\n{text}\n{fence}"


if __name__ == "__main__":
    main()
