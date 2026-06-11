# venv: ca-fs26-focus-work
# Grasshopper IronPython Component - Packing Stage Only
# keyword: timber-packing, production-layout, 2d-nesting

"""
PACKING STAGE COMPONENT (Standalone)

Use this after run_numbering() and run_module_naming() are complete.
Converts 3D beams to 2D production layout with traceability.

INPUT:
  - timber_model: TimberModel with beams containing:
    * module, number, display_name, beam_id (from run_numbering)
    * engraving_ref_side, engraving_start_x, engraving_start_y (from run_module_naming)
  - Origin: Point3d for layout start position
  - SawGap: Distance between nested beams (m)
  - LabelOffset: Z-offset for label text (m)
  - PricePerMeter: Cost per linear meter (EUR)

OUTPUT:
  - [0] arr_boxes: Flattened beam geometry in nested layout
  - [1] arr_names: Label text geometry (2D visualization)
  - [2] arr_lines: Reference positioning lines
  - [3] max_length: Maximum beam length
  - [4] dimensions: List of individual beam lengths
  - [5] num_txt: Dimension text labels
  - [6] stock_info: Metadata per beam (JSON-like list of dicts)
  - [7] packing_report: Production report with module breakdown
"""

import sys
import Rhino.Geometry as rg

# Ensure COMPAS path
try:
    from compas_ghpython.components import ParallelComponent
except ImportError:
    try:
        import DevTools
        DevTools.ensure_path()
    except:
        pass

# Import packing function
try:
    sys.path.insert(0, r"/Users/ra/Desktop/CODING II/04_FOCUS-WORK/00_FILE/coding_architecture_fs26_focus_work/working_directory/group_c/260608")
    from a03_cut2 import run_packing
except ImportError as e:
    print("ERROR: Could not import run_packing from a03_cut2")
    print(str(e))
    raise

def main(timber_model, origin, saw_gap, label_offset, price_per_meter):
    """Execute packing only."""
    
    if not timber_model:
        return None, "ERROR: No timber_model connected"
    
    if not timber_model.beams:
        return None, "ERROR: timber_model has no beams"
    
    # Check that beams have required attributes
    beam_checks = []
    for beam in timber_model.beams:
        attrs = getattr(beam, "attributes", {})
        has_display_name = "display_name" in attrs
        has_module = "module" in attrs
        beam_checks.append({
            "beam_key": beam.key,
            "has_display_name": has_display_name,
            "has_module": has_module
        })
    
    missing_attrs = [b for b in beam_checks if not (b["has_display_name"] and b["has_module"])]
    if missing_attrs:
        print("WARNING: Some beams missing attributes from run_numbering/run_module_naming")
        for b in missing_attrs[:3]:  # Show first 3
            print(f"  Beam {b['beam_key']}: display_name={b['has_display_name']}, module={b['has_module']}")
    
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

result, status = main(timber_model, origin, saw_gap, label_offset, price_per_meter)

if "ERROR" in status or result is None:
    print(status)
else:
    # Unpack packing results
    arr_boxes = result[0]
    arr_names = result[1]
    arr_lines = result[2]
    max_length = result[3]
    dimensions = result[4]
    num_txt = result[5]
    stock_info = result[6]
    packing_report = result[7]
