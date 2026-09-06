"""Command-line entry point for docbus.

Subcommands from day one (`docbus convert ...`) so future verbs like
`push`/`pull` can be added without a breaking CLI shape change.
"""

import argparse
import sys
from pathlib import Path

from . import __version__
from .convert import ConversionError, convert


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docbus",
        description="Convert Markdown (with embedded Mermaid diagrams) to .docx.",
    )
    parser.add_argument("--version", action="version", version=f"docbus {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    convert_parser = subparsers.add_parser(
        "convert", help="Convert a single .md file to .docx"
    )
    convert_parser.add_argument("input", type=Path, help="Path to the source .md file")
    convert_parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output .docx path (default: same name as input)",
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
            convert(args.input, output_path)
        except ConversionError as e:
            sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
