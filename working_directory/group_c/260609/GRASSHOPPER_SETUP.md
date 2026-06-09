# Production Pipeline - Grasshopper Integration Guide

## Overview

The production pipeline consists of three stages, each with a separate Python component:

```
Stage 1: NUMBERING          Stage 2: NAMING              Stage 3: PACKING
━━━━━━━━━━━━━━━━━           ━━━━━━━━━━━━━━━━━            ━━━━━━━━━━━━━━━
timber_model               timber_model_numbered        timber_model_named
    ↓                            ↓                            ↓
run_numbering()            run_module_naming()          run_packing()
    ↓                            ↓                            ↓
Adds attributes:           Adds attributes:             Outputs 2D layout:
• module (A-F)             • engraving_ref_side         • arr_boxes
• number (1,2,...)         • engraving_start_x/y        • arr_names
• display_name (A1)        • text_height                • stock_info
• beam_id (a1)             
                           Adds Text features ✓
```

---

## Component 1: Complete Pipeline (gh_production_pipeline.py)

**Use when**: You want to run all three stages in one component.

### Setup in Grasshopper

1. Create a new **Python** component in Grasshopper
2. Copy entire content of `gh_production_pipeline.py` into the script editor
3. Add inputs (right-click component → Input → New):

| Input Name | Type | Description |
|-----------|------|-------------|
| timber_model | Item | TimberModel object |
| Index | List | Module indices (from spatial partitioning) |
| RunExport | Boolean | Export statistics to file |
| OutputFolder | String | Path for exports |
| TextHeight | Number | Text height (mm) - default 0.03 |
| Origin | Point | Layout start point (default 0,0,0) |
| SawGap | Number | Gap between beams (m) - default 0.01 |
| LabelOffset | Number | Z-offset for labels (m) - default 0.1 |
| PricePerMeter | Number | Cost per meter (EUR) - default 10.0 |

4. Add outputs (right-click component → Output → New):

```
Stage 1 (Numbering):
out_1: debug_out
out_2: info_out
out_3: json_export_out
out_4: a_geom_out
out_5: b_geom_out
out_6: c_geom_out
out_7: d_geom_out
out_8: e_geom_out
out_9: f_geom_out
out_10: timber_model_numbered

Stage 2 (Naming):
out_11: named_labels
out_12: ordered_beams
out_13: engraving_refs
out_14: naming_report
out_15: timber_model_named

Stage 3 (Packing):
out_16: arr_boxes (geometry)
out_17: arr_names (geometry)
out_18: arr_lines (geometry)
out_19: max_length (number)
out_20: dimensions (list)
out_21: num_txt (list)
out_22: stock_info (list)
out_23: packing_report (string)
out_24: timber_model_final
```

### Example Connection

```
[Load TimberModel] 
       ↓
[Python: gh_production_pipeline.py]
       ↓ out_10 (timber_model_numbered)
     ↓ out_15 (timber_model_named)
     ↓ out_16 (arr_boxes) → [Mesh/BRep Display]
     ↓ out_17 (arr_names) → [Text Display]
     ↓ out_22 (stock_info) → [JSON Export]
     ↓ out_23 (packing_report) → [Text Panel]
```

---

## Component 2: Packing Stage Only (gh_packing_only.py)

**Use when**: You already have `timber_model_named` (from numbering + naming steps).

### Setup in Grasshopper

1. Create a new **Python** component
2. Copy content of `gh_packing_only.py`
3. Add inputs:

| Input Name | Type | Default |
|-----------|------|---------|
| timber_model | Item | (required) |
| Origin | Point | 0,0,0 |
| SawGap | Number | 0.01 |
| LabelOffset | Number | 0.1 |
| PricePerMeter | Number | 10.0 |

4. Add outputs:

```
arr_boxes (geometry)
arr_names (geometry)
arr_lines (geometry)
max_length (number)
dimensions (list)
num_txt (list)
stock_info (list)
packing_report (string)
```

---

## Required Python Environment

**venv**: `ca-fs26-focus-work`

Dependencies:
- COMPAS Timber (for `compas_timber.fabrication.Text`)
- Rhino.Geometry (IronPython)
- Standard library: sys, math, traceback

The component uses `DevTools.ensure_path()` to automatically set COMPAS paths.

---

## Data Flow: Attributes Through Pipeline

### After run_numbering()
```python
beam.attributes = {
    "module": "A",           # Letter A-F
    "number": 1,             # Sequential
    "display_name": "A1",    # Human-readable
    "beam_id": "a1"          # Lowercase ID
}
```

### After run_module_naming()
```python
beam.attributes = {
    # ... previous attributes ...
    "engraving_ref_side": 2,          # Face index (0-5)
    "engraving_start_x": 0.15,        # Position on face (m)
    "engraving_start_y": 0.20,        # Position on face (m)
    "text_height": 0.05               # Engraving height (m)
}

beam.features = [
    Text(ref_side_index=2, start_x=0.15, start_y=0.20, text="A1", ...)
]
```

### After run_packing()
```python
# Returns stock_info: list of dicts per beam
stock_info = [
    {
        "beam_id": "a1",
        "display_name": "A1",
        "module": "A",
        "number": 1,
        "nested_position_x": 2.35,     # Position in 2D layout (m)
        "nested_length": 3.15,         # Length in layout (m)
        "has_text_feature": True
    },
    # ... more beams ...
]
```

---

## Troubleshooting

### "ERROR: Could not import pipeline modules"
**Cause**: Path to scripts not found
**Fix**: Edit the `sys.path.insert()` line to match your working directory:
```python
sys.path.insert(0, r"YOUR_PATH_HERE/working_directory/group_c/260608")
```

### "ERROR: No beams in timber_model"
**Cause**: Empty or invalid model
**Fix**: Check that timber_model is properly loaded from upstream component

### "WARNING: Some beams missing attributes"
**Cause**: Beams weren't processed by run_numbering() first
**Fix**: Connect output from Stage 1 (out_10) to Stage 2 input

### Text features not visible in Rhino
**Cause**: Text features exist on model but not rendered in viewport
**Fix**: This is expected—Text features are metadata for CAM software, not viewable geometry. Use `arr_names` output for visualization.

---

## Production Workflow

### Setup
1. Load timber model from JSON/Rhino
2. Run numbering (assigns module + number attributes)
3. Run module naming (adds Text features + engraving attributes)
4. Run packing (creates 2D layout)

### Output
- **arr_boxes**: Send to CNC nesting
- **arr_names**: Print for verification
- **stock_info**: Export to CAM software (CSV/JSON)
- **timber_model_final**: Save for downstream fabrication (Drilling, Joinery, etc.)

### Export
```python
import json

# Save stock metadata for CAM
with open("stock_layout.json", "w") as f:
    json.dump(stock_info, f, indent=2)

# Save packing report
with open("production_report.txt", "w") as f:
    f.write(packing_report)
```

---

## Example Grasshopper Canvas

```
┌─────────────────┐
│ Load TimberModel│
└────────┬────────┘
         │
         v
┌─────────────────────────────────────────┐
│ Python: gh_production_pipeline.py       │
│                                         │
│ INPUT:                                  │
│ [timber_model] ─────────────────┐       │
│ [Index] ─────────────────┐       │       │
│ [RunExport] ─────────────┼───────┤       │
│ [OutputFolder] ──────────┼───────┤       │
│ [TextHeight] ─────────────┼───────┤       │
│ [Origin] ────────────────┼───────┤       │
│ [SawGap] ─────────────────┼───────┤       │
│ [LabelOffset] ────────────┼───────┤       │
│ [PricePerMeter] ──────────┼───────┤       │
│                           │       │       │
└─────────────────────────────────────────┘
  │      │      │      │      │      │  
  │      │      │      │      │      ├──> [out_16] arr_boxes
  │      │      │      │      │      ├──> [out_17] arr_names (Display)
  │      │      │      │      │      ├──> [out_22] stock_info (JSON Export)
  │      │      │      │      │      └──> [out_23] packing_report (Panel)
  │      │      │      │      │
  └──────┴──────┴──────┴──────┘
         │
         v
   [Continue to CAM]
```

---

## Next Steps

1. **Verify pipeline**: Run complete workflow and check all attributes are stored
2. **Test packing**: Visualize `arr_boxes` + `arr_names` in Rhino
3. **Export**: Save `stock_info` to JSON for CAM software
4. **Fabrication**: Use `timber_model_final` (with Text features) for downstream Drilling/Joinery components
