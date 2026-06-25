#!/usr/bin/env python3
"""Split a BTLx file into one file per module, preserving the original formatting.

A Part's module is the first character of its ``Annotation`` attribute
(e.g. ``Annotation="A30"`` -> module ``A``). The split is done at the text level
(no XML re-serialization), so the header, footer and every kept ``<Part>`` block
are byte-for-byte identical to the input -- the only difference between an output
file and the original is that the other modules' parts are removed.

Usage:
    python split_btlx_by_module.py INPUT.btlx [OUTPUT_DIR] [--renumber]
"""
import argparse
import os
import re

# A part block: leading whitespace + the whole <Part ...> ... </Part> (no nesting).
PART_RE = re.compile(r"\s*<Part\b.*?</Part>", re.DOTALL)
ANN_RE = re.compile(r'<Part\b[^>]*?\bAnnotation="([^"]*)"')


def _renumber(block, n):
    block = re.sub(r'(\bSingleMemberNumber=")[^"]*(")', r"\g<1>%d\g<2>" % n, block, 1)
    block = re.sub(r'(\bOrderNumber=")[^"]*(")', r"\g<1>%d\g<2>" % n, block, 1)
    return block


def split_btlx(input_path, output_dir=None, renumber=False):
    # newline="" keeps the original line endings; no re-encoding of content.
    with open(input_path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()

    m_open = re.search(r"<Parts\b[^>]*>", text)
    i_close = text.find("</Parts>")
    if m_open is None or i_close == -1:
        raise SystemExit("Could not find <Parts> ... </Parts> - is this a BTLx file?")

    header = text[: m_open.end()]       # up to and including <Parts>
    inner = text[m_open.end(): i_close]  # the parts + whitespace
    footer = text[i_close:]             # </Parts> ... </BTLx>

    matches = list(PART_RE.finditer(inner))
    if not matches:
        raise SystemExit("No <Part> elements found.")
    trailing = inner[matches[-1].end():]  # whitespace before </Parts>

    order = []           # module discovery order
    by_module = {}       # module -> [verbatim part block, ...]
    missing = 0
    for mm in matches:
        block = mm.group(0)
        am = ANN_RE.search(block)
        ann = am.group(1).strip() if am else ""
        module = ann[0].upper() if ann else "_NONE"
        if not ann:
            missing += 1
        if module not in by_module:
            by_module[module] = []
            order.append(module)
        by_module[module].append(block)

    stem = os.path.splitext(os.path.basename(input_path))[0]
    if output_dir is None:
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(input_path)), stem + "_modules"
        )
    os.makedirs(output_dir, exist_ok=True)

    written = []
    for module in order:
        blocks = by_module[module]
        if renumber:
            blocks = [_renumber(b, i) for i, b in enumerate(blocks)]
        out_text = header + "".join(blocks) + trailing + footer
        out_path = os.path.join(output_dir, "%s_%s.btlx" % (stem, module))
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(out_text)
        written.append((module, len(blocks), out_path))

    return written, missing


def main():
    ap = argparse.ArgumentParser(
        description="Split a BTLx file per module (by Annotation first letter)."
    )
    ap.add_argument("input", help="path to the input BTLx file")
    ap.add_argument(
        "output_dir", nargs="?", default=None,
        help="output directory (default: <input>_modules/ next to the input)",
    )
    ap.add_argument(
        "--renumber", action="store_true",
        help="renumber SingleMemberNumber/OrderNumber 0..n within each module",
    )
    args = ap.parse_args()

    written, missing = split_btlx(args.input, args.output_dir, args.renumber)
    total = sum(c for _, c, _ in written)
    print("Split %d parts into %d module file(s):" % (total, len(written)))
    for module, count, path in sorted(written):
        print("  module %-6s : %3d parts  ->  %s" % (module, count, path))
    if missing:
        print("WARNING: %d part(s) had no Annotation (grouped under _NONE)." % missing)


if __name__ == "__main__":
    main()
