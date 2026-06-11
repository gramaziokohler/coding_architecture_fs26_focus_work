
# venv: ca-fs26-focus-work

from compas_rhino.devtools import DevTools
DevTools.ensure_path()
ghenv.Component.Message = "Replace Miter -> CutoffLLapJoint"

# -------------------- IMPORTS ---------------------

import importlib
import a03_cutoff_l_lap_joint

importlib.reload(a03_cutoff_l_lap_joint)

from a03_cutoff_l_lap_joint import CutoffLLapJoint
from timber_design.workflow import DirectRule
from timber_design.workflow import JointRuleSolver

# ------------------- DEFAULTS ---------------------

if 'flip_lap_side' not in dir():                         flip_lap_side = False
if 'cut_plane_bias' not in dir():                        cut_plane_bias = 0.5
if 'cutoff_offset' not in dir():                         cutoff_offset = 0.0
if 'cutoff_offset_a' not in dir():                       cutoff_offset_a = None
if 'cutoff_offset_b' not in dir():                       cutoff_offset_b = None
if 'limit_lap_removal' not in dir():                     limit_lap_removal = True
if 'invert_lap_removal_plane' not in dir():              invert_lap_removal_plane = False
if 'extend_lap_removal_to_inner_edge' not in dir():      extend_lap_removal_to_inner_edge = False
if 'process_joinery' not in dir():                       process_joinery = True

# ------------------- VALIDATION -------------------

if timber_model is None:
    raise ValueError("timber_model input is required.")

# ------------------- FIND L-JOINTS BETWEEN BOUNDARY BEAMS ------------------

_BOUNDARY_CATEGORIES = {"base", "arch", "arch_A", "arch_B"}

def _is_boundary(beam):
    cat = beam.attributes.get("category", "")
    return cat in _BOUNDARY_CATEGORIES

def _is_l_joint(joint):
    """True for any joint that connects exactly two boundary beams with L-topology."""
    beam_a = getattr(joint, "beam_a", None)
    beam_b = getattr(joint, "beam_b", None)
    if beam_a is None or beam_b is None:
        return False
    if not (_is_boundary(beam_a) and _is_boundary(beam_b)):
        return False
    # Exclude T-topology joints (PreferredFaceTButtJoint, TButtJoint, TLapJoint, TBirdsmouth)
    type_name = type(joint).__name__
    if "TButt" in type_name or "TLap" in type_name or "TBird" in type_name or "Butt" in type_name:
        return False
    return True

_all_joints = list(
    getattr(timber_model, "joints", None)
    or getattr(timber_model, "interactions", None)
    or []
)
print("Total joints in model: {}".format(len(_all_joints)))
print("Joint types: {}".format(set(type(j).__name__ for j in _all_joints)))

target_joints = [j for j in _all_joints if _is_l_joint(j)]
print("Found {} boundary L-joints to replace with CutoffLLapJoint.".format(len(target_joints)))

# ------------------- REPLACEMENT ------------------

# Collect beam pairs before removing any joints
beam_pairs = [(j.beam_a, j.beam_b) for j in target_joints]

# Remove all target joints
for joint in target_joints:
    timber_model.remove_joint(joint)

# Build kwargs
_kwargs = dict(
    flip_lap_side=flip_lap_side,
    cut_plane_bias=float(cut_plane_bias),
    cutoff_offset=float(cutoff_offset),
    limit_lap_removal=bool(limit_lap_removal),
    invert_lap_removal_plane=bool(invert_lap_removal_plane),
    extend_lap_removal_to_inner_edge=bool(extend_lap_removal_to_inner_edge),
)
if cutoff_offset_a is not None:
    _kwargs["cutoff_offset_a"] = float(cutoff_offset_a)
if cutoff_offset_b is not None:
    _kwargs["cutoff_offset_b"] = float(cutoff_offset_b)

# Add new CutoffLLapJoints via DirectRule + solver
rules = [
    DirectRule(CutoffLLapJoint, [beam_a, beam_b], max_distance=0.05, **_kwargs)
    for beam_a, beam_b in beam_pairs
]

joining_errors = []
if rules:
    solver = JointRuleSolver(rules)
    joining_errors, _ = solver.apply_rules_to_model(timber_model)

replaced_count = len(beam_pairs) - len(joining_errors)
print("Replaced {} joint(s) with CutoffLLapJoint.".format(replaced_count))
if joining_errors:
    print("{} error(s):".format(len(joining_errors)))
    for err in joining_errors:
        print("  " + repr(err))

# ------------------- PROCESS JOINERY -------------

if process_joinery:
    print("Processing joinery...")
    timber_model.process_joinery()

# ------------------- OUTPUT -----------------------

replaced = replaced_count
errors = joining_errors
