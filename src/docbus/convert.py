"""Core md -> docx conversion logic.

Mermaid fenced code blocks are rendered to an image (PNG by default, or SVG
via -f/--format) via mermaid-cli (mmdc) and spliced back into the markdown
as base64 data-URI images; the result is handed to pandoc (-f gfm) for the
actual docx conversion. See README.md for why PNG is the default (not SVG)
and gfm (not pandoc's default markdown) are required.
"""

import base64
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MERMAID_FENCE_RE = re.compile(r"```mermaid[ \t]*\n(.*?)```", re.DOTALL)
VERSION_RE = re.compile(r"(\d+)\.(\d+)")
# mmdc's raw svg output starts with an XML prolog/doctype that isn't valid
# inside a GFM raw-HTML block, so it's stripped before inlining.
XML_PROLOG_RE = re.compile(r"^\s*<\?xml[^>]*\?>\s*", re.IGNORECASE)
SVG_DOCTYPE_RE = re.compile(r"^\s*<!DOCTYPE[^>]*>\s*", re.IGNORECASE)

# Oldest versions known to support the behavior docbus relies on: pandoc's
# gfm reader (-f gfm) and mmdc's -b/--backgroundColor flag.
MIN_PANDOC_VERSION = (2, 0)
MIN_MMDC_VERSION = (10, 0)

# mermaid's built-in themes (https://mermaid.js.org/config/theming.html).
MERMAID_THEMES = ("default", "neutral", "dark", "forest", "base")

# Matches mermaid.ai's default export look (black/white, print-friendly)
# rather than mmdc's own default ("default", lavender-filled) theme.
DEFAULT_MERMAID_THEME = "neutral"

# PNG is the default (see README's "Why PNG, not SVG?"); svg is opt-in since
# it needs rsvg-convert (or cairosvg/Inkscape) on PATH for pandoc to embed it.
MERMAID_FORMATS = ("png", "svg")
DEFAULT_MERMAID_FORMAT = "png"
MERMAID_FORMAT_MIME_TYPES = {"png": "image/png", "svg": "image/svg+xml"}


class ConversionError(RuntimeError):
    """Raised for expected failures (bad diagram, pandoc failure, etc.).

    Caught at the CLI boundary and reported as a one-line message instead
    of a stack trace.
    """


def require_tool(name: str, hint: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"error: '{name}' not found on PATH.\n  {hint}")


def require_tool_version(name: str, min_version: tuple[int, int], hint: str) -> None:
    """Fail fast on a too-old install instead of risking a subtly broken docx."""
    result = subprocess.run([name, "--version"], capture_output=True, text=True)
    match = VERSION_RE.search(result.stdout or result.stderr)
    if match is None:
        print(f"warning: could not determine '{name}' version; continuing anyway", file=sys.stderr)
        return
    found = (int(match.group(1)), int(match.group(2)))
    if found < min_version:
        found_str = ".".join(str(p) for p in found)
        min_str = ".".join(str(p) for p in min_version)
        sys.exit(
            f"error: '{name}' {found_str} is too old (docbus requires >= {min_str}).\n  {hint}"
        )


def render_mermaid_to_data_uris(
    md_text: str, theme: str = DEFAULT_MERMAID_THEME, fmt: str = DEFAULT_MERMAID_FORMAT
) -> tuple[str, int]:
    """Replace every ```mermaid fence with a plain markdown image reference
    whose src is a base64 data URI, rendered by mmdc as either PNG (default)
    or SVG. PNG needs no extra dependency; SVG needs rsvg-convert (or
    cairosvg/Inkscape) on PATH for pandoc to embed it into the docx.
    """
    count = 0
    mime_type = MERMAID_FORMAT_MIME_TYPES[fmt]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        def _replace(match: "re.Match[str]") -> str:
            nonlocal count
            diagram_src = match.group(1)
            digest = hashlib.sha256(diagram_src.encode("utf-8")).hexdigest()[:10]
            mmd_path = tmp_dir / f"d-{digest}.mmd"
            out_path = tmp_dir / f"d-{digest}.{fmt}"

            mmd_path.write_text(diagram_src, encoding="utf-8")
            result = subprocess.run(
                ["mmdc", "-i", str(mmd_path), "-o", str(out_path), "-b", "transparent", "-t", theme],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise ConversionError(
                    f"mermaid-cli failed on diagram {digest}:\n{result.stderr.strip()}"
                )

            b64 = base64.b64encode(out_path.read_bytes()).decode("ascii")
            count += 1
            print(f"  rendered diagram {digest}")
            return f"\n![diagram {digest}](data:{mime_type};base64,{b64})\n"

        new_text = MERMAID_FENCE_RE.sub(_replace, md_text)
    return new_text, count


def convert(
    input_path: Path, output_path: Path,
    theme: str = DEFAULT_MERMAID_THEME, fmt: str = DEFAULT_MERMAID_FORMAT,
) -> None:
    require_tool("mmdc", "Install with: npm install -g @mermaid-js/mermaid-cli")
    require_tool("pandoc", "Install from https://pandoc.org/installing.html")
    require_tool_version("mmdc", MIN_MMDC_VERSION, "Upgrade with: npm install -g @mermaid-js/mermaid-cli")
    require_tool_version("pandoc", MIN_PANDOC_VERSION, "Upgrade at https://pandoc.org/installing.html")

    md_text = input_path.read_text(encoding="utf-8")
    print(f"Scanning {input_path.name} for mermaid diagrams...")
    processed_md, count = render_mermaid_to_data_uris(md_text, theme=theme, fmt=fmt)
    print(f"Rendered {count} diagram(s).")

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(processed_md)
        processed_path = Path(f.name)

    try:
        cmd = [
            "pandoc", "-f", "gfm", str(processed_path),
            "-o", str(output_path),
            "--metadata", f"title={input_path.stem}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ConversionError(f"pandoc failed:\n{result.stderr.strip()}")
        if result.stderr.strip():
            print(result.stderr.strip())
    finally:
        processed_path.unlink(missing_ok=True)

    print(f"Wrote {output_path}")


def render_mermaid_to_inline_svg(md_text: str, theme: str = DEFAULT_MERMAID_THEME) -> tuple[str, int]:
    """Replace every ```mermaid fence with its raw <svg>...</svg> markup,
    inlined directly as a GFM raw-HTML block. No pandoc/PNG involved -- the
    output stays a plain .md file.
    """
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        def _replace(match: "re.Match[str]") -> str:
            nonlocal count
            diagram_src = match.group(1)
            digest = hashlib.sha256(diagram_src.encode("utf-8")).hexdigest()[:10]
            mmd_path = tmp_dir / f"d-{digest}.mmd"
            svg_path = tmp_dir / f"d-{digest}.svg"

            mmd_path.write_text(diagram_src, encoding="utf-8")
            result = subprocess.run(
                # -I/--svgId: without it every diagram gets id="my-svg", which
                # collides (duplicate IDs, broken CSS scoping) once more than
                # one is inlined into the same document.
                ["mmdc", "-i", str(mmd_path), "-o", str(svg_path), "-b", "transparent",
                 "-t", theme, "-I", f"d-{digest}"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise ConversionError(
                    f"mermaid-cli failed on diagram {digest}:\n{result.stderr.strip()}"
                )

            svg_markup = svg_path.read_text(encoding="utf-8")
            svg_markup = XML_PROLOG_RE.sub("", svg_markup)
            svg_markup = SVG_DOCTYPE_RE.sub("", svg_markup).strip()
            count += 1
            print(f"  rendered diagram {digest}")
            return f"\n{svg_markup}\n"

        new_text = MERMAID_FENCE_RE.sub(_replace, md_text)
    return new_text, count


def embed_svg(input_path: Path, output_path: Path, theme: str = DEFAULT_MERMAID_THEME) -> None:
    """md -> md: replace every mermaid fence with inline <svg> markup. No pandoc."""
    require_tool("mmdc", "Install with: npm install -g @mermaid-js/mermaid-cli")
    require_tool_version("mmdc", MIN_MMDC_VERSION, "Upgrade with: npm install -g @mermaid-js/mermaid-cli")

    md_text = input_path.read_text(encoding="utf-8")
    print(f"Scanning {input_path.name} for mermaid diagrams...")
    processed_md, count = render_mermaid_to_inline_svg(md_text, theme=theme)
    print(f"Rendered {count} diagram(s).")

    output_path.write_text(processed_md, encoding="utf-8")
    print(f"Wrote {output_path}")
