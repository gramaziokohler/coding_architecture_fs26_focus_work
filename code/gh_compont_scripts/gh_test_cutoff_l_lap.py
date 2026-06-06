# r: compas==2.15.1,timber_design==0.2.0,compas_fab==1.1.4
# venv: ca-fs26-focus-work

from compas_rhino.devtools import DevTools

DevTools.ensure_path()
ghenv.Component.Message = "Test Cutoff L-Lap"

import Rhino.Geometry as rg

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector
from compas.scene import SceneObject
from compas_timber.elements import Beam
from compas_timber.model import TimberModel
from timber_design.workflow import DirectRule
from timber_design.workflow import JointRuleSolver

from a03_cutoff_l_lap_joint import CutoffLLapJoint


beam_width = vars().get("beam_width") or 0.060
beam_height = vars().get("beam_height") or 0.080
joint_max_distance = vars().get("joint_max_distance") or 0.020
cut_plane_bias = vars().get("cut_plane_bias") or 0.5
cutoff_offset = vars().get("cutoff_offset") or 0.0
cutoff_offset_a = vars().get("cutoff_offset_a")
cutoff_offset_b = vars().get("cutoff_offset_b")
limit_lap_removal = True if vars().get("limit_lap_removal") is None else vars().get("limit_lap_removal")
invert_lap_removal_plane = vars().get("invert_lap_removal_plane") or False
extend_lap_removal_to_inner_edge = vars().get("extend_lap_removal_to_inner_edge") or False
flip_lap_side = vars().get("flip_lap_side") or False
process_joinery = True if vars().get("process_joinery") is None else vars().get("process_joinery")


def rhino_curve_to_line(curve):
    if isinstance(curve, rg.Line):
        line = curve
    elif isinstance(curve, rg.LineCurve):
        line = curve.Line
    elif isinstance(curve, rg.PolylineCurve):
        polyline = curve.ToPolyline()
        if polyline.Count < 2:
            raise ValueError("PolylineCurve must have at least two points.")
        line = rg.Line(polyline[0], polyline[polyline.Count - 1])
    else:
        try:
            success, line = curve.TryGetLine()
        except AttributeError:
            success = False
        if not success:
            line = rg.Line(curve.PointAtStart, curve.PointAtEnd)

    return Line(
        Point(line.From.X, line.From.Y, line.From.Z),
        Point(line.To.X, line.To.Y, line.To.Z),
    )


def make_beam(curve):
    return Beam.from_centerline(
        rhino_curve_to_line(curve),
        width=beam_width,
        height=beam_height,
        z_vector=Vector(0, 0, 1),
    )


def to_rhino(geometry, errors):
    try:
        return SceneObject(item=geometry).draw()
    except Exception as error:
        errors.append("Rhino conversion: {!r}".format(error))
        return None


errors = []
timber_model = TimberModel()

beam_a = make_beam(beam_a_curve)
beam_b = make_beam(beam_b_curve)

timber_model.add_element(beam_a)
timber_model.add_element(beam_b)

rule = DirectRule(
    CutoffLLapJoint,
    [beam_a, beam_b],
    max_distance=joint_max_distance,
    flip_lap_side=flip_lap_side,
    cut_plane_bias=cut_plane_bias,
    cutoff_offset=cutoff_offset,
    cutoff_offset_a=cutoff_offset_a,
    cutoff_offset_b=cutoff_offset_b,
    limit_lap_removal=limit_lap_removal,
    invert_lap_removal_plane=invert_lap_removal_plane,
    extend_lap_removal_to_inner_edge=extend_lap_removal_to_inner_edge,
)

solver = JointRuleSolver([rule])
joining_errors, unjoined_clusters = solver.apply_rules_to_model(timber_model)

if process_joinery:
    timber_model.process_joinery()

joints = list(getattr(timber_model, "joints", None) or getattr(timber_model, "interactions", None) or [])
joint_count = len(joints)
joint_errors = [getattr(error, "debug_info", repr(error)) for error in joining_errors]

beams = [beam_a, beam_b]
beams_out = []
beams_rhino = []
for beam in beams:
    try:
        geometry = beam.geometry
        beams_out.append(geometry)
        beams_rhino.append(to_rhino(geometry, errors))
    except Exception as error:
        errors.append("{} geometry: {!r}".format(type(beam).__name__, error))
        beams_out.append(None)
        beams_rhino.append(None)

cutting_plane_a = None
cutting_plane_b = None
extension_plane_a = None
extension_plane_b = None
negative_volume_a = None
negative_volume_b = None
negative_volume_a_rhino = None
negative_volume_b_rhino = None
clip_status = []
centerline_intersection = None
if joints:
    joint = joints[0]
    cutting_plane_a = joint.cutting_plane_a
    cutting_plane_b = joint.cutting_plane_b
    extension_plane_a = joint.extension_plane_a
    extension_plane_b = joint.extension_plane_b
    negative_volume_a = joint.debug_negative_volume_a
    negative_volume_b = joint.debug_negative_volume_b
    negative_volume_a_rhino = to_rhino(negative_volume_a.to_mesh(), errors) if negative_volume_a else None
    negative_volume_b_rhino = to_rhino(negative_volume_b.to_mesh(), errors) if negative_volume_b else None
    clip_status = joint.debug_clip_status
    centerline_intersection = joint.centerline_intersection

beam_a_out = beam_a.geometry    
beam_b_out = beam_b.geometry
