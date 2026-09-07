"""Command-line entry point for docbus.

Subcommands from day one (`docbus convert ...`) so future verbs like
`push`/`pull` can be added without a breaking CLI shape change.
"""

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .convert import (
    DEFAULT_MERMAID_BACKGROUND,
    DEFAULT_MERMAID_FORMAT,
    DEFAULT_MERMAID_THEME,
    MERMAID_FORMATS,
    MERMAID_THEMES,
    ConversionError,
    convert,
)

_BOLD = "\033[1m"
_CYAN = "\033[36m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _use_color() -> bool:
    # NO_COLOR (https://no-color.org) always wins; otherwise only color a real terminal.
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Bolds section headings and option/command names on a real terminal."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=30)

    def start_section(self, heading: "str | None") -> None:
        if _use_color() and heading:
            heading = f"{_BOLD}{_CYAN}{heading}{_RESET}"
        super().start_section(heading)

    def _format_action_invocation(self, action: argparse.Action) -> str:
        text = super()._format_action_invocation(action)
        if _use_color() and text:
            return f"{_BOLD}{text}{_RESET}"
        return text


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        label = f"{_BOLD}{_RED}error:{_RESET}" if _use_color() else "error:"
        self.exit(2, f"{self.prog}: {label} {message}\n")


def _epilog() -> str:
    heading = f"{_BOLD}{_CYAN}examples:{_RESET}" if _use_color() else "examples:"
    return (
        f"{heading}\n"
        "  docbus convert report.md              # writes report.docx\n"
        "  docbus convert report.md -o out.docx  # -o/--output: custom output path\n"
        "\n"
        "See 'docbus convert --help' for the full list of convert options.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="docbus",
        description="Convert Markdown (with embedded Mermaid diagrams) to .docx.",
        epilog=_epilog(),
        formatter_class=_HelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"docbus {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    convert_parser = subparsers.add_parser(
        "convert", help="Convert a single .md file to .docx",
        formatter_class=_HelpFormatter,
    )
    convert_parser.add_argument("input", type=Path, help="Path to the source .md file")
    convert_parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output .docx path (default: <input>.docx). Order vs. input doesn't matter.",
    )
    convert_parser.add_argument(
        "-t", "--theme", choices=MERMAID_THEMES, default=DEFAULT_MERMAID_THEME,
        metavar="THEME",
        help=f"Mermaid theme passed to mmdc (default: {DEFAULT_MERMAID_THEME}). "
             f"Choices: {', '.join(MERMAID_THEMES)}.",
    )
    convert_parser.add_argument(
        "-f", "--format", choices=MERMAID_FORMATS, default=DEFAULT_MERMAID_FORMAT,
        metavar="FORMAT",
        help=f"Image format mmdc renders diagrams to (default: {DEFAULT_MERMAID_FORMAT}). "
             f"Choices: {', '.join(MERMAID_FORMATS)}. svg needs rsvg-convert "
             "(or cairosvg/Inkscape) on PATH for pandoc to embed it.",
    )
    convert_parser.add_argument(
        "-b", "--background", default=DEFAULT_MERMAID_BACKGROUND,
        metavar="COLOR",
        help=f"Diagram background color passed to mmdc's -b flag (default: "
             f"{DEFAULT_MERMAID_BACKGROUND}). Any color mmdc accepts works, e.g. "
             "transparent, white, or a hex code like '#f0f0f0'.",
    )

    return parser


def main(argv: "list[str] | None" = None) -> None:
    parser = build_parser()

    # `docbus` with no args: print usage (not a stack trace) and exit non-zero.
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "convert":
        if not args.input.exists():
            sys.exit(f"Input file not found: {args.input}")
        output_path = args.output or args.input.with_suffix(".docx")
        try:
            convert(args.input, output_path, theme=args.theme, fmt=args.format, background=args.background)
        except ConversionError as e:
            sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
