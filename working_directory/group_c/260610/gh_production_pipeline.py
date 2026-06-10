# venv: ca-fs26-focus-work
# Grasshopper IronPython Component
# keyword: timber-pipeline, numbering, naming, packing, production-ready
# Orchestrates: run_numbering() -> run_module_naming() -> run_packing()

"""
PRODUCTION PIPELINE ORCHESTRATOR
Processes TimberModel through complete workflow:
  1. Spatial numbering + module assignment
  2. Text feature labeling with engraving attributes
  3. 2D production layout with traceability

INPUT:
  - timber_model: TimberModel object
  - Index: List of module indices (from spatial partitioning)
  - RunExport: Boolean to export statistics
  - OutputFolder: Path for exports
  - TextHeight: Height for engraving text (mm)
  - Origin: Point3d for layout start
  - SawGap: Distance between nested beams (mm)
  - LabelOffset: Z-offset for labels (mm)
  - PricePerMeter: Cost per linear meter (EUR)

OUTPUT:
  [STAGE 1: NUMBERING]
  - [0] debug_out: Beam type info
  - [1] info_out: Statistics (length, section, volume, weight)
  - [2] json_export_out: Export report
  - [3-8] A_geom_out through F_geom_out: Geometry by module
  - [9] timber_model_numbered: Model with partitioning attributes
  
  [STAGE 2: NAMING]
  - [10] named_labels: List of beam names (A1, B2, etc)
  - [11] ordered_beams: Beams with Text features
  - [12] engraving_refs: Engraving metadata (ref_side, start_x, start_y)
  - [13] naming_report: Text feature summary
  - [14] timber_model_named: Model with Text features + engraving attributes
  
  [STAGE 3: PACKING]
  - [15] arr_boxes: Flattened beam geometry in nested layout
  - [16] arr_names: Label text geometry (2D visualization)
  - [17] arr_lines: Reference positioning lines
  - [18] max_length: Maximum beam length
  - [19] dimensions: List of individual lengths
  - [20] num_txt: Dimension text labels
  - [21] stock_info: Metadata per beam (module, number, position)
  - [22] packing_report: Production report with costs
  - [23] timber_model_final: Final model (ready for CAM)
"""

import sys
import clr

# Ensure COMPAS path is set
try:
    from compas_ghpython.components import ParallelComponent
except ImportError:
    try:
        import DevTools
        DevTools.ensure_path()
    except:
        pass

import Rhino.Geometry as rg

# Import the pipeline modules (adjust paths as needed)
# These are relative to the Grasshopper file location
try:
    # Try loading from working_directory
    sys.path.insert(0, r"/Users/ra/Desktop/CODING II/04_FOCUS-WORK/00_FILE/coding_architecture_fs26_focus_work/working_directory/group_c/260608")
    from a03_number_beams import run_numbering
    from a03_module_naming import run_module_naming
    from a03_cut2 import run_packing
except ImportError as e:
    print("ERROR: Could not import pipeline modules")
    print(str(e))
    raise

def main(timber_model, index_list, run_export, output_folder, text_height, 
         origin, saw_gap, label_offset, price_per_meter):
    """
    Execute complete production pipeline.
    """
    
    if not timber_model:
        return None, "ERROR: No timber_model connected"
    
    try:
        # ==========================================
        # STAGE 1: NUMBERING WITH PARTITIONING
        # ==========================================
        numbering_results = run_numbering(
            timber_model,
            index_list,
            run_export,
            output_folder
        )
        
        debug_out = numbering_results[0]
        info_out = numbering_results[1]
        json_export_out = numbering_results[2]
        a_geom_out = numbering_results[3]
        b_geom_out = numbering_results[4]
        c_geom_out = numbering_results[5]
        d_geom_out = numbering_results[6]
        e_geom_out = numbering_results[7]
        f_geom_out = numbering_results[8]
        timber_model_numbered = numbering_results[9]
        
        # ==========================================
        # STAGE 2: MODULE NAMING WITH TEXT FEATURES
        # ==========================================
        naming_results = run_module_naming(
            timber_model_numbered,
            TextHeight=text_height
        )
        
        named_labels = naming_results[0]
        ordered_beams = naming_results[1]
        engraving_refs = naming_results[2]
        naming_report = naming_results[3]
        timber_model_named = naming_results[4]
        
        # ==========================================
        # STAGE 3: 2D PRODUCTION PACKING
        # ==========================================
        packing_results = run_packing(
            timber_model_named,
            origin,
            saw_gap,
            label_offset,
            price_per_meter
        )
        
        arr_boxes = packing_results[0]
        arr_names = packing_results[1]
        arr_lines = packing_results[2]
        max_length = packing_results[3]
        dimensions = packing_results[4]
        num_txt = packing_results[5]
        stock_info = packing_results[6]
        packing_report = packing_results[7]
        
        # ==========================================
        # RETURN ALL OUTPUTS
        # ==========================================
        return (
            # Stage 1
            debug_out, info_out, json_export_out,
            a_geom_out, b_geom_out, c_geom_out, d_geom_out, e_geom_out, f_geom_out,
            timber_model_numbered,
            # Stage 2
            named_labels, ordered_beams, engraving_refs, naming_report,
            timber_model_named,
            # Stage 3
            arr_boxes, arr_names, arr_lines, max_length,
            dimensions, num_txt, stock_info,
            packing_report, timber_model_named
        )
    
    except Exception as e:
        import traceback
        error_msg = "PIPELINE ERROR:\n" + traceback.format_exc()
        return None, error_msg


# ==========================================
# GRASSHOPPER COMPONENT INTERFACE
# ==========================================

# Unpack all inputs
timber_model = timber_model
index_list = Index if 'Index' in dir() else []
run_export = RunExport if 'RunExport' in dir() else False
output_folder = OutputFolder if 'OutputFolder' in dir() else ""
text_height = TextHeight if 'TextHeight' in dir() else 0.03
origin = Origin if 'Origin' in dir() else rg.Point3d(0, 0, 0)
saw_gap = SawGap if 'SawGap' in dir() else 0.01
label_offset = LabelOffset if 'LabelOffset' in dir() else 0.1
price_per_meter = PricePerMeter if 'PricePerMeter' in dir() else 10.0

# Execute pipeline
result = main(
    timber_model, index_list, run_export, output_folder, text_height,
    origin, saw_gap, label_offset, price_per_meter
)

if result[1] and "ERROR" in str(result[1]):
    print(result[1])

# Unpack and assign to outputs
out_1 = result[0]   # debug_out
out_2 = result[1]   # info_out
out_3 = result[2]   # json_export_out
out_4 = result[3]   # a_geom_out
out_5 = result[4]   # b_geom_out
out_6 = result[5]   # c_geom_out
out_7 = result[6]   # d_geom_out
out_8 = result[7]   # e_geom_out
out_9 = result[8]   # f_geom_out
out_10 = result[9]  # timber_model_numbered

out_11 = result[10] # named_labels
out_12 = result[11] # ordered_beams
out_13 = result[12] # engraving_refs
out_14 = result[13] # naming_report
out_15 = result[14] # timber_model_named

out_16 = result[15] # arr_boxes
out_17 = result[16] # arr_names
out_18 = result[17] # arr_lines
out_19 = result[18] # max_length
out_20 = result[19] # dimensions
out_21 = result[20] # num_txt
out_22 = result[21] # stock_info
out_23 = result[22] # packing_report
out_24 = result[23] # timber_model_final
