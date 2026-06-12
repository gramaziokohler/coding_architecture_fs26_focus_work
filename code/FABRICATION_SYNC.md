# Fabrication status tracking via Google Sheets

Tracks the fabrication status of every beam in the pavilion in a Google
Sheet, kept in sync with the TimberModel JSON
(`timber_models/timber_model_w2-wednesday-03.json`) by
[`code/fabrication_sheet_sync.py`](fabrication_sheet_sync.py) and the
[`fabrication-sync`](../.github/workflows/fabrication-sync.yml) GitHub
Actions workflow.

## How it works

- **Rows are matched by `beam_id`** (a1…h24), the stable naming attribute
  stored on each beam — *not* by guid, because guids are regenerated on every
  Grasshopper re-export. Status survives design re-exports as long as beam
  ids are preserved.
- The **sheet owns the status columns**: `File ready`, `Milled`, `Assembled`,
  `Robot`, `Labeled` (checkboxes) and `Redo` (free text).
- The **model owns the design columns**: `Beam`, `Module`, `Category`,
  `Length (m)`, `Section (cm)`, `GUID`, `In model`.
- `pull` writes status into each beam as flat custom attributes:
  `fab_file_ready`, `fab_milled`, `fab_assembled`, `fab_robot`,
  `fab_labeled`, `fab_redo` — same convention as `module` / `beam_id`.
- `push` adds new beams to the sheet (status unchecked), refreshes design
  columns, and unchecks `In model` for beams that disappeared from the model
  (their status rows are kept, never deleted).
- `sync` = `pull` then `push`. The CI workflow runs it every 15 minutes, on
  every push that changes the model, and on demand; if statuses changed it
  commits the updated model JSON back to `main` (with `[skip ci]`, so it does
  not retrigger itself).

## One-time setup

1. **Create the spreadsheet**: make a new (empty) Google Sheet, note the id
   from its URL: `https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit`.

2. **Create a service account**:
   - In [Google Cloud Console](https://console.cloud.google.com/), create (or
     reuse) a project and enable the **Google Sheets API**.
   - Create a service account (IAM & Admin → Service Accounts), no special
     roles needed.
   - Create a **JSON key** for it and download the file.

3. **Share the sheet** with the service account's email
   (`...@<project>.iam.gserviceaccount.com`) as **Editor**.

4. **Add the repo secrets** (Settings → Secrets and variables → Actions):
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — the full content of the JSON key file
   - `FABRICATION_SPREADSHEET_ID` — the spreadsheet id from step 1

   Optionally, on the **Variables** tab, set `FABRICATION_MODEL_PATH` to the
   model JSON the sync should track (e.g.
   `timber_models/timber_model_w2-wednesday-03.json`). When unset, the
   script's built-in default is used. Locally the same env var works, or
   pass `--model`.

5. **Initialize the worksheet**: run the workflow manually from the Actions
   tab (`Fabrication sheet sync` → Run workflow → command: `setup`). This
   creates the `Fabrication` worksheet with headers, checkboxes and one row
   per beam, sorted by module.

## Local usage

```bash
pip install gspread
export GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account-key.json
export FABRICATION_SPREADSHEET_ID=<spreadsheet id>

python code/fabrication_sheet_sync.py setup   # first time only
python code/fabrication_sheet_sync.py sync    # pull statuses, push new beams
python code/fabrication_sheet_sync.py pull    # sheet -> model JSON only
python code/fabrication_sheet_sync.py push    # model -> sheet only
# different model file:
python code/fabrication_sheet_sync.py sync --model timber_models/other.json
```

## Rules of thumb for editing the sheet

- Edit only the status columns (`File ready` … `Redo`). Design columns are
  overwritten by the next `push`.
- Don't reorder or delete rows — not harmful (matching is by `Beam` id), but
  removed rows lose their status on the next pull… they simply won't exist.
- New beams appear automatically at the bottom after the next sync.
