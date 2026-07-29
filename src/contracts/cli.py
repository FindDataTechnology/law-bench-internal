"""Command-line tool: extract 法律法规 and generate contract DOCX/PDF.

Usage::

    python -m src.contracts <contract_type> [--format pdf|docx|both] [--out DIR]
    python -m src.contracts --all [--format pdf|docx|both] [--out DIR]
"""

from __future__ import annotations

import argparse
import sys

from .generator import generate_contract
from .templates import list_contract_types


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.contracts",
        description="Extract 法律法规 and generate contract DOCX/PDF per contract class.",
    )
    parser.add_argument("contract_type", nargs="?", help="contract class key (e.g. sale)")
    parser.add_argument(
        "--format", choices=("docx", "pdf", "both"), default="pdf",
        help="output format (default: pdf)",
    )
    parser.add_argument("--all", action="store_true", help="generate for every contract class")
    parser.add_argument("--out", default=None, help="output directory (default: output/contracts)")
    return parser


def _print_paths(result: dict) -> None:
    for p in (result["docx_path"], result["pdf_path"]):
        if p:
            print(p)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.all:
        types = list_contract_types()
        if not types:
            print("no contract types found", file=sys.stderr)
            return 1
        failed = 0
        for ct in types:
            try:
                result = generate_contract(ct["key"], format=args.format, out_dir=args.out)
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"error generating {ct['key']}: {exc}", file=sys.stderr)
                failed += 1
                continue
            _print_paths(result)
        return 1 if failed else 0

    if not args.contract_type:
        parser.error("contract_type is required (or use --all)")
        return 2  # parser.error exits; unreachable

    try:
        result = generate_contract(args.contract_type, format=args.format, out_dir=args.out)
    except Exception as exc:  # noqa: BLE001 - surface any error (e.g. unknown type)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_paths(result)
    return 0
