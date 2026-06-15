#!/usr/bin/env python3
"""Sync fabrication status between a TimberModel JSON and a Google Sheet.

The sheet is the source of truth for the fabrication status columns
(File ready, Milled, Assembled, Robot, Labeled, Redo); the model JSON is the
source of truth for the design columns (beam id, module, category, dimensions).
Rows are matched by ``beam_id`` (the stable a1..h24 naming stored as a custom
attribute on each beam), NOT by guid: guids are regenerated on every
Grasshopper re-export, beam ids survive.

Status values are written back into each beam's data as flat custom
attributes (``fab_file_ready``, ``fab_milled``, ..., ``fab_redo``), the same
convention used by the other custom attributes (``module``, ``beam_id``, ...).

Commands:
    setup   create/format the worksheet (headers, checkboxes) and fill rows
    push    model -> sheet: add new beams, refresh design columns
    pull    sheet -> model: write status attributes into the model JSON
    sync    pull, then push

Auth: a Google service account with the Sheets API enabled. Provide the key
via the ``GOOGLE_SERVICE_ACCOUNT_JSON`` env var (the JSON content itself) or
``GOOGLE_APPLICATION_CREDENTIALS`` (path to the key file). The spreadsheet
must be shared with the service account email as Editor. See
``code/FABRICATION_SYNC.md`` for the full setup walkthrough.
"""

import argparse
import json
import os
import re
import sys

DEFAULT_MODEL = "timber_models/timber_model_w2-wednesday-03.json"
WORKSHEET_NAME = "Fabrication"
ATTR_PREFIX = "fab_"

# (attribute suffix, sheet header, kind)
STATUS_FIELDS = [
    ("file_ready", "File ready", "checkbox"),
    ("milled", "Milled", "checkbox"),
    ("assembled", "Assembled", "checkbox"),
    ("robot", "Robot", "checkbox"),
    ("labeled", "Labeled", "checkbox"),
    ("redo", "Redo", "text"),
]

DESIGN_HEADERS = ["Beam", "Module", "Category", "Length (mm)", "Cross section (mm)"]
TAIL_HEADERS = ["In model", "GUID"]
HEADERS = DESIGN_HEADERS + [label for _, label, _ in STATUS_FIELDS] + TAIL_HEADERS

N_DESIGN = len(DESIGN_HEADERS)  # status columns start right after these
COL_IN_MODEL = len(HEADERS) - 2  # 0-based index of "In model"
COL_GUID = len(HEADERS) - 1  # 0-based index of "GUID" (last column)
VALIDATION_ROWS = 2000  # checkbox validation pre-applied to this many rows


# ---------------------------------------------------------------- model side


def load_model(path):
    with open(path) as fp:
        return json.load(fp)


def save_model(path, model):
    with open(path, "w") as fp:
        json.dump(model, fp, sort_keys=True, indent=2)


def iter_beams(model):
    for guid, element in model["data"].get("elements", {}).items():
        if element.get("dtype", "").endswith("/Beam"):
            yield guid, element["data"]


def beam_key(guid, data):
    return str(data.get("beam_id") or guid).upper()


def natural_sort_key(item):
    guid, data = item
    module = str(data.get("module") or "ZZ")
    try:
        number = int(data.get("number") or data.get("beam_number"))
    except (TypeError, ValueError):
        number = 10**6
    return (module, number, beam_key(guid, data))


def design_values(guid, data):
    width = float(data.get("width") or 0)
    height = float(data.get("height") or 0)
    return [
        beam_key(guid, data),
        str(data.get("module") or ""),
        str(data.get("category") or ""),
        round(float(data.get("length") or 0) * 1000, 3),
        "{:g} x {:g}".format(width * 1000, height * 1000),
    ]


# ---------------------------------------------------------------- sheet side


def get_worksheet(args, create=False):
    import gspread

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        gc = gspread.service_account_from_dict(json.loads(raw))
    elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        gc = gspread.service_account(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    else:
        sys.exit(
            "No credentials: set GOOGLE_SERVICE_ACCOUNT_JSON (key content) "
            "or GOOGLE_APPLICATION_CREDENTIALS (key file path)."
        )

    spreadsheet_id = args.spreadsheet_id or os.environ.get("FABRICATION_SPREADSHEET_ID")
    if not spreadsheet_id:
        sys.exit(
            "No spreadsheet: set FABRICATION_SPREADSHEET_ID or pass --spreadsheet-id."
        )

    sh = gc.open_by_key(spreadsheet_id)
    try:
        return sh, sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        if not create:
            sys.exit(
                "Worksheet '{}' not found. Run the 'setup' command first.".format(
                    WORKSHEET_NAME
                )
            )
        return sh, sh.add_worksheet(
            WORKSHEET_NAME, rows=VALIDATION_ROWS, cols=len(HEADERS)
        )


def cell_to_bool(value):
    return str(value).strip().upper() == "TRUE"


def norm(value):
    """Normalize a cell/python value for change detection (sheet returns strings)."""
    s = str(value).strip()
    if s.upper() in ("TRUE", "FALSE"):
        return s.upper()
    try:
        return "{:g}".format(float(s))
    except ValueError:
        return s


def column_letter(index):
    """1-based column index -> A1 letter(s)."""
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def read_rows(ws):
    """Return (header, list of (row_number, padded_row_values))."""
    values = ws.get_all_values()
    if not values:
        return [], []
    rows = []
    for i, row in enumerate(values[1:], start=2):
        row = row + [""] * (len(HEADERS) - len(row))
        if row[0].strip():
            rows.append((i, row))
    return values[0], rows


# ------------------------------------------------------------------ commands


def cmd_setup(args):
    sh, ws = get_worksheet(args, create=True)

    # Start from a clean, correctly-sized grid: drop any previous content
    # (including off-to-the-right junk rows/columns from earlier runs) so the
    # checkbox validation and the first push land in the right place.
    ws.clear()
    ws.resize(rows=VALIDATION_ROWS, cols=len(HEADERS))

    ws.update(values=[HEADERS], range_name="A1", value_input_option="RAW")

    checkbox_cols = [
        N_DESIGN + i
        for i, (_, _, kind) in enumerate(STATUS_FIELDS)
        if kind == "checkbox"
    ]
    checkbox_cols.append(
        COL_IN_MODEL
    )  # "In model" is a checkbox too (read-only by convention)
    requests = [
        {
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": ws.id,
                    "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1},
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
            }
        },
    ]
    for col in checkbox_cols:
        requests.append(
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 1,
                        "endRowIndex": VALIDATION_ROWS,
                        "startColumnIndex": col,
                        "endColumnIndex": col + 1,
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "strict": True},
                }
            }
        )
    sh.batch_update({"requests": requests})
    print("Worksheet '{}' formatted.".format(WORKSHEET_NAME))
    cmd_push(args)


def cmd_push(args):
    """Model -> sheet: append new beams, refresh design columns, flag removed."""
    model = load_model(args.model)
    _, ws = get_worksheet(args)
    _, rows = read_rows(ws)
    row_by_key = {row[0].strip().upper(): (n, row) for n, row in rows}

    beams = sorted(iter_beams(model), key=natural_sort_key)
    model_keys = set()
    updates = []
    appends = []

    for guid, data in beams:
        key = beam_key(guid, data)
        model_keys.add(key)
        design = design_values(guid, data)
        if key in row_by_key:
            n, row = row_by_key[key]
            current = row[:N_DESIGN] + [row[COL_IN_MODEL], row[COL_GUID]]
            wanted = design + [True, guid]
            if [norm(v) for v in current] != [norm(v) for v in wanted]:
                updates.append({"range": "A{0}:E{0}".format(n), "values": [design]})
                updates.append(
                    {
                        "range": "{1}{0}:{2}{0}".format(
                            n,
                            column_letter(COL_IN_MODEL + 1),
                            column_letter(len(HEADERS)),
                        ),
                        "values": [[True, guid]],
                    }
                )
        else:
            status_defaults = [
                False if kind == "checkbox" else "" for _, _, kind in STATUS_FIELDS
            ]
            appends.append(design + status_defaults + [True, guid])

    # beams that disappeared from the model keep their row but get unchecked "In model"
    for key, (n, row) in row_by_key.items():
        if key not in model_keys and cell_to_bool(row[COL_IN_MODEL]):
            updates.append(
                {
                    "range": "{1}{0}".format(n, column_letter(COL_IN_MODEL + 1)),
                    "values": [[False]],
                }
            )

    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    if appends:
        # Write to an explicit range anchored at column A instead of
        # ws.append_rows(): the Sheets "append" table-detection can guess the
        # wrong start column and drop the new rows far to the right.
        start_row = len(ws.get_all_values()) + 1
        end_row = start_row + len(appends) - 1
        if ws.row_count < end_row:  # ws.update() does not auto-grow the grid
            ws.add_rows(end_row - ws.row_count)
        last_col = column_letter(len(HEADERS))
        ws.update(
            values=appends,
            range_name="A{0}:{1}{2}".format(start_row, last_col, end_row),
            value_input_option="RAW",
        )
    print(
        "push: {} rows updated, {} beams added, {} total in model.".format(
            len(updates), len(appends), len(beams)
        )
    )


def cmd_pull(args):
    """Sheet -> model: write fab_* attributes into the model JSON."""
    model = load_model(args.model)
    beams_by_key = {beam_key(guid, data): data for guid, data in iter_beams(model)}

    _, ws = get_worksheet(args)
    _, rows = read_rows(ws)

    changed = 0
    unknown = []
    for _, row in rows:
        key = row[0].strip()
        data = beams_by_key.get(key)
        if data is None:
            unknown.append(key)
            continue
        for i, (suffix, _, kind) in enumerate(STATUS_FIELDS):
            cell = row[N_DESIGN + i]
            value = cell_to_bool(cell) if kind == "checkbox" else str(cell).strip()
            attr = ATTR_PREFIX + suffix
            if data.get(attr) != value:
                data[attr] = value
                changed += 1

    if changed:
        save_model(args.model, model)
    print("pull: {} attribute(s) updated in {}.".format(changed, args.model))
    if unknown:
        print(
            "pull: {} sheet row(s) not in model (ok if removed): {}".format(
                len(unknown), ", ".join(unknown[:10])
            )
        )


def cmd_sync(args):
    cmd_pull(args)
    cmd_push(args)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["setup", "push", "pull", "sync"])
    parser.add_argument(
        "--model",
        default=os.environ.get("FABRICATION_MODEL_PATH") or DEFAULT_MODEL,
        help="path to the TimberModel JSON (default: $FABRICATION_MODEL_PATH or %(default)s)",
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=None,
        help="Google Sheet id (default: $FABRICATION_SPREADSHEET_ID)",
    )
    args = parser.parse_args()

    if args.command in ("pull", "sync", "push") and not os.path.exists(args.model):
        sys.exit("Model file not found: {}".format(args.model))

    {"setup": cmd_setup, "push": cmd_push, "pull": cmd_pull, "sync": cmd_sync}[
        args.command
    ](args)


if __name__ == "__main__":
    main()
