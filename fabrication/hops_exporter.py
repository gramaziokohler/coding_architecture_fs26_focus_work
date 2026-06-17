"""hops_exporter.py
===================
Grasshopper-compatible beam visualiser / .hop exporter.

GH Python component usage
--------------------------
Inputs (Item Access, No Type Hint unless noted):
    filepath    : str  — path to the JSON fabrication model
    index       : int  — beam idx attribute (idx-mode)
    hierarchy   : str  — beam hierarchy, e.g. "shoe", "primary" (type-mode)
    type_index  : int  — 0-based position within the filtered hierarchy list (type-mode)
    export      : bool — write .hop file to <filepath_dir>/hops/<beam.name>.hop

When hierarchy is set, type-mode is used and index is ignored.
When hierarchy is None, idx-mode is used and index is matched against beam.attributes["idx"].

Outputs:
    geometry          — Rhino geometry drawn by the scene
    processing_report — list[str], one entry per BTLx processing on the beam
                        format: "PROCESSING_NAME | ref_side: N"

Note: add 'processing_report' as a named output parameter on the GH Python component.

GH component body (minimal):
    import os, sys, importlib

    gh_dir = os.path.dirname(ghenv.Component.OnPingDocument().FilePath)
    # go up from your GH file to the repo root, then down to fabrication/cnc
    # adjust the number of dirname() calls to match your GH file's folder depth
    repo_root = os.path.dirname(os.path.dirname(gh_dir))  # e.g. design/modularization -> design -> repo root
    cnc_dir = os.path.join(repo_root, "fabrication", "cnc")
    if cnc_dir not in sys.path:
        sys.path.insert(0, cnc_dir)

    import hops_exporter
    importlib.reload(hops_exporter)

    geometry, processing_report = hops_exporter.run(filepath, index, hierarchy, type_index, export, ghenv)
"""

import math
import os

import Grasshopper.Kernel as gh

from compas.data import json_load
from compas.geometry import Rotation
from compas.geometry import Translation
from compas.geometry import Vector
from compas.scene import Scene
from compas.tolerance import TOL

from compas_timber.fabrication import Drilling, JackRafterCut
from compas_timber.btlx import BTLxReader

from easyhops.hop_job import HOPSJob
from easyhops.hop_core import ParkMode
from easyhops.utility_commands import MachineStop
from easyhops.strategies import LapStrategies
from easyhops.strategies import JackRafterCutStrategies
from easyhops.strategies import DrillingStrategies
from easyhops.strategies import PocketStrategies
from easyhops.tool_library import SaegeD350
from easyhops.tool_library import CastorD61
from easyhops.tool_library import MachiningTool


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def load_model(filepath):
    model_dict = json_load(filepath)
    model = model_dict[0]["model"]
    model.process_joinery()

    return model


def load_btlx(filepath):
    """Load a BTLx file and return the first beam element."""
    reader = BTLxReader()
    model = reader.read(filepath)
    if reader.errors:
        reader.print_errors()
    return model


# ---------------------------------------------------------------------------
# Beam resolution
# ---------------------------------------------------------------------------


def resolve_element(model, index=None, group=None, ref_side=None):
    """Return a beam element from the model by index or group."""

    elements = list(model.elements())
    if group is not None:
        elements = [e for e in elements if e.name.startswith(group)]
        print(
            "Group[{}] {}/{} -> {}".format(
                group, index + 1, len(elements), elements[index].name
            )
        )
    element = elements[index]

    # set the ref_side_index attribute on the element for later use in feature overrides
    element.attributes["ref_side_index"] = ref_side
    return element


def override_features(element, allow_flip=False):
    """Replace any JackRafterCut features on the beam with new features based on the same planes but with ref_side_index taken from beam attributes."""

    ref_side_index = element.attributes.get("ref_side_index", 0)
    _, height = element.get_dimensions_relative_to_side(ref_side_index)

    for f in list(element.features):
        if isinstance(f, JackRafterCut):
            plane = f.plane_from_params_and_beam(element)
            new_feature = f.__class__.from_plane_and_beam(
                plane, element, ref_side_index
            )
            if height < 120.0:
                # remove the feature only if the cut can be done from only one side
                element.remove_features(f)
            element.add_feature(new_feature)
        elif isinstance(f, Drilling):
            if f.ref_side_index == (ref_side_index + 2) % 4:
                line = f.line_from_params_and_element(element)
                new_feature = f.__class__.from_line_and_element(
                    line, element, f.diameter, ref_side_index=ref_side_index
                )
            elif f.ref_side_index == ref_side_index:
                pass
            else:
                try:
                    line = f.line_from_params_and_element(element)
                    new_feature = f.__class__.from_line_and_element(
                        line, element, f.diameter, ref_side_index=ref_side_index
                    )
                except Exception:
                    pass

            if new_feature is not None:
                element.add_feature(new_feature)
                element.remove_features(f)


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------


def visualize_geometry(element, ghenv=None):
    """Transform the beam to the origin and add blank edges + featured geometry to scene."""
    scene = Scene()
    warn = gh.GH_RuntimeMessageLevel.Warning

    ref_side_index = element.attributes.get("ref_side_index", 0)

    width, _ = element.get_dimensions_relative_to_side(ref_side_index)

    # warn if the beam is too narrow for machining without clams
    if width < 75:
        ghenv.Component.AddRuntimeMessage(
            warn,
            "Warning: beam {} is will require the clams for machining (dy={:.1f}mm < 75mm)".format(
                element.name, width
            ),
        )

    ref_frame = element.ref_frame.transformed(element.transformation_to_local())
    translation = Translation.from_vector(
        Vector.from_start_end(ref_frame.point, [0, 0, 0])
    ) * Translation.from_vector([0, width, 0])
    rotation = Rotation.from_axis_and_angle([1, 0, 0], math.pi * ref_side_index / 2)
    transformation = translation * rotation

    # blank edges
    blank_brp = element.compute_elementgeometry(include_features=False)
    blank_brp.transform(transformation)
    for edge in blank_brp.edges:
        scene.add(edge.curve)

    # geometry with features
    geometry = element.compute_elementgeometry(include_features=True)
    scene.add(geometry.transformed(transformation))
    return scene.draw()


# ---------------------------------------------------------------------------
# Processing report
# ---------------------------------------------------------------------------


def get_processing_report(element):
    """Return a list of strings describing each BTLx processing on the beam.

    Each entry has the format: "PROCESSING_NAME | ref_side: N"
    """
    width, height = element.get_dimensions_relative_to_side(
        element.attributes.get("ref_side_index", 0)
    )
    report = [
        "Beam: {} | RSId: {} | W: {:.1f} x H: {:.1f}".format(
            element.name, element.attributes.get("ref_side_index"), width, height
        )
    ]
    report.append("-------------")
    report.extend(
        "{} | RSId: {}".format(feature.PROCESSING_NAME, feature.ref_side_index)
        for feature in element.features
    )
    return report


# ---------------------------------------------------------------------------
# Export HOPS
# ---------------------------------------------------------------------------


def _element_to_job(element, scale_factor=1.0):
    """Build a HOPSJob for *element* with explicit control over dispatch.

    Returns:
        job              — HOPSJob
        machining_report — list[str] comparing registered BTLx processings to
                           the machinings actually produced (one entry per
                           processing, plus a pass/fail summary line)
    """
    job = HOPSJob.from_element(element, scale_factor=scale_factor)

    rsi = job.ref_side_index
    opp_rsi = (rsi + 2) % 4

    pre_flip = []
    post_flip = []

    # Each entry: {"name": str, "rsi": int|str, "status": "ok"|"empty"|"skipped",
    #              "count": int, "placement": str, "ops": list[str]}
    conversion_log = []

    def _dispatch(name, rsi_proc, machinings, placement):
        ops = []
        for m in machinings:
            op = getattr(m, "OPERATION_TYPE", "?")
            tool = getattr(m, "tool", None)
            tool_name = type(tool).__name__ if tool is not None else "no-tool"
            ops.append("{} / {}".format(op, tool_name))
            m._processing_name = name  # tag for sorting
        status = "ok" if machinings else "empty"
        conversion_log.append(
            {
                "name": name,
                "rsi": rsi_proc,
                "status": status,
                "count": len(machinings),
                "placement": placement,
                "ops": ops,
            }
        )

    for processing in element.features:
        processing = processing.scaled(scale_factor)
        name = processing.PROCESSING_NAME
        rsi_proc = getattr(processing, "ref_side_index", "?")

        if name == "Lap":
            if processing.ref_side_index == opp_rsi:
                machinings = LapStrategies.pocketing(
                    processing, machine_ref_side_index=opp_rsi, tool=CastorD61()
                )
                # introduce a flip if the lap is on the opposite side
                pre_flip.extend(machinings)
                _dispatch(name, rsi_proc, machinings, "pre-flip")
            else:
                machinings = LapStrategies.pocketing(
                    processing, machine_ref_side_index=rsi, tool=CastorD61()
                )
                post_flip.extend(machinings)
                _dispatch(name, rsi_proc, machinings, "post-flip")

        elif name == "JackRafterCut":
            assert processing.ref_side_index in (rsi, opp_rsi), (
                f"Unexpected ref_side_index {processing.ref_side_index} for JackRafterCut"
            )
            if processing.ref_side_index == opp_rsi:
                machinings = JackRafterCutStrategies.sawing(
                    processing, machine_ref_side_index=opp_rsi, tool=SaegeD350()
                )
                pre_flip.extend(machinings)
                _dispatch(name, rsi_proc, machinings, "pre-flip")
            else:
                machinings = JackRafterCutStrategies.sawing(
                    processing, machine_ref_side_index=rsi, tool=SaegeD350()
                )
                post_flip.extend(machinings)
                _dispatch(name, rsi_proc, machinings, "post-flip")

        elif name == "Pocket":
            if processing.ref_side_index == opp_rsi:
                machinings = PocketStrategies.pocketing(
                    processing,
                    machine_ref_side_index=opp_rsi,
                    tool=MachiningTool(position=403),
                )
                pre_flip.extend(machinings)
                _dispatch(name, rsi_proc, machinings, "pre-flip")
            else:
                machinings = PocketStrategies.pocketing(
                    processing,
                    machine_ref_side_index=rsi,
                    tool=MachiningTool(position=403),
                )
                post_flip.extend(machinings)
                _dispatch(name, rsi_proc, machinings, "post-flip")

        elif name == "Drilling":
            if processing.diameter == 4.0:
                if processing.ref_side_index == opp_rsi:
                    pre_flip.extend(
                        DrillingStrategies.pre_drilling(
                            processing,
                            machine_ref_side_index=opp_rsi,  # use opp_rsi to mill and add a 180 flip
                        )
                    )
                    _dispatch(name, rsi_proc, [], "pre-flip (pre-drill)")
                else:
                    machinings = DrillingStrategies.pre_drilling(
                        processing, machine_ref_side_index=rsi
                    )
                    # skip the drilling if it's too steep
                    if TOL.is_positive(abs(processing.inclination) - 20.0):
                        machinings.extend(
                            DrillingStrategies.drilling(
                                processing, machine_ref_side_index=rsi
                            )
                        )
                    post_flip.extend(machinings)
                    _dispatch(name, rsi_proc, machinings, "post-flip (pre-drill)")
            else:
                machinings = DrillingStrategies.drilling(
                    processing,
                    machine_ref_side_index=rsi,
                )
                if processing.ref_side_index == opp_rsi:
                    pre_flip.extend(machinings)
                    _dispatch(name, rsi_proc, machinings, "pre-flip")
                else:
                    post_flip.extend(machinings)
                    _dispatch(name, rsi_proc, machinings, "post-flip")

        else:
            conversion_log.append(
                {
                    "name": name,
                    "rsi": rsi_proc,
                    "status": "skipped",
                    "count": 0,
                    "placement": "-",
                    "ops": [],
                }
            )

    # Sort order: operation type → tool position → processing name
    OP_ORDER = {"SAWING": 2, "DRILLING": 0, "MILLING": 1}

    POST_FLIP_PROCESSING_ORDER = {
        "JackRafterCut": 9,  # always FIRST — saw cut removes the end of the beam
        "Drilling": 1,
        "Lap": 2,
        "Pocket": 0,
    }
    PRE_FLIP_PROCESSING_ORDER = {
        "Drilling": 1,
        "Lap": 2,
        "Pocket": 9,
        "JackRafterCut": 0,  # always LAST — saw cut removes the end of the beam
    }

    def _sort_key(processing_order):
        def key(m):
            op_priority = OP_ORDER.get(getattr(m, "OPERATION_TYPE", ""), 3)
            tool = getattr(m, "tool", None)
            tool_position = getattr(tool, "position", 0) if tool is not None else 0
            processing_priority = processing_order.get(
                getattr(m, "_processing_name", ""), 50
            )
            return (processing_priority, op_priority, tool_position)

        return key

    pre_flip.sort(key=_sort_key(PRE_FLIP_PROCESSING_ORDER))
    post_flip.sort(key=_sort_key(POST_FLIP_PROCESSING_ORDER))

    if pre_flip:
        job.add(pre_flip)
        job.add(MachineStop(message="flip beam 180deg", park_mode=ParkMode.RIGHT_FRONT))
    job.add(post_flip)

    # --- Build comparison report ---
    n_total = len(conversion_log)
    n_ok = sum(1 for e in conversion_log if e["status"] == "ok")
    n_empty = sum(1 for e in conversion_log if e["status"] == "empty")
    n_skipped = sum(1 for e in conversion_log if e["status"] == "skipped")
    all_ok = n_ok == n_total

    STATUS_ICON = {"ok": "[OK]     ", "empty": "[EMPTY]  ", "skipped": "[SKIPPED]"}

    machining_report = [
        "=== Conversion report: {} (beam rsi={}) ===".format(element.name, rsi),
        "  Registered processings : {}".format(n_total),
        "  Converted (>0 machinings): {}".format(n_ok),
        "  Converted (0 machinings) : {}".format(n_empty),
        "  Skipped (no handler)    : {}".format(n_skipped),
        "  Result: {}".format(
            "ALL CONVERTED"
            if all_ok
            else "WARNING: {} processing(s) not fully converted".format(
                n_empty + n_skipped
            )
        ),
        "  " + "-" * 56,
    ]
    for i, entry in enumerate(conversion_log):
        icon = STATUS_ICON[entry["status"]]
        machining_report.append(
            "  {} #{:02d} {:22s} RSId:{} | {} | {} machining(s)".format(
                icon, i, entry["name"], entry["rsi"], entry["placement"], entry["count"]
            )
        )
        for op_str in entry["ops"]:
            machining_report.append("           -> {}".format(op_str))

    machining_report.append(
        "  pre-flip machinings: {}  |  post-flip machinings: {}".format(
            len(pre_flip), len(post_flip)
        )
    )

    return job, machining_report


def export_hop(beam, export_dir):
    """Write a .hop file for beam into export_dir/<beam.name>.hop.

    Returns:
        job              — HOPSJob
        machining_report — list[str] describing what each processing produced
    """
    os.makedirs(export_dir, exist_ok=True)
    hop_path = os.path.join(export_dir, beam.name + ".hop")
    job, machining_report = _element_to_job(beam)
    job.to_hop_file(hop_path)
    return job, machining_report


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(filepath, index, ref_side, export, group=None, allow_flip=False, ghenv=None):
    """Load a BTLx file, resolve one beam by index, visualise it, optionally export it, and return a processing report.

    Parameters:
        filepath  — path to the BTLx fabrication file
        index     — 0-based position in model.elements()
        ref_side  — ref_side_index to assign to the beam
        export    — write .hop file to <filepath_dir>/HOPS/<beam.name>.hop
        allow_flip — passed to override_features
        ghenv     — Grasshopper component environment (for runtime messages)

    Returns:
        geometry          — result of scene.draw()
        processing_report — list[str] of processing descriptions
    """
    # Load model
    model = load_btlx(filepath)
    export_dir = os.path.join(os.path.dirname(filepath), "HOPS")

    # Get element by index (optionally filtered by group)
    element = resolve_element(model, index=index, group=group, ref_side=ref_side)

    # Override features
    override_features(element, allow_flip)

    # Visualise geometry
    geometry = visualize_geometry(element, ghenv=ghenv)

    # Export HOP
    machining_report = []
    if export:
        _, machining_report = export_hop(element, export_dir)

    # Get processing report
    processing_report = get_processing_report(element)

    return geometry, processing_report + ["-" * 40] + machining_report
