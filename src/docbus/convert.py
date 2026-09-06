"""Core md -> docx conversion logic.

Mermaid fenced code blocks are rendered to PNG via mermaid-cli (mmdc) and
spliced back into the markdown as base64 data-URI images; the result is
handed to pandoc (-f gfm) for the actual docx conversion. See README.md for
why PNG (not SVG) and gfm (not pandoc's default markdown) are required.
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


class ConversionError(RuntimeError):
    """Raised for expected failures (bad diagram, pandoc failure, etc.).

    Caught at the CLI boundary and reported as a one-line message instead
    of a stack trace.
    """


def require_tool(name: str, hint: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"error: '{name}' not found on PATH.\n  {hint}")


def render_mermaid_to_png_data_uris(md_text: str) -> tuple[str, int]:
    """Replace every ```mermaid fence with a plain markdown image reference
    whose src is a base64 PNG data URI. PNG (not SVG) because pandoc can't
    reliably embed SVG into docx without rsvg-convert installed.
    """
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        def _replace(match: "re.Match[str]") -> str:
            nonlocal count
            diagram_src = match.group(1)
            digest = hashlib.sha256(diagram_src.encode("utf-8")).hexdigest()[:10]
            mmd_path = tmp_dir / f"d-{digest}.mmd"
            png_path = tmp_dir / f"d-{digest}.png"

            mmd_path.write_text(diagram_src, encoding="utf-8")
            result = subprocess.run(
                ["mmdc", "-i", str(mmd_path), "-o", str(png_path), "-b", "transparent"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise ConversionError(
                    f"mermaid-cli failed on diagram {digest}:\n{result.stderr.strip()}"
                )

            b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
            count += 1
            print(f"  rendered diagram {digest}")
            return f"\n![diagram {digest}](data:image/png;base64,{b64})\n"

        new_text = MERMAID_FENCE_RE.sub(_replace, md_text)
    return new_text, count


def convert(input_path: Path, output_path: Path) -> None:
    require_tool("mmdc", "Install with: npm install -g @mermaid-js/mermaid-cli")
    require_tool("pandoc", "Install from https://pandoc.org/installing.html")

    md_text = input_path.read_text(encoding="utf-8")
    print(f"Scanning {input_path.name} for mermaid diagrams...")
    processed_md, count = render_mermaid_to_png_data_uris(md_text)
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
