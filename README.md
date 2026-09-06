# docbus

Convert a Markdown file (with embedded Mermaid diagrams) into a `.docx`,
via [pandoc](https://pandoc.org) and [mermaid-cli](https://github.com/mermaid-js/mermaid-cli).

`docbus` is a standalone CLI — install it once with the script below and call
it as a plain subprocess from any project, the same way you'd call `pandoc`
or `jq`, regardless of what language that project is written in.

## Install

macOS / Linux:

```sh
curl -sSfL https://raw.githubusercontent.com/RomanKaliupinMelonusa/docbus/main/install.sh | sh
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/RomanKaliupinMelonusa/docbus/main/install.ps1 | iex
```

Both scripts bootstrap [`uv`](https://docs.astral.sh/uv/) if it isn't already
present, then use `uv tool install` to put `docbus` on `PATH` in an isolated
environment.

### Runtime dependencies

`docbus` shells out to two tools that must already be installed on the
machine running it — the installer does not vendor or install them:

- **pandoc** (>= 2.0) — <https://pandoc.org/installing.html>
- **mmdc** (mermaid-cli, >= 10.0) — `npm install -g @mermaid-js/mermaid-cli`

If either is missing, or is older than the minimum version above, `docbus`
fails immediately with a one-line message telling you which one and how to
install/upgrade it, instead of a stack trace or a subtly broken `.docx`.

## Usage

```sh
docbus convert input.md
docbus convert input.md -o output.docx
```

This:

1. Reads `input.md`.
2. Renders every ` ```mermaid ` fenced block to a PNG via `mmdc` and embeds
   it as a base64 image.
3. Runs `pandoc -f gfm` on the result to produce the `.docx`.
4. Cleans up all temp files. The only new file left on disk is the `.docx`.

`docbus` is subcommand-based (`docbus convert ...`) from day one so future
verbs (e.g. `docbus push`) can be added without breaking existing callers.

## Scope

In scope: single-file `.md` -> `.docx` conversion, with Mermaid diagrams
rendered to embedded PNGs.

Out of scope (by design, not yet implemented): Confluence or other API
integrations, HTML output, folder/batch conversion, watch mode, and a
persistent render cache.

## Why PNG, not SVG? Why `-f gfm`?

- **PNG for Mermaid renders.** Pandoc can't reliably embed SVG into a docx
  unless `rsvg-convert` (or cairosvg/Inkscape) is also installed — without
  it, pandoc falls back to an embed Word typically shows as broken. PNG
  embeds cleanly with no extra dependency.
- **`pandoc -f gfm`.** Pandoc's default markdown dialect has extensions
  enabled that GitHub-flavored markdown doesn't, which can subtly change
  how tables, task lists, and autolinks render. `-f gfm` matches GitHub's
  rendering rules.

## License

[MIT](LICENSE)
