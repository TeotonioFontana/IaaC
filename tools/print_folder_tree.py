#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 print_tree.py — v1.1.0
===============================================================================
 Purpose............: Print a clean directory tree similar to `tree`, with the
                      option to skip specific folder names.
 Author.............: Duke (GPT-5, OpenAI)
-------------------------------------------------------------------------------
 Usage examples
 ------------------------------------------------------------------------------
    python print_tree.py --root ./iaactools
    python print_tree.py --root ./project --exclude .venv __pycache__ .git
    python print_tree.py --root ./src --max-depth 3 --exclude node_modules dist
===============================================================================
"""

import argparse
from pathlib import Path

def build_tree(path: Path, prefix: str = "", depth: int = 0,
               max_depth: int = None, exclude: list[str] = None) -> list[str]:
    """Recursively collect formatted lines representing a directory tree."""
    exclude = exclude or []
    if max_depth is not None and depth > max_depth:
        return []

    entries = [
        e for e in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        if e.name not in exclude
    ]

    lines = []
    for idx, entry in enumerate(entries):
        connector = "└── " if idx == len(entries) - 1 else "├── "
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir():
            extension = "    " if idx == len(entries) - 1 else "│   "
            lines.extend(build_tree(entry, prefix + extension, depth + 1, max_depth, exclude))
    return lines

def main():
    parser = argparse.ArgumentParser(description="Print a directory tree with optional exclusions.")
    parser.add_argument("--root", required=True, help="Root folder to scan.")
    parser.add_argument("--max-depth", type=int, default=None, help="Maximum recursion depth.")
    parser.add_argument("--exclude", nargs="*", default=[],
                        help="List of folder/file names to exclude (space-separated).")
    parser.add_argument("--output", help="Optional path to save tree output to a text file.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Invalid root path: {root}")
        return

    lines = [root.name + "/"] + build_tree(root, max_depth=args.max_depth, exclude=args.exclude)
    tree_output = "\n".join(lines)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(tree_output, encoding="utf-8")
        print(f"[OK] Tree written to {args.output}")
    else:
        print(tree_output)

if __name__ == "__main__":
    main()
