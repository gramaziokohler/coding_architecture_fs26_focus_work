# venv: ca-fs26-focus-work
# Grasshopper IronPython Component
# keyword: timber-packing, step-3-only, production-layout

"""
PACKING COMPONENT (Step 3 Only)

Takes timber_model with:
- Attributes from run_numbering() (module, number, display_name, beam_id)
- Text features from run_module_naming() (on each beam)
- Engraving attributes (engraving_ref_side, start_x, start_y)

Outputs:
- 2D production layout
- Traceability metadata
- Production report

INPUT:
  - timber_model: TimberModel (pre-processed by numbering + naming)
  - Origin: Point3d for layout start
  - SawGap: Distance between nested beams (m)
  - LabelOffset: Z-offset for labels (m)
  - PricePerMeter: Cost per linear meter (EUR)

OUTPUT:
  - [0] arr_boxes: Flattened beam geometry (nested layout)
  - [1] arr_names: Label text geometry (2D visualization)
  - [2] arr_lines: Reference lines for positioning
  - [3] max_length: Maximum beam length
  - [4] dimensions: List of all beam lengths
  - [5] num_txt: Dimension text labels
  - [6] stock_info: Metadata per beam (module, number, position, has_text_feature)
  - [7] packing_report: Production summary with costs
"""

import sys
import Rhino.Geometry as rg

try:
    sys.path.insert(0, r"/Users/ra/Desktop/CODING II/04_FOCUS-WORK/00_FILE/coding_architecture_fs26_focus_work/working_directory/group_c/260608")
    from a03_cut2 import run_packing
except ImportError as e:
    print("ERROR: Could not import run_packing")
    print(str(e))
    raise

def execute_packing(timber_model, origin, saw_gap, label_offset, price_per_meter):
    """Execute packing stage."""
    
    if not timber_model:
        return None, "ERROR: No timber_model connected"
    
    if not hasattr(timber_model, 'beams') or not timber_model.beams:
        return None, "ERROR: timber_model has no beams"
    
    # Check that beams have required attributes
    missing_attrs = []
    for beam in timber_model.beams:
        attrs = getattr(beam, "attributes", {})
        if "display_name" not in attrs or "module" not in attrs:
            missing_attrs.append(beam.key)
    
    if missing_attrs:
        print(f"WARNING: {len(missing_attrs)} beams missing attributes from numbering/naming")
        print(f"  Example: {missing_attrs[0]}")
    
    try:
        results = run_packing(
            timber_model,
            origin,
            saw_gap,
            label_offset,
            price_per_meter
        )
        return results, "SUCCESS"
    
    except Exception as e:
        import traceback
        error_msg = "PACKING ERROR:\n" + traceback.format_exc()
        return None, error_msg


# ==========================================
# GRASSHOPPER COMPONENT INTERFACE
# ==========================================

timber_model = timber_model
origin = Origin if 'Origin' in dir() else rg.Point3d(0, 0, 0)
saw_gap = SawGap if 'SawGap' in dir() else 0.01
label_offset = LabelOffset if 'LabelOffset' in dir() else 0.1
price_per_meter = PricePerMeter if 'PricePerMeter' in dir() else 10.0

result, status = execute_packing(timber_model, origin, saw_gap, label_offset, price_per_meter)

if "ERROR" in status:
    print(status)
else:
    arr_boxes = result[0]
    arr_names = result[1]
    arr_lines = result[2]
    max_length = result[3]
    dimensions = result[4]
    num_txt = result[5]
    stock_info = result[6]
    packing_report = result[7]
