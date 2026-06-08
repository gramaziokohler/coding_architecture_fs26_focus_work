#!/usr/bin/env python3
"""Export a COMPAS TimberModel JSON into the web viewer data format.

The exporter intentionally keeps beam naming in ``get_beam_identity``. Group C - Mahalo **
can replace only that function once their final attribute names are fixed.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path


DEFAULT_BASE_URL = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data"
DEFAULT_MODULE_SIZES = "A:36,B:31,C:30,D:27,E:27,F:31"
DEFAULT_DENSITY_KG_M3 = 500.0

NAME_KEYS = ("beam_id", "beam ID", "beam_name", "name", "label", "mark")
MODULE_KEYS = ("module", "module_id", "module_name", "fabrication_module", "assembly_module", "group")
NUMBER_KEYS = ("beam_number", "number", "sequence", "fabrication_number", "element_number", "index")


def rounded(value, digits=4):
    return round(float(value), digits)


def clean_id(value):
    value = str(value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[^A-Za-z0-9_-]", "", value)
    return value.lower()


def parse_module_sizes(value):
    sizes = []
    for item in value.split(","):
        if not item.strip():
            continue
        module, count = item.split(":", 1)
        sizes.append((module.strip().upper(), int(count)))
    return sizes


def sequential_identity(index, module_sizes):
    offset = 0
    for module, count in module_sizes:
        if index < offset + count:
            number = index - offset + 1
            beam_id = "{}{}".format(module.lower(), number)
            return beam_id, module, "{}{}".format(module, number)
        offset += count

    number = index + 1
    beam_id = "beam{}".format(number)
    return beam_id, "X", "Beam {}".format(number)


def first_value(mapping, keys):
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def get_beam_identity(index, element_guid, beam_data, module_sizes):
    """Return ``(beam_id, module, display_name)`` for one beam.

    Replace this function once Group C finalizes the attribute convention.
    Currently it checks both direct beam data and ``beam_data["attributes"]``.
    Expected useful attribute keys are:

    - beam id/name: ``beam_id``, ``beam_name``, ``name``, ``label``, ``mark``
    - module: ``module``, ``module_id``, ``fabrication_module``
    - number: ``beam_number``, ``number``, ``sequence``
    """

    attributes = beam_data.get("attributes") or {}
    lookup = {}
    lookup.update(beam_data)
    lookup.update(attributes)

    explicit_name = first_value(lookup, NAME_KEYS)
    module = first_value(lookup, MODULE_KEYS)
    number = first_value(lookup, NUMBER_KEYS)

    if explicit_name:
        beam_id = clean_id(explicit_name)
        display_name = str(explicit_name).strip().upper()
        module = str(module or display_name[:1] or "X").upper()
        return beam_id, module, display_name

    if module and number:
        module = str(module).strip().upper()
        display_name = "{}{}".format(module, number)
        return clean_id(display_name), module, display_name

    return sequential_identity(index, module_sizes)


def vector_add(a, b):
    return [a[i] + b[i] for i in range(3)]


def vector_sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def vector_scale(v, scale):
    return [v[i] * scale for i in range(3)]


def vector_cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def vector_length(v):
    return math.sqrt(sum(component * component for component in v))


def vector_normalize(v):
    length = vector_length(v)
    if not length:
        return [0.0, 0.0, 0.0]
    return [component / length for component in v]


def frame_from_data(frame_data):
    data = frame_data.get("data", frame_data)
    origin = data.get("point") or data.get("origin")
    x_axis = data.get("xaxis") or data.get("x_axis")
    y_axis = data.get("yaxis") or data.get("y_axis")
    z_axis = data.get("zaxis") or data.get("z_axis") or vector_cross(x_axis, y_axis)
    return {
        "origin": [float(v) for v in origin],
        "x_axis": vector_normalize([float(v) for v in x_axis]),
        "y_axis": vector_normalize([float(v) for v in y_axis]),
        "z_axis": vector_normalize([float(v) for v in z_axis]),
    }


def beam_box_vertices(frame, length, width, height):
    origin = frame["origin"]
    axes = (
        vector_scale(frame["x_axis"], length / 2.0),
        vector_scale(frame["y_axis"], width / 2.0),
        vector_scale(frame["z_axis"], height / 2.0),
    )
    vertices = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                point = origin
                point = vector_add(point, vector_scale(axes[0], sx))
                point = vector_add(point, vector_scale(axes[1], sy))
                point = vector_add(point, vector_scale(axes[2], sz))
                vertices.append(point)
    return vertices


def facet_normal(a, b, c):
    return vector_normalize(vector_cross(vector_sub(b, a), vector_sub(c, a)))


def triangulate_face(face):
    if len(face) < 3:
        return []
    if len(face) == 3:
        return [face]
    return [(face[0], face[index], face[index + 1]) for index in range(1, len(face) - 1)]


def write_mesh_ascii_stl(path, name, vertices, faces):
    with open(path, "w") as fp:
        fp.write("solid {}\n".format(name))
        for face in faces:
            for tri in triangulate_face(face):
                a, b, c = ([float(coord) for coord in vertices[i]] for i in tri)
                normal = facet_normal(a, b, c)
                fp.write("  facet normal {:.9g} {:.9g} {:.9g}\n".format(*normal))
                fp.write("    outer loop\n")
                for vertex in (a, b, c):
                    fp.write("      vertex {:.9g} {:.9g} {:.9g}\n".format(*vertex))
                fp.write("    endloop\n")
                fp.write("  endfacet\n")
        fp.write("endsolid {}\n".format(name))


def write_ascii_stl(path, name, vertices):
    # Vertex index from nested loops: x, y, z signs in that order.
    faces = [
        (0, 2, 3, 1),
        (4, 5, 7, 6),
        (0, 1, 5, 4),
        (2, 6, 7, 3),
        (0, 4, 6, 2),
        (1, 3, 7, 5),
    ]
    with open(path, "w") as fp:
        fp.write("solid {}\n".format(name))
        for face in faces:
            triangles = ((face[0], face[1], face[2]), (face[0], face[2], face[3]))
            for tri in triangles:
                a, b, c = (vertices[i] for i in tri)
                normal = facet_normal(a, b, c)
                fp.write("  facet normal {:.9g} {:.9g} {:.9g}\n".format(*normal))
                fp.write("    outer loop\n")
                for vertex in (a, b, c):
                    fp.write("      vertex {:.9g} {:.9g} {:.9g}\n".format(*vertex))
                fp.write("    endloop\n")
                fp.write("  endfacet\n")
        fp.write("endsolid {}\n".format(name))


def geometry_to_vertices_and_faces(geometry):
    """Best-effort conversion of COMPAS geometry/datastructures to mesh data."""

    if geometry is None:
        return None

    candidates = [geometry]
    if isinstance(geometry, (list, tuple)):
        candidates = list(geometry)

    combined_vertices = []
    combined_faces = []
    for candidate in candidates:
        if candidate is None:
            continue

        mesh = candidate
        if hasattr(candidate, "to_mesh"):
            mesh = candidate.to_mesh()

        if hasattr(mesh, "to_vertices_and_faces"):
            vertices, faces = mesh.to_vertices_and_faces()
        elif hasattr(mesh, "vertices") and hasattr(mesh, "faces"):
            vertices = mesh.vertices
            faces = mesh.faces
        else:
            continue

        offset = len(combined_vertices)
        combined_vertices.extend([[float(coord) for coord in vertex] for vertex in vertices])
        combined_faces.extend([[int(index) + offset for index in face] for face in faces])

    if not combined_vertices or not combined_faces:
        return None
    return combined_vertices, combined_faces


def iter_model_beams(model):
    beams = getattr(model, "beams", None)
    if beams is not None:
        for beam in beams:
            yield beam
        return

    elements = getattr(model, "elements", None)
    if elements is not None:
        for element in elements:
            if hasattr(element, "frame") and hasattr(element, "geometry"):
                yield element


def load_processed_compas_meshes(model_path, process_joinery=True):
    """Load TimberModel with COMPAS Timber and return beam mesh data.

    This is optional by design. The script also runs in plain Python without
    COMPAS Timber and then falls back to rectangular box STLs.
    """

    repo_code_dir = Path(__file__).resolve().parent
    if str(repo_code_dir) not in sys.path:
        sys.path.insert(0, str(repo_code_dir))

    from compas.data import json_load

    try:
        import compas_timber  # noqa: F401
    except ImportError as error:
        raise RuntimeError("compas_timber is not installed in this Python environment") from error

    try:
        from compas.geometry import Frame  # noqa: F401
        from compas.geometry import Point  # noqa: F401
        from compas.geometry import Vector  # noqa: F401
        from compas_timber.elements import Beam  # noqa: F401
        from compas_timber.model import TimberModel  # noqa: F401
        from compas_timber.connections import LMiterJoint  # noqa: F401
        from compas_timber.connections import TButtJoint  # noqa: F401
        from compas_timber.connections import XLapJoint  # noqa: F401
    except Exception:
        pass

    # Register local custom classes used by exported TimberModels when present.
    try:
        import a03_preferred_face_tbutt_joint  # noqa: F401
        import a03_cutoff_l_lap_joint  # noqa: F401
        import base_lap  # noqa: F401
        import b_metal_plate_pocket  # noqa: F401
        import metal_plate_lap  # noqa: F401
    except Exception:
        pass

    model = json_load(str(model_path))
    if process_joinery and hasattr(model, "process_joinery"):
        model.process_joinery()

    by_guid = {}
    by_index = {}
    errors = []

    for index, beam in enumerate(iter_model_beams(model)):
        try:
            mesh_data = geometry_to_vertices_and_faces(beam.geometry)
            if not mesh_data:
                errors.append("Beam {} geometry did not convert to mesh".format(index))
                continue
            guid = str(getattr(beam, "guid", ""))
            if guid:
                by_guid[guid] = mesh_data
            by_index[index] = mesh_data
        except Exception as error:
            errors.append("Beam {} geometry: {!r}".format(index, error))

    return by_guid, by_index, errors


def point_data(value):
    if not value:
        return None
    if isinstance(value, dict):
        return value.get("data")
    return value


def joint_kind(name):
    lower = (name or "").lower()
    if "xlap" in lower:
        return "xlap"
    if "tbutt" in lower:
        return "tbutt"
    if "lmiter" in lower:
        return "lmiter"
    return "other"


def collect_joints(model_data, guid_to_beam_id):
    joints_by_beam = defaultdict(list)
    connected = defaultdict(set)
    joints = model_data.get("joints") or model_data.get("interactions") or {}

    for index, (joint_guid, joint) in enumerate(joints.items(), start=1):
        data = joint.get("data", {})
        element_guids = data.get("element_guids") or []
        beam_ids = [guid_to_beam_id[guid] for guid in element_guids if guid in guid_to_beam_id]
        if len(beam_ids) < 2:
            continue

        name = data.get("name") or joint.get("dtype", "").split("/")[-1] or "Joint"
        kind = joint_kind(name)
        location = point_data(data.get("location"))
        joint_id = str(index)
        detail = {
            "id": joint_id,
            "guid": joint_guid,
            "type": name,
            "kind": kind,
            "connected_beams": beam_ids,
            "location": [rounded(v) for v in location] if location else None,
        }

        for beam_id in beam_ids:
            joints_by_beam[beam_id].append(detail)
            for other_id in beam_ids:
                if other_id != beam_id:
                    connected[beam_id].add(other_id)

    return joints_by_beam, connected


def make_structure_entry(beam):
    return {
        "beam_id": beam["beam_id"],
        "module": beam["module"],
        "centerline_start": beam["centerline_start"],
        "centerline_end": beam["centerline_end"],
        "midpoint": beam["midpoint"],
        "midpoint_normalized": beam["midpoint_normalized"],
        "connected_beams": beam["connected_beams"],
    }


def export_web_data(model_path, output_dir, base_url, density, module_sizes, clean=False, geometry_source="auto", process_joinery=True):
    with open(model_path, "r") as fp:
        model = json.load(fp)

    model_data = model["data"]
    elements = [
        (guid, element)
        for guid, element in model_data.get("elements", {}).items()
        if element.get("dtype", "").endswith("/Beam")
    ]

    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    beams_dir = output_dir / "beams"
    beams_dir.mkdir(parents=True, exist_ok=True)

    compas_meshes_by_guid = {}
    compas_meshes_by_index = {}
    compas_geometry_errors = []
    if geometry_source in ("auto", "compas"):
        try:
            compas_meshes_by_guid, compas_meshes_by_index, compas_geometry_errors = load_processed_compas_meshes(
                model_path,
                process_joinery=process_joinery,
            )
        except Exception as error:
            compas_geometry_errors = ["Could not load COMPAS Timber geometry: {!r}".format(error)]
            if geometry_source == "compas":
                raise

    beam_records = []
    guid_to_beam_id = {}

    for index, (guid, element) in enumerate(elements):
        data = element["data"]
        beam_id, module, display_name = get_beam_identity(index, guid, data, module_sizes)
        guid_to_beam_id[guid] = beam_id
        frame = frame_from_data(data["frame"])
        length = float(data["length"])
        width = float(data["width"])
        height = float(data["height"])
        centerline_start = vector_sub(frame["origin"], vector_scale(frame["x_axis"], length / 2.0))
        centerline_end = vector_add(frame["origin"], vector_scale(frame["x_axis"], length / 2.0))
        volume_m3 = length * width * height

        beam_records.append({
            "guid": guid,
            "beam_id": beam_id,
            "name": display_name,
            "module": module,
            "frame": frame,
            "length": length,
            "width": width,
            "height": height,
            "volume_m3": volume_m3,
            "weight_kg": volume_m3 * density,
            "centerline_start": centerline_start,
            "centerline_end": centerline_end,
            "midpoint": frame["origin"],
            "features": data.get("features") or [],
            "extra_processings": [
                {"name": key, "data": value}
                for key, value in data.items()
                if key not in {"frame", "length", "width", "height", "features", "attributes"}
                and isinstance(value, dict)
                and "fabrication/" in str(value.get("dtype", ""))
            ],
            "mesh_data": compas_meshes_by_guid.get(guid) or compas_meshes_by_index.get(index),
        })

    all_points = []
    for beam in beam_records:
        all_points.extend([beam["centerline_start"], beam["centerline_end"]])

    bounds_min = [min(point[i] for point in all_points) for i in range(3)]
    bounds_max = [max(point[i] for point in all_points) for i in range(3)]
    bounds_size = [bounds_max[i] - bounds_min[i] for i in range(3)]

    for beam in beam_records:
        beam["midpoint_normalized"] = [
            0.0 if not bounds_size[i] else (beam["midpoint"][i] - bounds_min[i]) / bounds_size[i]
            for i in range(3)
        ]

    joints_by_beam, connected = collect_joints(model_data, guid_to_beam_id)

    for beam in beam_records:
        beam_id = beam["beam_id"]
        beam_dir = beams_dir / beam_id
        beam_dir.mkdir(parents=True, exist_ok=True)
        stl_path = beam_dir / "{}.stl".format(beam_id)
        json_path = beam_dir / "{}.json".format(beam_id)

        if beam["mesh_data"]:
            vertices, faces = beam["mesh_data"]
            write_mesh_ascii_stl(stl_path, beam_id, vertices, faces)
        else:
            vertices = beam_box_vertices(beam["frame"], beam["length"], beam["width"], beam["height"])
            write_ascii_stl(stl_path, beam_id, vertices)

        joint_details = joints_by_beam.get(beam_id, [])
        joint_groups = {
            "all": [joint["id"] for joint in joint_details],
            "xlap": [joint["id"] for joint in joint_details if joint["kind"] == "xlap"],
            "tbutt": [joint["id"] for joint in joint_details if joint["kind"] == "tbutt"],
            "lmiter": [joint["id"] for joint in joint_details if joint["kind"] == "lmiter"],
            "details": joint_details,
        }

        beam_json = {
            "beam ID": beam_id,
            "name": beam["name"],
            "module": beam["module"],
            "width (m)": rounded(beam["width"]),
            "height (m)": rounded(beam["height"]),
            "length (m)": rounded(beam["length"]),
            "volume (cm3)": rounded(beam["volume_m3"] * 1000000.0, 2),
            "weight (kg)": rounded(beam["weight_kg"], 2),
            "local_frame": {
                "origin": [rounded(v) for v in beam["frame"]["origin"]],
                "x_axis": [rounded(v) for v in beam["frame"]["x_axis"]],
                "y_axis": [rounded(v) for v in beam["frame"]["y_axis"]],
                "z_axis": [rounded(v) for v in beam["frame"]["z_axis"]],
            },
            "connected_beams": sorted(connected.get(beam_id, [])),
            "global_position": {
                "centerline_start": [rounded(v) for v in beam["centerline_start"]],
                "centerline_end": [rounded(v) for v in beam["centerline_end"]],
                "midpoint": [rounded(v) for v in beam["midpoint"]],
                "midpoint_normalized": [rounded(v) for v in beam["midpoint_normalized"]],
            },
            "joints": joint_groups,
            "processing": beam["features"] + beam["extra_processings"],
            "3d_model": "{}/beams/{}/{}.stl".format(base_url.rstrip("/"), beam_id, beam_id),
        }

        with open(json_path, "w") as fp:
            json.dump(beam_json, fp, indent=2)

    structure = {
        "total_beams": len(beam_records),
        "bounding_box": {
            "min": [rounded(v) for v in bounds_min],
            "max": [rounded(v) for v in bounds_max],
        },
        "beams": [make_structure_entry({
            **beam,
            "centerline_start": [rounded(v) for v in beam["centerline_start"]],
            "centerline_end": [rounded(v) for v in beam["centerline_end"]],
            "midpoint": [rounded(v) for v in beam["midpoint"]],
            "midpoint_normalized": [rounded(v) for v in beam["midpoint_normalized"]],
            "connected_beams": sorted(connected.get(beam["beam_id"], [])),
        }) for beam in beam_records],
    }

    with open(output_dir / "structure.json", "w") as fp:
        json.dump(structure, fp, indent=2)

    compas_mesh_count = sum(1 for beam in beam_records if beam["mesh_data"])
    return {
        "beam_count": len(beam_records),
        "joint_ref_count": sum(len(joints) for joints in joints_by_beam.values()),
        "compas_mesh_count": compas_mesh_count,
        "box_mesh_count": len(beam_records) - compas_mesh_count,
        "compas_geometry_errors": compas_geometry_errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="Path to TimberModel JSON")
    parser.add_argument("--output", type=Path, default=Path("web_data"), help="Output web_data folder")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Public base URL used in beam JSON 3d_model fields")
    parser.add_argument("--density", type=float, default=DEFAULT_DENSITY_KG_M3, help="Wood density in kg/m3")
    parser.add_argument("--module-sizes", default=DEFAULT_MODULE_SIZES, help="Fallback naming, for example A:36,B:31,C:30")
    parser.add_argument("--geometry-source", choices=("auto", "compas", "box"), default="auto", help="STL source. auto tries COMPAS Timber processed beam.geometry, then boxes.")
    parser.add_argument("--skip-process-joinery", action="store_true", help="Do not call model.process_joinery() before reading beam.geometry")
    parser.add_argument("--clean", action="store_true", help="Delete output folder before exporting")
    args = parser.parse_args()

    result = export_web_data(
        model_path=args.model,
        output_dir=args.output,
        base_url=args.base_url,
        density=args.density,
        module_sizes=parse_module_sizes(args.module_sizes),
        clean=args.clean,
        geometry_source=args.geometry_source,
        process_joinery=not args.skip_process_joinery,
    )
    print("Exported {} beams to {}".format(result["beam_count"], args.output))
    print("Wrote {} beam-joint references".format(result["joint_ref_count"]))
    print("STL geometry: {} processed COMPAS meshes, {} rectangular box fallbacks".format(
        result["compas_mesh_count"],
        result["box_mesh_count"],
    ))
    for error in result["compas_geometry_errors"][:8]:
        print("Geometry note: {}".format(error))
    if len(result["compas_geometry_errors"]) > 8:
        print("Geometry note: {} more geometry messages omitted".format(len(result["compas_geometry_errors"]) - 8))


if __name__ == "__main__":
    main()
