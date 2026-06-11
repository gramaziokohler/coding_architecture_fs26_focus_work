# r: compas==2.15.1,timber_design==0.2.0,compas_fab==1.1.4
# venv: ca-fs26-focus-work

from compas_rhino.devtools import DevTools

DevTools.ensure_path()
ghenv.Component.Message = "Test Preferred TButt"

import Rhino.Geometry as rg

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector
from compas.scene import SceneObject
from compas_timber.elements import Beam
from compas_timber.model import TimberModel
from timber_design.workflow import DirectRule
from timber_design.workflow import JointRuleSolver

from a03_preferred_face_tbutt_joint import PreferredFaceTButtJoint


beam_width = vars().get("beam_width") or 0.060
beam_height = vars().get("beam_height") or 0.080
joint_max_distance = vars().get("joint_max_distance") or 0.020
mill_depth = vars().get("mill_depth") or 0.001
process_joinery = True if vars().get("process_joinery") is None else vars().get("process_joinery")
preferred_face_vector = vars().get("preferred_face_vector") or Vector(0, 0, 1)
cross_beam_ref_side_index = vars().get("cross_beam_ref_side_index")


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


def vector_to_compas(vector):
    if isinstance(vector, Vector):
        return vector
    return Vector(vector.X, vector.Y, vector.Z)


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

main_beam = make_beam(main_curve)
cross_beam = make_beam(cross_curve)

timber_model.add_element(main_beam)
timber_model.add_element(cross_beam)

rule = DirectRule(
    PreferredFaceTButtJoint,
    [main_beam, cross_beam],
    max_distance=joint_max_distance,
    mill_depth=mill_depth,
    preferred_face_vector=vector_to_compas(preferred_face_vector),
    cross_beam_ref_side_index=cross_beam_ref_side_index,
)

solver = JointRuleSolver([rule])
joining_errors, unjoined_clusters = solver.apply_rules_to_model(timber_model)

if process_joinery:
    timber_model.process_joinery()

joints = list(getattr(timber_model, "joints", None) or getattr(timber_model, "interactions", None) or [])
joint_count = len(joints)
joint_errors = [getattr(error, "debug_info", repr(error)) for error in joining_errors]

beams = [main_beam, cross_beam]
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

cross_ref_side_index = None
cross_ref_side = None
if joints:
    cross_ref_side_index = joints[0].cross_beam_ref_side_index
    cross_ref_side = cross_beam.ref_sides[cross_ref_side_index]

main_beam_out = main_beam
cross_beam_out = cross_beam
