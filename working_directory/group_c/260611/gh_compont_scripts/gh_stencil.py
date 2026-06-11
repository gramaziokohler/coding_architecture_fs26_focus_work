# r: compas==2.15.1,timber_design==0.2.0,compas_fab==1.1.4
# venv: ca-fs26-focus-work

from compas_rhino.devtools import DevTools

DevTools.ensure_path()
ghenv.Component.Message = "Stencil"

from a03_stencil import create_stencil


plate_thickness = vars().get("plate_thickness") or 0.010
hole_radius = vars().get("hole_radius") or 0.015
hole_segments = vars().get("hole_segments") or 24
beam_width = vars().get("beam_width") or 0.060
beam_height = vars().get("beam_height") or 0.080
joint_max_distance = vars().get("joint_max_distance") or 0.020
tbutt_mill_depth = vars().get("tbutt_mill_depth") or 0.001
lap_cut_plane_bias = vars().get("lap_cut_plane_bias") or 0.5
flip_lap_side = vars().get("flip_lap_side") or False
include_x_lap = vars().get("include_x_lap")
include_x_lap = True if include_x_lap is None else include_x_lap
process_joinery = vars().get("process_joinery") or False
compute_plate_geometry = vars().get("compute_plate_geometry") or False


result = create_stencil(
    rectangles=rectangles,
    points=points,
    lines=lines,
    plate_thickness=plate_thickness,
    hole_radius=hole_radius,
    hole_segments=hole_segments,
    beam_width=beam_width,
    beam_height=beam_height,
    joint_max_distance=joint_max_distance,
    tbutt_mill_depth=tbutt_mill_depth,
    lap_cut_plane_bias=lap_cut_plane_bias,
    flip_lap_side=flip_lap_side,
    include_x_lap=include_x_lap,
    process_joinery=process_joinery,
    compute_plate_geometry=compute_plate_geometry,
)


plates = result["plates"]
beams = result["beams"]
plates_out = result["plates_out"]
beams_out = result["beams_out"]
plate_holes_out = result["plate_holes_out"]
plate_holes_rhino = result["plate_holes_rhino"]
plates_rhino = result["plates_rhino"]
beams_rhino = result["beams_rhino"]
geometry_errors = result["geometry_errors"]
joints = result["joints"]
joint_count = result["joint_count"]
joint_types = result["joint_types"]
joint_errors = result["joint_errors"]
joining_errors = result["joining_errors"]
unjoined_clusters = result["unjoined_clusters"]
timber_model = result["timber_model"]
