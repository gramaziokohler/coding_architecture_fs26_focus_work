# r: compas==2.15.1,timber_design==0.2.0,compas_fab==1.1.4
# venv: ca-fs26-focus-work

"""Grasshopper component script: export TimberModel to web_data.

Inputs expected on the GH Python component:
    model            TimberModel
    path             Output folder path, normally .../coding_architecture.../web_data
    run              Boolean

Optional inputs:
    base_url         Public web_data URL used in beam JSON 3d_model fields
    density          kg/m3, default 500
    process_joinery  Boolean, default True
    clean            Boolean, default True
    module_sizes     Fallback naming, e.g. "A:36,B:31,C:30,D:27,E:27,F:31"
    repo_path        Optional repository folder, used to resolve relative paths

Outputs you may add:
    export_message
    exported_count
    stl_count
    box_fallback_count
    errors
"""

import json
import math
import os
import re
import shutil
from collections import defaultdict


ghenv.Component.Message = "Export Web Data"


DEFAULT_BASE_URL = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data"
DEFAULT_DENSITY_KG_M3 = 500.0
DEFAULT_MODULE_SIZES = "A:36,B:31,C:30,D:27,E:27,F:31"

NAME_KEYS = ("beam_id", "beam ID", "beam_name", "name", "label", "mark")
MODULE_KEYS = ("module", "module_id", "module_name", "fabrication_module", "assembly_module", "group")
NUMBER_KEYS = ("beam_number", "number", "sequence", "fabrication_number", "element_number", "index")
GENERIC_BEAM_NAMES = ("beam", "beams", "timberbeam", "element")


def normalize_output_path(value):
    value = str(value).strip().strip("\"'")
    if value.lower() == "webdata":
        return "web_data"
    return value


def parent_dirs(path):
    path = os.path.abspath(path)
    if os.path.isfile(path):
        path = os.path.dirname(path)

    while path:
        yield path
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent


def is_repo_root(path):
    return os.path.isdir(os.path.join(path, "web_app")) and (
        os.path.isdir(os.path.join(path, "web_data")) or os.path.isdir(os.path.join(path, ".git"))
    )


def find_repo_root_from(path):
    if not path:
        return None
    for candidate in parent_dirs(path):
        if is_repo_root(candidate):
            return candidate
    return None


def rhino_document_folder():
    try:
        import Rhino

        doc_path = Rhino.RhinoDoc.ActiveDoc.Path
        if doc_path:
            return os.path.dirname(doc_path)
    except Exception:
        pass
    return None


def script_folder():
    filename = globals().get("__file__")
    if filename:
        return os.path.dirname(os.path.abspath(filename))
    return None


def resolve_output_dir(path_value, repo_path_value=None):
    """Resolve GH-friendly output paths.

    In Grasshopper, ``os.path.abspath("web_data")`` can resolve to ``/web_data``
    if Rhino's working directory is root. Prefer the explicit repo path, then
    the Rhino document location, then the script location/current folder.
    """

    requested = normalize_output_path(path_value)

    if os.path.isabs(requested):
        return os.path.abspath(requested)

    repo_candidates = [
        repo_path_value,
        rhino_document_folder(),
        script_folder(),
        os.getcwd(),
    ]

    for candidate in repo_candidates:
        repo_root = find_repo_root_from(candidate)
        if repo_root:
            return os.path.abspath(os.path.join(repo_root, requested))

    return os.path.abspath(requested)


def rounded(value, digits=4):
    return round(float(value), digits)


def clean_id(value):
    value = str(value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[^A-Za-z0-9_-]", "", value)
    return value.lower()


def parse_module_sizes(value):
    sizes = []
    for item in str(value).split(","):
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


def is_generic_beam_name(value):
    return clean_id(value).lower() in GENERIC_BEAM_NAMES


def beam_mapping(beam):
    mapping = {}

    attributes = getattr(beam, "attributes", None) or {}
    if isinstance(attributes, dict):
        mapping.update(attributes)

    for key in NAME_KEYS + MODULE_KEYS + NUMBER_KEYS:
        if hasattr(beam, key):
            mapping[key] = getattr(beam, key)

    return mapping


def get_beam_identity(index, beam, module_sizes):
    """Return ``(beam_id, module, display_name)``.

    Group C naming should be added here only. Current logic checks beam
    attributes first, then falls back to sequential A1, A2, ...
    """

    lookup = beam_mapping(beam)
    explicit_name = first_value(lookup, NAME_KEYS)
    module = first_value(lookup, MODULE_KEYS)
    number = first_value(lookup, NUMBER_KEYS)

    if explicit_name and not is_generic_beam_name(explicit_name):
        beam_id = clean_id(explicit_name)
        display_name = str(explicit_name).strip().upper()
        module = str(module or display_name[:1] or "X").upper()
        return beam_id, module, display_name

    if module and number:
        module = str(module).strip().upper()
        display_name = "{}{}".format(module, number)
        return clean_id(display_name), module, display_name

    return sequential_identity(index, module_sizes)


def get_unique_beam_identity(index, beam, module_sizes, used_beam_ids):
    beam_id, module, display_name = get_beam_identity(index, beam, module_sizes)

    if beam_id and beam_id not in used_beam_ids:
        used_beam_ids.add(beam_id)
        return beam_id, module, display_name

    beam_id, module, display_name = sequential_identity(index, module_sizes)
    original_beam_id = beam_id
    suffix = 2
    while beam_id in used_beam_ids:
        beam_id = "{}_{}".format(original_beam_id, suffix)
        display_name = "{} {}".format(display_name, suffix)
        suffix += 1

    used_beam_ids.add(beam_id)
    return beam_id, module, display_name


def vector_to_list(vector):
    return [float(vector[0]), float(vector[1]), float(vector[2])]


def point_to_list(point):
    return [float(point[0]), float(point[1]), float(point[2])]


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


def frame_data(beam):
    frame = beam.frame
    x_axis = vector_to_list(frame.xaxis)
    y_axis = vector_to_list(frame.yaxis)
    z_axis = vector_to_list(getattr(frame, "zaxis", None) or vector_cross(x_axis, y_axis))
    return {
        "origin": point_to_list(frame.point),
        "x_axis": vector_normalize(x_axis),
        "y_axis": vector_normalize(y_axis),
        "z_axis": vector_normalize(z_axis),
    }


def get_centerline(beam, frame, length):
    centerline = getattr(beam, "centerline", None)
    if centerline:
        try:
            return point_to_list(centerline.start), point_to_list(centerline.end)
        except Exception:
            pass

    start = vector_sub(frame["origin"], vector_scale(frame["x_axis"], length / 2.0))
    end = vector_add(frame["origin"], vector_scale(frame["x_axis"], length / 2.0))
    return start, end


def triangulate_face(face):
    if len(face) < 3:
        return []
    if len(face) == 3:
        return [face]
    return [(face[0], face[index], face[index + 1]) for index in range(1, len(face) - 1)]


def facet_normal(a, b, c):
    return vector_normalize(vector_cross(vector_sub(b, a), vector_sub(c, a)))


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


def write_box_ascii_stl(path, name, frame, length, width, height):
    vertices = beam_box_vertices(frame, length, width, height)
    faces = [
        (0, 2, 3, 1),
        (4, 5, 7, 6),
        (0, 1, 5, 4),
        (2, 6, 7, 3),
        (0, 4, 6, 2),
        (1, 3, 7, 5),
    ]
    write_mesh_ascii_stl(path, name, vertices, faces)


def object_to_xyz(value):
    """Return XYZ coordinates from lists, COMPAS points, Rhino points/vertices."""

    if value is None:
        return None

    if hasattr(value, "Location"):
        return object_to_xyz(value.Location)

    if hasattr(value, "Point"):
        return object_to_xyz(value.Point)

    if hasattr(value, "point"):
        point = value.point
        if callable(point):
            point = point()
        return object_to_xyz(point)

    if all(hasattr(value, attr) for attr in ("X", "Y", "Z")):
        return [float(value.X), float(value.Y), float(value.Z)]

    if all(hasattr(value, attr) for attr in ("x", "y", "z")):
        return [float(value.x), float(value.y), float(value.z)]

    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except Exception:
        pass

    try:
        coords = list(value)
        if len(coords) >= 3:
            return [float(coords[0]), float(coords[1]), float(coords[2])]
    except Exception:
        pass

    return None


def face_to_indices(face):
    if isinstance(face, (list, tuple)):
        return [int(index) for index in face]

    if all(hasattr(face, attr) for attr in ("A", "B", "C", "D")):
        indices = [int(face.A), int(face.B), int(face.C)]
        if int(face.D) != int(face.C):
            indices.append(int(face.D))
        return indices

    if all(hasattr(face, attr) for attr in ("a", "b", "c")):
        indices = [int(face.a), int(face.b), int(face.c)]
        if hasattr(face, "d") and int(face.d) != int(face.c):
            indices.append(int(face.d))
        return indices

    try:
        return [int(index) for index in list(face)]
    except Exception:
        return None


def rhino_geometry_to_vertices_and_faces(geometry):
    """Mesh native Rhino Breps/Meshes when the component runs inside Rhino."""

    try:
        import Rhino
    except Exception:
        return None

    native = getattr(geometry, "native_brep", None) or getattr(geometry, "native", None) or geometry

    meshes = []
    if isinstance(native, Rhino.Geometry.Mesh):
        meshes = [native]
    elif isinstance(native, Rhino.Geometry.Brep):
        meshing_parameters = Rhino.Geometry.MeshingParameters.Default
        meshes = list(Rhino.Geometry.Mesh.CreateFromBrep(native, meshing_parameters) or [])
    else:
        return None

    combined_vertices = []
    combined_faces = []

    for mesh in meshes:
        mesh.Faces.ConvertQuadsToTriangles()
        mesh.Normals.ComputeNormals()
        mesh.Compact()

        offset = len(combined_vertices)
        for vertex in mesh.Vertices:
            combined_vertices.append([float(vertex.X), float(vertex.Y), float(vertex.Z)])

        for face in mesh.Faces:
            combined_faces.append([offset + int(face.A), offset + int(face.B), offset + int(face.C)])

    if not combined_vertices or not combined_faces:
        return None

    return combined_vertices, combined_faces


def geometry_to_vertices_and_faces(geometry):
    if geometry is None:
        return None

    candidates = list(geometry) if isinstance(geometry, (list, tuple)) else [geometry]
    combined_vertices = []
    combined_faces = []

    for candidate in candidates:
        if candidate is None:
            continue

        rhino_mesh_data = rhino_geometry_to_vertices_and_faces(candidate)
        if rhino_mesh_data:
            vertices, faces = rhino_mesh_data
            offset = len(combined_vertices)
            combined_vertices.extend(vertices)
            combined_faces.extend([[index + offset for index in face] for face in faces])
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
        clean_vertices = [object_to_xyz(vertex) for vertex in vertices]
        clean_faces = [face_to_indices(face) for face in faces]

        if not all(clean_vertices) or not all(clean_faces):
            continue

        combined_vertices.extend(clean_vertices)
        combined_faces.extend([[int(index) + offset for index in face] for face in clean_faces])

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
            if hasattr(element, "frame"):
                yield element


def iter_model_joints(model):
    joints = getattr(model, "joints", None)
    if joints is not None:
        for joint in joints:
            yield joint
        return

    interactions = getattr(model, "interactions", None)
    if interactions is not None:
        for joint in interactions:
            yield joint


def joint_kind(name):
    lower = (name or "").lower()
    if "xlap" in lower:
        return "xlap"
    if "tbutt" in lower:
        return "tbutt"
    if "lmiter" in lower:
        return "lmiter"
    return "other"


def joint_location(joint):
    location = getattr(joint, "location", None)
    if location is None:
        return None
    try:
        return point_to_list(location)
    except Exception:
        return None


def joint_element_guids(joint):
    guids = getattr(joint, "element_guids", None)
    if guids:
        return [str(guid) for guid in guids]

    elements = getattr(joint, "elements", None)
    if elements:
        return [str(getattr(element, "guid", "")) for element in elements if getattr(element, "guid", None)]

    result = []
    for attr in ("beam_a", "beam_b", "main_beam", "cross_beam", "element_a", "element_b"):
        element = getattr(joint, attr, None)
        guid = getattr(element, "guid", None)
        if guid:
            result.append(str(guid))
    return result


def collect_joints(model, guid_to_beam_id):
    joints_by_beam = defaultdict(list)
    connected = defaultdict(set)

    for index, joint in enumerate(iter_model_joints(model), start=1):
        beam_ids = [guid_to_beam_id[guid] for guid in joint_element_guids(joint) if guid in guid_to_beam_id]
        if len(beam_ids) < 2:
            continue

        name = getattr(joint, "name", None) or type(joint).__name__
        kind = joint_kind(name)
        detail = {
            "id": str(index),
            "guid": str(getattr(joint, "guid", "")),
            "type": name,
            "kind": kind,
            "connected_beams": beam_ids,
            "location": [rounded(v) for v in joint_location(joint)] if joint_location(joint) else None,
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


def export_model_to_web_data(model, output_dir, base_url, density, module_sizes, do_process_joinery=True, do_clean=True):
    if do_process_joinery and hasattr(model, "process_joinery"):
        model.process_joinery()

    if do_clean and os.path.isdir(output_dir):
        shutil.rmtree(output_dir)

    beams_dir = os.path.join(output_dir, "beams")
    if not os.path.isdir(beams_dir):
        os.makedirs(beams_dir)

    beams = list(iter_model_beams(model))
    beam_records = []
    guid_to_beam_id = {}
    errors = []
    used_beam_ids = set()

    for index, beam in enumerate(beams):
        beam_id, module, display_name = get_unique_beam_identity(index, beam, module_sizes, used_beam_ids)
        guid_to_beam_id[str(getattr(beam, "guid", index))] = beam_id

        frame = frame_data(beam)
        length = float(getattr(beam, "length"))
        width = float(getattr(beam, "width"))
        height = float(getattr(beam, "height"))
        centerline_start, centerline_end = get_centerline(beam, frame, length)
        volume_m3 = length * width * height

        mesh_data = None
        try:
            mesh_data = geometry_to_vertices_and_faces(beam.geometry)
        except Exception as error:
            errors.append("{} geometry: {!r}".format(display_name, error))

        beam_records.append({
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
            "mesh_data": mesh_data,
            "processing": list(getattr(beam, "features", None) or []),
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

    joints_by_beam, connected = collect_joints(model, guid_to_beam_id)

    stl_count = 0
    box_fallback_count = 0

    for beam in beam_records:
        beam_id = beam["beam_id"]
        beam_dir = os.path.join(beams_dir, beam_id)
        if not os.path.isdir(beam_dir):
            os.makedirs(beam_dir)

        stl_path = os.path.join(beam_dir, "{}.stl".format(beam_id))
        json_path = os.path.join(beam_dir, "{}.json".format(beam_id))

        if beam["mesh_data"]:
            vertices, faces = beam["mesh_data"]
            write_mesh_ascii_stl(stl_path, beam_id, vertices, faces)
            stl_count += 1
        else:
            write_box_ascii_stl(stl_path, beam_id, beam["frame"], beam["length"], beam["width"], beam["height"])
            box_fallback_count += 1

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
            "processing": [],
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

    with open(os.path.join(output_dir, "structure.json"), "w") as fp:
        json.dump(structure, fp, indent=2)

    return len(beam_records), stl_count, box_fallback_count, errors


base_url = vars().get("base_url") or DEFAULT_BASE_URL
density = float(vars().get("density") or DEFAULT_DENSITY_KG_M3)
process_joinery = True if vars().get("process_joinery") is None else bool(vars().get("process_joinery"))
clean = True if vars().get("clean") is None else bool(vars().get("clean"))
module_sizes = parse_module_sizes(vars().get("module_sizes") or DEFAULT_MODULE_SIZES)
repo_path = vars().get("repo_path")

export_message = "Set run=True and provide model + output folder path."
exported_count = 0
stl_count = 0
box_fallback_count = 0
errors = []
output_dir = ""

if run and model and path:
    try:
        output_dir = resolve_output_dir(path, repo_path)
        exported_count, stl_count, box_fallback_count, errors = export_model_to_web_data(
            model=model,
            output_dir=output_dir,
            base_url=base_url,
            density=density,
            module_sizes=module_sizes,
            do_process_joinery=process_joinery,
            do_clean=clean,
        )
        export_message = "Exported {} beams to {}".format(exported_count, output_dir)
    except Exception as error:
        export_message = "Web data export failed for {}: {!r}".format(output_dir or path, error)
        errors = [export_message]

print(export_message)
print("Processed STL: {}, box fallbacks: {}".format(stl_count, box_fallback_count))
for error in errors[:20]:
    print(error)
if len(errors) > 20:
    print("{} more errors omitted.".format(len(errors) - 20))
