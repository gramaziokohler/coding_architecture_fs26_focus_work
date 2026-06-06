# venv: ca-fs26-focus-work

from compas_rhino.devtools import DevTools

DevTools.ensure_path()
ghenv.Component.Message = "Drilling & Procurement"

# -------------------- IMPORTS ---------------------
import Rhino.Geometry as rg
import traceback
import sys

# Point Rhino to the folder containing versuch_rf_drilling.py
_module_dir = r"/Users/leona/Desktop/Coding_Architecture_FS26_Vertiefungsarbeit/coding_architecture_fs26_focus_work/code"
if _module_dir not in sys.path:
    sys.path.insert(0, _module_dir)


# ------------------- EXECUTION --------------------

# Default outputs
drilled_model = timber_model
beams = []
screws = []
geometry_errors = []
failed_screws = []
failed_labels = []

# Default summary state
summary = "Waiting to run..."

if process_drillings and timber_model:
    try:
        # Import inside the execution block to ensure we grab the freshest save
        from versuch_rf_drilling import DrillingProcessor

        dia = screw_diameter if screw_diameter else 0.008
        length = screw_length if screw_length else 0.150

        # Initialize the processor
        processor = DrillingProcessor(
            timber_model, screw_diameter=dia, screw_length=length
        )

        drilled_model = processor.process_drillings()

        # 1. GRAB THE SUMMARY TEXT
        summary = processor.summary_text

        # 2. GENERATE 3D SOLID CYLINDERS FOR PHYSICAL SCREWS
        radius = dia / 2.0
        for compas_line in processor.screw_lines:
            # Convert COMPAS geometry to Rhino geometry
            start_pt = rg.Point3d(
                compas_line.start.x, compas_line.start.y, compas_line.start.z
            )
            end_pt = rg.Point3d(compas_line.end.x, compas_line.end.y, compas_line.end.z)
            direction = end_pt - start_pt

            # Prevent zero-length errors
            if direction.Length > 0.001:
                # Create a plane facing the direction of the screw
                base_plane = rg.Plane(start_pt, direction)
                base_circle = rg.Circle(base_plane, radius)

                # Extrude the circle into a cylinder matching the screw length
                rhino_cylinder = rg.Cylinder(base_circle, direction.Length)

                # ToBrep(True, True) caps the ends to make it a solid pipe
                screws.append(rhino_cylinder.ToBrep(True, True))

        # 3. OUTPUT FAILED SCREW TRAJECTORIES AND LABELS
        for info in processor.failed_screw_info:
            compas_line = info["line"]
            j_type = info["type"]

            start_pt = rg.Point3d(
                compas_line.start.x, compas_line.start.y, compas_line.start.z
            )
            end_pt = rg.Point3d(compas_line.end.x, compas_line.end.y, compas_line.end.z)
            failed_screws.append(rg.Line(start_pt, end_pt))

            mid_pt = (start_pt + end_pt) / 2.0
            failed_labels.append(rg.TextDot(j_type, mid_pt))

        ghenv.Component.Message = f"Generated {processor.drilling_count} drillings"

    except Exception as e:
        summary = "ERROR DURING EXECUTION:\n" + traceback.format_exc()
        ghenv.Component.Message = "Script Crashed"

elif not process_drillings:
    summary = "Drilling skipped"
    ghenv.Component.Message = "Drilling skipped"

# --- OUTPUT TIMBER GEOMETRY ---
if drilled_model:
    for beam in drilled_model.beams:
        try:
            beams.append(beam.geometry)
        except Exception as e:
            geometry_errors.append(e)

    if len(geometry_errors) > 0:
        print(f"Failed to load {len(geometry_errors)} beam geometries.")
