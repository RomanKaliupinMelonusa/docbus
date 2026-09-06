"""Core md -> docx conversion logic.

Mermaid fenced code blocks are rendered to an image (PNG by default, or SVG
via -f/--format) via mermaid-cli (mmdc) and spliced back into the markdown
as base64 data-URI images; the result is handed to pandoc (-f gfm) for the
actual docx conversion. See README.md for why PNG is the default (not SVG)
and gfm (not pandoc's default markdown) are required.
"""

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

MERMAID_FENCE_RE = re.compile(r"```mermaid[ \t]*\n(.*?)```", re.DOTALL)
VERSION_RE = re.compile(r"(\d+)\.(\d+)")

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

# neutral is otherwise all-grayscale by design (mmdc/mermaid drops the note's
# yellow highlight entirely under it) -- restore mermaid's own "default" theme
# note colors so callouts stay visible, matching mermaid.ai's neutral export.
NEUTRAL_THEME_NOTE_VARIABLES = {
    "noteBkgColor": "#fff5ad",
    "noteBorderColor": "#aaaa33",
    "noteTextColor": "#333333",
}


# pandoc's default docx template only swaps `code` spans to a monospace font
# (no background), so inline code is invisible inside anything but plain body
# text (e.g. it blends into and inherits bold from headings) -- add a light
# shading box and force non-bold, GFM-style.
INLINE_CODE_SHADING_FILL = "EDEDED"
VERBATIM_STYLE_RE = re.compile(
    r'(<w:style\b[^>]*w:styleId="VerbatimChar"[^>]*>.*?<w:rPr>)(.*?)(</w:rPr>\s*</w:style>)',
    re.DOTALL,
)


class ConversionError(RuntimeError):
    """Raised for expected failures (bad diagram, pandoc failure, etc.).

    Caught at the CLI boundary and reported as a one-line message instead
    of a stack trace.
    """


def _shade_inline_code(docx_path: Path) -> None:
    """Patch pandoc's VerbatimChar style in-place to add a background shade."""
    with zipfile.ZipFile(docx_path) as zin:
        infos = zin.infolist()
        styles_xml = zin.read("word/styles.xml").decode("utf-8")

    extra_rpr = (
        f'<w:shd w:val="clear" w:color="auto" w:fill="{INLINE_CODE_SHADING_FILL}" />'
        '<w:b w:val="0" /><w:bCs w:val="0" />'
    )
    patched, n = VERBATIM_STYLE_RE.subn(
        lambda m: m.group(1) + m.group(2) + extra_rpr + m.group(3), styles_xml
    )
    if n == 0:
        return

    tmp_path = docx_path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx_path) as zin, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            data = patched.encode("utf-8") if info.filename == "word/styles.xml" else zin.read(info.filename)
            zout.writestr(info, data)
    tmp_path.replace(docx_path)


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


def _mmdc_theme_args(theme: str, tmp_dir: Path) -> list[str]:
    """Usually just -t theme; neutral additionally needs a configFile to
    restore its stripped-out note color (see NEUTRAL_THEME_NOTE_VARIABLES)."""
    if theme != "neutral":
        return ["-t", theme]
    config_path = tmp_dir / "mermaid-config.json"
    config_path.write_text(
        json.dumps({"theme": theme, "themeVariables": NEUTRAL_THEME_NOTE_VARIABLES}),
        encoding="utf-8",
    )
    return ["-c", str(config_path)]


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
        theme_args = _mmdc_theme_args(theme, tmp_dir)

        def _replace(match: "re.Match[str]") -> str:
            nonlocal count
            diagram_src = match.group(1)
            digest = hashlib.sha256(diagram_src.encode("utf-8")).hexdigest()[:10]
            mmd_path = tmp_dir / f"d-{digest}.mmd"
            out_path = tmp_dir / f"d-{digest}.{fmt}"

            mmd_path.write_text(diagram_src, encoding="utf-8")
            result = subprocess.run(
                ["mmdc", "-i", str(mmd_path), "-o", str(out_path), "-b", "transparent", *theme_args],
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

    _shade_inline_code(output_path)
    print(f"Wrote {output_path}")
