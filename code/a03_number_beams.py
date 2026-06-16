import os
import sys
import re
import json
import shutil
import math
from pathlib import Path
from collections import defaultdict, deque
import Rhino.Geometry as rg
from compas.datastructures import Graph

# =========================
# COSTANTI GLOBALI
# =========================
DEFAULT_BASE_URL = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data"
DEFAULT_DENSITY_KG_M3 = 500.0
DEFAULT_MODULE_SIZES = "A:36,B:31,C:30,D:27,E:27,F:31,G:6,H:3"

NAME_KEYS = ("beam_id", "beam ID", "beam_name", "name", "label", "mark")
MODULE_KEYS = ("module", "module_id", "module_name", "fabrication_module", "assembly_module", "group")
NUMBER_KEYS = ("beam_number", "number", "sequence", "fabrication_number", "element_number", "index")

# Key Beams aggiornati basati sulla nomenclatura finale dell'apparizione
KEY_BEAMS_LIST = ["B10", "B11", "C10", "C19", "C20", "C23", "E36", "G18", "A21", "C13"]

# Beams estratti per modulo G (nomi pre-spostamento)
KEY_BEAMS_MODULE_G = ["A10", "C27", "C28", "C29", "D17", "D18"]

# Beams estratti per modulo H (nomi pre-spostamento)
KEY_BEAMS_MODULE_H = ["C25", "C26", "D22"]

# =========================
# UTILITY FUNCTIONS
# =========================

def rounded(value, digits=4):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [rounded(v, digits) for v in value]
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

def set_beam_partitioning_attributes(beam, module, number, beam_id=None, display_name=None):
    attributes = getattr(beam, "attributes", None)
    if attributes is None:
        attributes = {}
        setattr(beam, "attributes", attributes)
    if not isinstance(attributes, dict):
        attributes = dict(attributes)
        setattr(beam, "attributes", attributes)

    module_value = str(module).strip().upper() if module is not None else None
    number_value = int(number) if number is not None and str(number).strip().lstrip("-").isdigit() else number

    if module_value is not None:
        attributes["module"] = module_value
    if number_value is not None:
        attributes["number"] = number_value
        attributes["beam_number"] = number_value
    if beam_id is not None:
        attributes["beam_id"] = str(beam_id)
    if display_name is not None:
        attributes["display_name"] = str(display_name)

    return attributes

def get_beam_identity(index, element_guid, beam_data, module_sizes):
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

# =========================
# VECTOR & FRAME OPERATIONS
# =========================

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

def vector_dot(a, b):
    return sum(a[i] * b[i] for i in range(3))

def vector_length(v):
    return math.sqrt(sum(c * c for c in v))

def vector_normalize(v):
    length = vector_length(v)
    if not length:
        return [0.0, 0.0, 0.0]
    return [c / length for c in v]

def xyz_to_list(value):
    if all(hasattr(value, attr) for attr in ("x", "y", "z")):
        return [float(value.x), float(value.y), float(value.z)]
    if fastener_key := all(hasattr(value, attr) for attr in ("X", "Y", "Z")):
        return [float(value.X), float(value.Y), float(value.Z)]
    return [float(value[0]), float(value[1]), float(value[2])]

def beam_frame_data(beam):
    frame = beam.frame
    blank = getattr(beam, "blank", None)
    blank_frame = getattr(blank, "frame", None) if blank is not None else None
    origin = getattr(blank_frame, "point", None) or frame.point
    x_axis = xyz_to_list(frame.xaxis)
    y_axis = xyz_to_list(frame.yaxis)
    z_axis = xyz_to_list(getattr(frame, "zaxis", None) or vector_cross(x_axis, y_axis))
    return {
        "origin": xyz_to_list(origin),
        "x_axis": vector_normalize(x_axis),
        "y_axis": vector_normalize(y_axis),
        "z_axis": vector_normalize(z_axis),
    }

def frame_from_data(frame_data):
    data = frame_data.get("data", frame_data)
    origin = data.get("point") or data.get("origin")
    x_axis = data.get("xaxis") or data.get("x_axis")
    y_axis = data.get("yaxis") or data.get("y_axis")
    if x_axis and y_axis:
        z_axis = data.get("zaxis") or data.get("z_axis") or vector_cross(x_axis, y_axis)
    else:
        z_axis = data.get("zaxis") or data.get("z_axis") or [0, 0, 1]
    return {
        "origin": [float(v) for v in origin],
        "x_axis": vector_normalize([float(v) for v in x_axis]),
        "y_axis": vector_normalize([float(v) for v in y_axis]),
        "z_axis": vector_normalize([float(v) for v in z_axis]),
    }

def blank_frame_from_beam_data(blank_data):
    blank = blank_data.get("blank") or {}
    if isinstance(blank, dict):
        blank_data = blank.get("data", blank)
        frame = blank_data.get("frame")
        if frame:
            return frame_from_data(frame)
    return None

# =========================
# BEAM GEOMETRY OPERATIONS
# =========================

def get_line_start(line):
    if hasattr(line, "start"):
        return line.start
    if hasattr(line, "start_point"):
        return line.start_point
    if hasattr(line, "point_at"):
        return line.point_at(0.0)
    return line[0]

def get_line_end(line):
    if hasattr(line, "end"):
        return line.end
    if hasattr(line, "end_point"):
        return line.end_point
    if hasattr(line, "point_at"):
        return line.point_at(1.0)
    return line[1]

def get_beam_section(beam):
    for w_attr in ['width', 'w', 'b', 'breadth']:
        for h_attr in ['height', 'h', 'd', 'depth']:
            try:
                w = getattr(beam, w_attr)
                h = getattr(beam, h_attr)
                if w and h:
                    return float(w), float(h)
            except:
                continue
    try:
        sec = beam.section
        for w_attr in ['width', 'w', 'b', 'breadth']:
            for h_attr in ['height', 'h', 'd', 'depth']:
                try:
                    w = getattr(sec, w_attr)
                    h = getattr(sec, h_attr)
                    if w and h:
                        return float(w), float(h)
                except:
                    continue
    except:
        pass
    for container in ['blank', 'shape', 'profile']:
        try:
            obj = getattr(beam, container)
            w = getattr(obj, 'xsize', None) or getattr(obj, 'width', None)
            h = getattr(obj, 'ysize', None) or getattr(obj, 'height', None)
            if w and h:
                return float(w), float(h)
        except:
            continue
    return None, None

def get_orientation_string(w, h):
    if w is None or h is None:
        return "?x?cm"
    w_cm = round(w * 100) if w < 1 else round(w)
    h_cm = round(h * 100) if h < 1 else round(h)
    return "{}x{}cm".format(int(w_cm), int(h_cm))

def get_beam_weight(beam, length, density=500):
    w, h = get_beam_section(beam)
    if w is None or h is None:
        return 0.0
    w_m = w if w < 1 else w / 100.0
    h_m = h if h < 1 else h / 100.0
    return w_m * h_m * length * density

def get_blank_length(beam, fallback=None):
    def positive_number(value):
        try:
            number = float(value)
            return number if number > 0 else None
        except:
            return None

    for attr in ("blank_length", "blank_len"):
        number = positive_number(getattr(beam, attr, None))
        if number:
            return number

    attributes = getattr(beam, "attributes", None)
    if isinstance(attributes, dict):
        for key in ("blank_length", "blank_len"):
            number = positive_number(attributes.get(key))
            if number:
                return number

    blank = getattr(beam, "blank", None)
    for attr in ("length", "xsize", "x_size", "size_x"):
        number = positive_number(getattr(blank, attr, None))
        if number:
            return number

    blank_attributes = getattr(blank, "attributes", None)
    if isinstance(blank_attributes, dict):
        for key in ("length", "blank_length", "xsize", "x_size", "size_x"):
            number = positive_number(blank_attributes.get(key))
            if number:
                return number

    try:
        mesh_data = geometry_to_vertices_and_faces_any(blank)
        if mesh_data:
            vertices, _ = mesh_data
            blank_frame = getattr(blank, "frame", None)
            frame = blank_frame or getattr(beam, "frame", None)
            axis = xyz_to_list(getattr(frame, "xaxis", None)) if frame else None
            if axis:
                axis = vector_normalize(axis)
                projections = [vector_dot(vertex, axis) for vertex in vertices]
                number = positive_number(max(projections) - min(projections))
                if number:
                    return number
    except:
        pass

    return fallback

def get_beam_local_frame(beam):
    try:
        frame = beam_frame_data(beam)
        return {
            "origin": [round(v, 4) for v in frame["origin"]],
            "x_axis": [round(v, 4) for v in frame["x_axis"]],
            "y_axis": [round(v, 4) for v in frame["y_axis"]],
            "z_axis": [round(v, 4) for v in frame["z_axis"]]
        }
    except:
        return None

# =========================
# STL EXPORT FUNCTIONS
# =========================

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
                point = origin[:]
                point = vector_add(point, vector_scale(axes[0], sx))
                point = vector_add(point, vector_scale(axes[1], sy))
                point = vector_add(point, vector_scale(axes[2], sz))
                vertices.append(point)
    return vertices

def geometry_to_vertices_and_faces(geometry):
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
        combined_vertices.extend([[float(c) for c in v] for v in vertices])
        combined_faces.extend([[int(i) + offset for i in f] for f in faces])
    if not combined_vertices or not combined_faces:
        return None
    return combined_vertices, combined_faces

def write_rhino_geometry_ascii_stl(path, name, geometry):
    native = (
        getattr(geometry, "native_brep", None)
        or getattr(geometry, "native_mesh", None)
        or getattr(geometry, "native", None)
        or geometry
    )
    meshes = []
    if isinstance(native, rg.Mesh):
        meshes = [native]
    elif isinstance(native, rg.Brep):
        meshes = list(rg.Mesh.CreateFromBrep(native, rg.MeshingParameters.Default) or [])
    else:
        return False

    joined = rg.Mesh()
    for mesh in meshes:
        joined.Append(mesh)

    vertices = [[float(v.X), float(v.Y), float(v.Z)] for v in joined.Vertices]
    faces = []
    for face in joined.Faces:
        faces.append([int(face.A), int(face.B), int(face.C)])
        if not face.IsTriangle:
            faces.append([int(face.A), int(face.C), int(face.D)])
    write_mesh_ascii_stl(path, name, vertices, faces)
    return True

def rhino_geometry_to_vertices_and_faces(geometry):
    native = (
        getattr(geometry, "native_brep", None)
        or getattr(geometry, "native_mesh", None)
        or getattr(geometry, "native", None)
        or geometry
    )
    meshes = []
    if isinstance(native, rg.Mesh):
        meshes = [native]
    elif isinstance(native, rg.Brep):
        meshes = list(rg.Mesh.CreateFromBrep(native, rg.MeshingParameters.Default) or [])
    else:
        return None

    joined = rg.Mesh()
    for mesh in meshes:
        joined.Append(mesh)

    vertices = [[float(v.X), float(v.Y), float(v.Z)] for v in joined.Vertices]
    faces = []
    for face in joined.Faces:
        faces.append([int(face.A), int(face.B), int(face.C)])
        if not face.IsTriangle:
            faces.append([int(face.A), int(face.C), int(face.D)])
    if not vertices or not faces:
        return None
    return vertices, faces

def geometry_to_vertices_and_faces_any(geometry):
    if geometry is None:
        return None
    rhino_data = rhino_geometry_to_vertices_and_faces(geometry)
    if rhino_data:
        return rhino_data
    return geometry_to_vertices_and_faces(geometry)

def write_geometry_ascii_stl(path, name, geometry):
    if geometry is None:
        return False
    if write_rhino_geometry_ascii_stl(path, name, geometry):
        return True
    mesh_data = geometry_to_vertices_and_faces(geometry)
    if not mesh_data:
        return False
    vertices, faces = mesh_data
    write_mesh_ascii_stl(path, name, vertices, faces)
    return True

def safe_number(value):
    try:
        return float(value)
    except:
        return None

def point_list(value):
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("data", value)
        if all(key in value for key in ("x", "y", "z")):
            return [float(value["x"]), float(value["y"]), float(value["z"])]
        if all(key in value for key in ("X", "Y", "Z")):
            return [float(value["X"]), float(value["Y"]), float(value["Z"])]
    try:
        return xyz_to_list(value)
    except:
        return None

def line_points(value):
    if value is None:
        return None
    if isinstance(value, dict):
        data = value.get("data", value)
        start = data.get("start") or data.get("from") or data.get("start_point")
        end = data.get("end") or data.get("to") or data.get("end_point")
        if start is not None and end is not None:
            start_pt = point_list(start)
            end_pt = point_list(end)
            if start_pt and end_pt:
                return start_pt, end_pt
        if "point" in data and ("direction" in data or "vector" in data):
            origin = point_list(data.get("point"))
            direction = point_list(data.get("direction") or data.get("vector"))
            length = safe_number(data.get("length") or data.get("depth"))
            if origin and direction and length:
                direction = vector_normalize(direction)
                return origin, vector_add(origin, vector_scale(direction, length))
    for start_name, end_name in (("start", "end"), ("from_point", "to_point"), ("start_point", "end_point")):
        start = getattr(value, start_name, None)
        end = getattr(value, end_name, None)
        start_pt = point_list(start)
        end_pt = point_list(end)
        if start_pt and end_pt:
            return start_pt, end_pt
    return None

def primitive_data(value, depth=0):
    if depth > 3:
        return str(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [primitive_data(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): primitive_data(val, depth + 1) for key, val in value.items() if not str(key).startswith("_")}
    pts = line_points(value)
    if pts:
        return {"start": [rounded(v) for v in pts[0]], "end": [rounded(v) for v in pts[1]]}
    point = point_list(value)
    if point:
        return [rounded(v) for v in point]
    return str(value)

def feature_raw_data(feature):
    for method_name in ("to_data", "__data__"):
        method = getattr(feature, method_name, None)
        if callable(method):
            try:
                return method()
            except:
                pass
    data = getattr(feature, "data", None)
    if isinstance(data, dict):
        return data
    data = {}
    for key in dir(feature):
        if key.startswith("_"):
            continue
        try:
            value = getattr(feature, key)
        except:
            continue
        if callable(value):
            continue
        if isinstance(value, (str, bool, int, float, list, tuple, dict)) or point_list(value) or line_points(value):
            data[key] = value
    return data

def feature_type_name(feature):
    return type(feature).__name__

def is_joinery_feature(feature):
    name = feature_type_name(feature).lower()
    joinery_tokens = ("lap", "miter", "tbutt", "butt", "joint", "cut", "tenon", "birdsmouth", "jackrafter")
    non_joinery_tokens = ("drill", "screw", "hole", "fastener")
    if any(token in name for token in non_joinery_tokens):
        return False
    return any(token in name for token in joinery_tokens)

def feature_number(feature, raw, keys):
    for key in keys:
        if isinstance(raw, dict) and key in raw:
            value = safe_number(raw.get(key))
            if value is not None:
                return value
        value = safe_number(getattr(feature, key, None))
        if value is not None:
            return value
    return None

def feature_line(feature, raw):
    for key in ("line", "drilling_line", "screw_line", "toolpath", "axis", "centerline"):
        value = raw.get(key) if isinstance(raw, dict) else None
        pts = line_points(value)
        if pts:
            return pts
        pts = line_points(getattr(feature, key, None))
        if pts:
            return pts

    point = None
    direction = None
    for key in ("point", "origin", "start", "start_point"):
        point = point_list(raw.get(key)) if isinstance(raw, dict) else None
        if point:
            break
        point = point_list(getattr(feature, key, None))
        if point:
            break
    for key in ("direction", "vector", "axis_vector"):
        direction = point_list(raw.get(key)) if isinstance(raw, dict) else None
        if direction:
            break
        direction = point_list(getattr(feature, key, None))
        if direction:
            break
    length = feature_number(feature, raw, ("length", "depth", "screw_length", "drilling_depth"))
    if point and direction and length:
        direction = vector_normalize(direction)
        return point, vector_add(point, vector_scale(direction, length))
    return None

def cylinder_mesh_from_line(start, end, radius, segments=16):
    axis = vector_sub(end, start)
    length = vector_length(axis)
    if length <= 1e-9 or radius <= 0:
        return None
    x_axis = vector_normalize(axis)
    ref = [0.0, 0.0, 1.0]
    if abs(sum(x_axis[i] * ref[i] for i in range(3))) > 0.92:
        ref = [0.0, 1.0, 0.0]
    y_axis = vector_normalize(vector_cross(x_axis, ref))
    z_axis = vector_normalize(vector_cross(x_axis, y_axis))

    vertices = []
    for center in (start, end):
        for index in range(segments):
            angle = 2.0 * math.pi * float(index) / float(segments)
            offset = vector_add(
                vector_scale(y_axis, math.cos(angle) * radius),
                vector_scale(z_axis, math.sin(angle) * radius)
            )
            vertices.append(vector_add(center, offset))
    vertices.append(start)
    vertices.append(end)
    start_center = len(vertices) - 2
    end_center = len(vertices) - 1

    faces = []
    for index in range(segments):
        nxt = (index + 1) % segments
        faces.append([index, nxt, segments + nxt, segments + index])
        faces.append([start_center, nxt, index])
        faces.append([end_center, segments + index, segments + nxt])
    return vertices, faces

def feature_geometry_data(feature):
    for key in ("geometry", "mesh", "brep", "volume", "shape", "solid"):
        try:
            value = getattr(feature, key, None)
        except:
            value = None
        mesh_data = geometry_to_vertices_and_faces_any(value)
        if mesh_data:
            return mesh_data
    return None

def collect_non_joinery_features(beam):
    records = []
    combined_vertices = []
    combined_faces = []

    def add_record_mesh(record, pts, diameter):
        mesh_data = None
        if pts:
            radius = (diameter or 0.006) / 2.0
            mesh_data = cylinder_mesh_from_line(pts[0], pts[1], radius)
        if mesh_data:
            vertices, faces = mesh_data
            offset = len(combined_vertices)
            combined_vertices.extend(vertices)
            combined_faces.extend([[int(i) + offset for i in face] for face in faces])
            record["has_stl_geometry"] = True
        else:
            record["has_stl_geometry"] = False
        records.append(record)

    for index, raw_record in enumerate((getattr(beam, "attributes", {}) or {}).get("web_features", []) or [], start=1):
        raw = raw_record if isinstance(raw_record, dict) else {}
        pts = line_points(raw) or feature_line(raw, raw)
        diameter = feature_number(raw, raw, ("diameter", "diameter_m", "screw_diameter"))
        length = feature_number(raw, raw, ("length", "length_m", "depth", "screw_length", "drilling_depth"))
        record = {
            "id": "web-{}".format(index),
            "type": raw.get("type") or "Feature",
            "data": primitive_data(raw),
        }
        if pts:
            start, end = pts
            record["start"] = [rounded(v) for v in start]
            record["end"] = [rounded(v) for v in end]
            record["line_length_m"] = rounded(vector_length(vector_sub(end, start)))
            if length is None:
                length = record["line_length_m"]
        if diameter is not None:
            record["diameter_m"] = rounded(diameter)
        if length is not None:
            record["length_m"] = rounded(length)
            record["length_mm"] = rounded(length * 1000.0, 1)
        if raw.get("assigned_length_mm") is not None:
            record["assigned_length_mm"] = raw.get("assigned_length_mm")
        if raw.get("joint_type"):
            record["joint_type"] = raw.get("joint_type")
        add_record_mesh(record, pts, diameter)

    for index, feature in enumerate(list(getattr(beam, "features", None) or []), start=1):
        if is_joinery_feature(feature):
            continue
        raw = feature_raw_data(feature)
        record = {
            "id": index,
            "type": feature_type_name(feature),
            "data": primitive_data(raw),
        }
        diameter = feature_number(feature, raw, ("diameter", "diameter_m", "screw_diameter"))
        length = feature_number(feature, raw, ("length", "depth", "screw_length", "drilling_depth"))
        pts = feature_line(feature, raw)
        if pts:
            start, end = pts
            record["start"] = [rounded(v) for v in start]
            record["end"] = [rounded(v) for v in end]
            record["line_length_m"] = rounded(vector_length(vector_sub(end, start)))
            if length is None:
                length = record["line_length_m"]
        if diameter is not None:
            record["diameter_m"] = rounded(diameter)
        if length is not None:
            record["length_m"] = rounded(length)
            record["length_mm"] = rounded(length * 1000.0, 1)

        mesh_data = feature_geometry_data(feature)
        if not mesh_data and pts:
            radius = (diameter or 0.006) / 2.0
            mesh_data = cylinder_mesh_from_line(pts[0], pts[1], radius)
        if mesh_data:
            vertices, faces = mesh_data
            offset = len(combined_vertices)
            combined_vertices.extend(vertices)
            combined_faces.extend([[int(i) + offset for i in face] for face in faces])
            record["has_stl_geometry"] = True
            records.append(record)
        elif not records or record.get("start") or record.get("end"):
            record["has_stl_geometry"] = False
            records.append(record)

    mesh_data = (combined_vertices, combined_faces) if combined_vertices and combined_faces else None
    return records, mesh_data

# =========================
# JOINT FUNCTIONS
# =========================

def point_on_centerline(beam, t):
    line = beam.centerline
    try:
        return line.point_at(t)
    except:
        a = get_line_start(line)
        b = get_line_end(line)
        return type(a)(
            a.x + (b.x - a.x) * t,
            a.y + (b.y - a.y) * t,
            a.z + (b.z - a.z) * t
        )

def joint_point_from_beams(ea, eb):
    best_pa, best_pb = None, None
    best_d = 1e99
    samples = 25
    for i in range(samples + 1):
        ta = float(i) / samples
        pa = point_on_centerline(ea, ta)
        for j in range(samples + 1):
            tb = float(j) / samples
            pb = point_on_centerline(eb, tb)
            d = (pa.x - pb.x)**2 + (pa.y - pb.y)**2 + (pa.z - pb.z)**2
            if d < best_d:
                best_d = d
                best_pa = pa
                best_pb = pb
    return rg.Point3d(
        (best_pa.x + best_pb.x) / 2.0,
        (best_pa.y + best_pb.y) / 2.0,
        (best_pa.z + best_pb.z) / 2.0
    )

def parameter_on_centerline(beam, point):
    best_t = 0.0
    best_d = 1e99
    samples = 50
    for i in range(samples + 1):
        t = float(i) / samples
        p = point_on_centerline(beam, t)
        d = (p.x - point.X)**2 + (p.y - point.Y)**2 + (p.z - point.Z)**2
        if d < best_d:
            best_d = d
            best_t = t
    return best_t

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

# =========================
# MAIN NUMBERING FUNCTION (GRASSHOPPER)
# =========================

def run_numbering(timber_model, Index, RunExport, OutputFolder):
    """
    Main function for Grasshopper numbering + export.

    Returns (12 outputs):
    0: debug_out
    1: info_out
    2: json_export_out
    3: A_geom_out
    4: B_geom_out
    5: C_geom_out
    6: D_geom_out
    7: E_geom_out
    8: F_geom_out
    9: G_geom_out
    10: H_geom_out
    11: timber_model
    """

    debug_out = ""
    info_out = ""
    json_export_out = "Export non avviato (RunExport è False)."
    A_geom_out, B_geom_out, C_geom_out = [], [], []
    D_geom_out, E_geom_out, F_geom_out = [], [], []
    G_geom_out, H_geom_out = [], []

    try:
        idx = int(Index)
    except:
        idx = 0

    # =========================
    # TEST RAPIDO GEOMETRIA
    # =========================
    try:
        test_beam = list(timber_model.beams)[0]
        g_obj = test_beam.geometry
        debug_out = "TIPO: {}\nATTR: {}".format(
            type(g_obj),
            [a for a in dir(g_obj) if not a.startswith('_')]
        )
    except Exception as e:
        debug_out = "ERRORE TEST GEOMETRIA: {}".format(e)

    # =========================
    # 1. COSTRUZIONE GRAFO
    # =========================
    g = Graph()

    for joint in timber_model.joints:
        ea, eb = joint.elements
        pa = ea.centerline.midpoint
        pb = eb.centerline.midpoint
        na = g.add_node(str(ea.guid), x=pa.x, y=pa.y, z=pa.z)
        nb = g.add_node(str(eb.guid), x=pb.x, y=pb.y, z=pb.z)
        g.add_edge(na, nb)

    # =========================
    # 2. DATI NODI & BOUNDING BOX
    # =========================
    pts = {n: g.node_attributes(n, ['x', 'y', 'z']) for n in g.nodes()}

    min_x = min(p[0] for p in pts.values())
    max_x = max(p[0] for p in pts.values())
    min_y = min(p[1] for p in pts.values())
    max_y = max(p[1] for p in pts.values())
    min_z = min(p[2] for p in pts.values())
    max_z = max(p[2] for p in pts.values())

    # =========================
    # 3. GRIGLIA 3x2 = 6 MODULI BASE (A-F)
    # =========================
    nx_grid = 3
    ny_grid = 2
    dx = (max_x - min_x) / nx_grid
    dy = (max_y - min_y) / ny_grid

    cells = []
    for i in range(nx_grid):
        for j in range(ny_grid):
            cx = min_x + dx * (i + 0.5)
            cy = min_y + dy * (j + 0.5)
            cells.append((cx, cy))

    # Solo A-F per la griglia spaziale iniziale
    base_labels = ["A", "B", "C", "D", "E", "F"]
    all_labels  = ["A", "B", "C", "D", "E", "F", "G", "H"]

    # =========================
    # 4. SEEDS
    # =========================
    def dist2(a, b):
        return (a[0] - b[0])**2 + (a[1] - b[1])**2

    seeds = {}
    for key, (cx, cy) in zip(base_labels, cells):
        seed = min(pts, key=lambda n: dist2(pts[n], (cx, cy)))
        seeds[key] = seed

    # =========================
    # 5. ASSEGNAZIONE SPAZIALE (solo A-F)
    # =========================
    assignment = {}
    groups = {k: [] for k in base_labels}

    for node, p in pts.items():
        best_k = None
        best_d = 1e99
        for k, seed in seeds.items():
            sx, sy, _ = pts[seed]
            d = dist2(p, (sx, sy))
            if d < best_d:
                best_d = d
                best_k = k
        assignment[node] = best_k
        groups[best_k].append(node)

    # =========================
    # 6. CRESCITA COSTRUIBILE
    # =========================
    def connected_growth(seed, group_nodes):
        group_set = set(group_nodes)
        visited = set([seed])
        order = [seed]
        frontier = [seed]

        while len(order) < len(group_set):
            best_candidate = None
            best_dist = 1e99

            for f in frontier:
                for nbr in g.neighbors(f):
                    if nbr in group_set and nbr not in visited:
                        px, py, pz = pts[f]
                        nx2, ny2, nz2 = pts[nbr]
                        d = (px-nx2)**2 + (py-ny2)**2 + (pz-nz2)**2
                        if d < best_dist:
                            best_dist = d
                            best_candidate = nbr

            if best_candidate is None:
                remaining = list(group_set - visited)
                for r in remaining:
                    for v in visited:
                        px, py, pz = pts[v]
                        rx, ry, rz = pts[r]
                        d = (px-rx)**2 + (py-ry)**2 + (pz-rz)**2
                        if d < best_dist:
                            best_dist = d
                            best_candidate = r

            visited.add(best_candidate)
            order.append(best_candidate)
            frontier.append(best_candidate)

        return order

    ordered_by_module = {k: [] for k in all_labels}
    for k in base_labels:
        ordered_by_module[k] = connected_growth(seeds[k], groups[k])

    def _insert_by_proximity(target_list, node_to_move):
        if not target_list:
            target_list.append(node_to_move)
            return
        best_idx = 0
        min_d2 = 1e99
        px, py, pz = pts[node_to_move]
        for idx_n, existing_node in enumerate(target_list):
            ex, ey, ez = pts[existing_node]
            d2 = (px-ex)**2 + (py-ey)**2 + (pz-ez)**2
            if d2 < min_d2:
                min_d2 = d2
                best_idx = idx_n
        target_list.insert(best_idx + 1, node_to_move)

    # =========================================================================
    # POST-PROCESSING FASE 1: APPLICAZIONE SPOSTAMENTI STORICI (Nomenclatura Corrente)
    # =========================================================================
    guid_by_pure_grid_name = {}
    for k in base_labels:
        for i, node in enumerate(ordered_by_module[k]):
            pure_name = "{}{}".format(k, i + 1)
            guid_by_pure_grid_name[pure_name] = node

    historical_moves = {
        "B19": "D", "B22": "D", "B23": "D", "B24": "D",
        "A28": "C", "A29": "C", "E36": "C"
    }

    for pure_name, target_mod in historical_moves.items():
        if pure_name in guid_by_pure_grid_name:
            node_to_move = guid_by_pure_grid_name[pure_name]
            for mod_k in base_labels:
                if node_to_move in ordered_by_module[mod_k]:
                    ordered_by_module[mod_k].remove(node_to_move)
                    break

    for pure_name, target_mod in historical_moves.items():
        if pure_name in guid_by_pure_grid_name:
            node_to_move = guid_by_pure_grid_name[pure_name]
            _insert_by_proximity(ordered_by_module[target_mod], node_to_move)
            assignment[node_to_move] = target_mod

    # =========================================================================
    # POST-PROCESSING FASE 2: MAPPATURA DALLA NOMENCLATURA MODIFICATA CORRENTE
    # =========================================================================
    guid_by_modified_name = {}
    node_initial_name = {}

    for k in base_labels:
        for i, node in enumerate(ordered_by_module[k]):
            current_modified_name = "{}{}".format(k, i + 1)
            guid_by_modified_name[current_modified_name] = node
            node_initial_name[node] = current_modified_name

    # =========================================================================
    # POST-PROCESSING FASE 3: NUOVI MODULI G, H E SPOSTAMENTI FINALI RICHIESTI
    # =========================================================================
    new_manual_moves_ordered = [
        ("A10",  "G"),
        ("C27",  "G"),
        ("C28",  "G"),
        ("C29",  "G"),
        ("D17",  "G"),
        ("D18",  "G"),
        ("C25",  "H"),
        ("C26",  "H"),
        ("D22",  "H"),
        ("D19",  "B"),
        ("D20",  "B"),
        ("D21",  "B"),
        ("F23",  "E"),
    ]

    for interim_name, target_mod in new_manual_moves_ordered:
        if interim_name in guid_by_modified_name:
            node_to_move = guid_by_modified_name[interim_name]
            for mod_k in all_labels:
                if node_to_move in ordered_by_module[mod_k]:
                    ordered_by_module[mod_k].remove(node_to_move)
                    break

    for interim_name, target_mod in new_manual_moves_ordered:
        if interim_name in guid_by_modified_name:
            node_to_move = guid_by_modified_name[interim_name]
            _insert_by_proximity(ordered_by_module[target_mod], node_to_move)
            assignment[node_to_move] = target_mod

    # =========================================================================
    # POST-PROCESSING FASE 4: NUOVA NOMENCLATURA DEI MODULI CON INVERSIONI CORRETTE
    # E->B, F->A, A->D, B->C, C->H, G->F, H->G, D->E
    # =========================================================================
    module_renaming_map = {
        "F": "A",
        "E": "B",
        "B": "C",
        "A": "D",
        "D": "E",
        "G": "F",
        "H": "G",
        "C": "H"
    }

    renamed_ordered_by_module = {k: [] for k in all_labels}
    for old_mod, new_mod in module_renaming_map.items():
        renamed_ordered_by_module[new_mod] = ordered_by_module[old_mod]
    
    ordered_by_module = renamed_ordered_by_module

    for node in assignment:
        old_assignment = assignment[node]
        if old_assignment in module_renaming_map:
            assignment[node] = module_renaming_map[old_assignment]

    # =========================================================================
    # POST-PROCESSING FASE 5: STRUTTURAZIONE SECONDO I NUOVI INTERVALLI E UNIONI
    # =========================================================================
    final_ordered_by_module = {k: [] for k in all_labels}

    def get_by_indices(nodes_list, start_num, end_num):
        extracted = []
        for idx_one, node in enumerate(nodes_list, start=1):
            if start_num <= idx_one <= end_num:
                extracted.append(node)
        return extracted

    curr_A = list(ordered_by_module["A"])
    curr_B = list(ordered_by_module["B"])
    curr_C = list(ordered_by_module["C"])
    curr_D = list(ordered_by_module["D"])
    curr_E = list(ordered_by_module["E"])
    curr_F = list(ordered_by_module["F"])
    curr_G = list(ordered_by_module["G"])
    curr_H = list(ordered_by_module["H"])

    final_ordered_by_module["A"] = curr_A
    final_ordered_by_module["B"] = get_by_indices(curr_E, 11, 21)
    final_ordered_by_module["C"] = curr_C
    final_ordered_by_module["D"] = get_by_indices(curr_E, 1, 10) + get_by_indices(curr_E, 22, 26)
    final_ordered_by_module["E"] = curr_B
    final_ordered_by_module["F"] = get_by_indices(curr_H, 11, 21) + curr_G
    final_ordered_by_module["G"] = curr_D
    final_ordered_by_module["H"] = get_by_indices(curr_H, 1, 10) + get_by_indices(curr_H, 22, 29) + curr_F

    ordered_by_module = final_ordered_by_module

    # =========================================================================
    # POST-PROCESSING FASE 6: ULTIMO CAMBIAMENTO NOMENCLATURA RICHIESTO
    # A,B,C,D,E restano uguali. F -> H, H -> G, G -> F
    # =========================================================================
    final_swap_map = {
        "A": "A",
        "B": "B",
        "C": "C",
        "D": "D",
        "E": "E",
        "F": "H",
        "G": "F",
        "H": "G"
    }

    swapped_ordered_by_module = {k: [] for k in all_labels}
    for old_mod, new_mod in final_swap_map.items():
        swapped_ordered_by_module[new_mod] = ordered_by_module[old_mod]

    ordered_by_module = swapped_ordered_by_module

    for k in all_labels:
        for node in ordered_by_module[k]:
            assignment[node] = k

    # =========================
    # 7. GENERAZIONE BEAM OUTPUT
    # =========================
    geom = {k: [] for k in all_labels}
    beam_label_by_guid = {}
    is_key_beam_by_guid = {}

    for k in all_labels:
        for i, node in enumerate(ordered_by_module[k]):
            name = "{}{}".format(k, i + 1)
            beam = timber_model.get_element(node)
            set_beam_partitioning_attributes(beam, k, i + 1, beam_id=name.lower(), display_name=name)

            # CORREZIONE CRUCIALE: Il controllo del Key Beam viene eseguito basandosi 
            # sul nome dell'apparizione finale generata a schermo (es. B10, B11, C10, ecc.)
            is_key_beam_by_guid[node] = (name in KEY_BEAMS_LIST)

            rhino_geom = beam.geometry
            if hasattr(beam.geometry, "native_brep") and beam.geometry.native_brep:
                rhino_geom = beam.geometry.native_brep
            elif hasattr(beam.geometry, "native_mesh") and beam.geometry.native_mesh:
                rhino_geom = beam.geometry.native_mesh
            elif hasattr(beam.geometry, "to_rhino"):
                try:
                    rhino_geom = beam.geometry.to_rhino()
                except:
                    pass

            geom[k].append(rhino_geom)
            beam_label_by_guid[node] = name

    # =========================
    # 7B. STRUTTURA INTERNA CO-GIUNTI
    # =========================
    joint_number_by_pair = {}
    beam_joints = {node: [] for node in g.nodes()}
    joint_type_by_number = {}
    counter = 1

    for joint in timber_model.joints:
        ea, eb = joint.elements
        ga, gb = str(ea.guid), str(eb.guid)
        pair_key = tuple(sorted([ga, gb]))

        if pair_key not in joint_number_by_pair:
            joint_number = "{:02d}".format(counter)
            joint_number_by_pair[pair_key] = joint_number
            joint_type_by_number[joint_number] = type(joint).__name__
            counter += 1
        else:
            joint_number = joint_number_by_pair[pair_key]

        jp = joint_point_from_beams(ea, eb)
        beam_joints[ga].append((parameter_on_centerline(ea, jp), joint_number))
        beam_joints[gb].append((parameter_on_centerline(eb, jp), joint_number))

    # =========================
    # 8. RACCOLTA INFO BEAMS
    # =========================
    summary_by_category = {k: [] for k in all_labels}
    info_lines_master = []

    for k in all_labels:
        for node in ordered_by_module.get(k, []):
            name = beam_label_by_guid.get(node, "?")
            display_info_name = "{} [KEY BEAM]".format(name) if is_key_beam_by_guid.get(node, False) else name

            beam = timber_model.get_element(node)
            try:
                length = beam.centerline.length
            except:
                length = 0.0

            w, h = get_beam_section(beam)
            orientation = get_orientation_string(w, h)
            weight = get_beam_weight(beam, length)
            w_m = w if (w is not None and w < 1) else (w / 100.0 if w is not None else None)
            h_m = h if (h is not None and h < 1) else (h / 100.0 if h is not None else None)
            volume_m3 = w_m * h_m * length if (w_m and h_m) else 0.0

            full_info = "{} | L={:.2f}m | Sez={} | Vol={:.2f}cm3 | Peso={:.1f}kg".format(
                display_info_name, length, orientation, volume_m3 * 1_000_000, weight
            )
            summary_by_category[k].append(full_info)
            info_lines_master.append(full_info)

    def sort_key(line):
        match = re.match(r'([A-Z]+)(\d+)', line)
        return (match.group(1), int(match.group(2))) if match else (line, 0)

    info_list = sorted(info_lines_master, key=sort_key)
    info_out = info_list[idx] if (0 <= idx < len(info_list)) else (info_list[0] if info_list else "nessun beam")

    # =========================
    # 9. POSIZIONI GLOBALI
    # =========================
    all_beams_positions = {}
    all_pts_list = list(pts.values())
    min_x3 = min(p[0] for p in all_pts_list)
    max_x3 = max(p[0] for p in all_pts_list)
    min_y3 = min(p[1] for p in all_pts_list)
    max_y3 = max(p[1] for p in all_pts_list)
    min_z3 = min(p[2] for p in all_pts_list)
    max_z3 = max(p[2] for p in all_pts_list)
    rx = max_x3 - min_x3 if max_x3 != min_x3 else 1.0
    ry = max_y3 - min_y3 if max_y3 != min_y3 else 1.0
    rz = max_z3 - min_z3 if max_z3 != min_z3 else 1.0

    for node in g.nodes():
        label = beam_label_by_guid.get(node, node)
        px, py, pz = pts[node]
        beam = timber_model.get_element(node)
        try:
            cl = beam.centerline
            s, e = get_line_start(cl), get_line_end(cl)
            all_beams_positions[label] = {
                "guid": node,
                "module": assignment.get(node, "?"),
                "centerline_start": [round(s.x, 4), round(s.y, 4), round(s.z, 4)],
                "centerline_end": [round(e.x, 4), round(e.y, 4), round(e.z, 4)],
                "midpoint": [round(px, 4), round(py, 4), round(pz, 4)],
                "midpoint_normalized": [
                    round((px - min_x3) / rx, 4),
                    round((py - min_y3) / ry, 4),
                    round((pz - min_z3) / rz, 4)
                ]
            }
        except:
            all_beams_positions[label] = {
                "guid": node,
                "module": assignment.get(node, "?"),
                "midpoint": [round(px, 4), round(py, 4), round(pz, 4)],
                "midpoint_normalized": [
                    round((px - min_x3) / rx, 4),
                    round((py - min_y3) / ry, 4),
                    round((pz - min_z3) / rz, 4)
                ]
            }

    # =========================
    # 10. EXPORT
    # =========================
    if RunExport and OutputFolder:
        output_folder = str(OutputFolder)
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        global_structure_path = os.path.join(output_folder, "structure.json")
        json_files_created, stl_files_created, blank_files_created, feature_files_created, stl_errors = [], [], [], [], []

        for k in all_labels:
            for node in ordered_by_module.get(k, []):
                name = beam_label_by_guid.get(node, "?")
                beam = timber_model.get_element(node)

                try:
                    length = beam.centerline.length
                except:
                    length = 0.0

                blank_length = get_blank_length(beam, length)
                w, h = get_beam_section(beam)
                w_m = w if (w is not None and w < 1) else (w / 100.0 if w is not None else None)
                h_m = h if (h is not None and h < 1) else (h / 100.0 if h is not None else None)
                weight = get_beam_weight(beam, length)
                volume_m3 = w_m * h_m * length if (w_m and h_m) else 0.0

                joints_list = sorted(beam_joints.get(node, []), key=lambda item: item[0])
                seen, clean_joints = set(), []
                for param, j_num in joints_list:
                    if j_num not in seen:
                        clean_joints.append(j_num)
                        seen.add(j_num)

                xlap, tbutt, lmiter = [], [], []
                for j_num in clean_joints:
                    j_type = joint_type_by_number.get(j_num, "")
                    if j_type == 'XLapJoint':
                        xlap.append(j_num)
                    elif j_type == 'TButtJoint':
                        tbutt.append(j_num)
                    elif j_type == 'LMiterJoint':
                        lmiter.append(j_num)

                beam_id = name.lower()
                beam_folder = os.path.join(output_folder, "beams", beam_id)
                if not os.path.exists(beam_folder):
                    os.makedirs(beam_folder)

                local_frame = get_beam_local_frame(beam)

                stl_path          = os.path.join(beam_folder, "{}.stl".format(beam_id))
                blank_stl_path    = os.path.join(beam_folder, "{}_blank.stl".format(beam_id))
                features_stl_path = os.path.join(beam_folder, "{}_features.stl".format(beam_id))

                try:
                    if write_geometry_ascii_stl(stl_path, beam_id, beam.geometry):
                        stl_files_created.append(stl_path)
                except Exception as error:
                    stl_errors.append("Errore STL geometry per {}: {}".format(beam_id, error))

                try:
                    blank = getattr(beam, "blank", None)
                    if write_geometry_ascii_stl(blank_stl_path, "{}_blank".format(beam_id), blank):
                        blank_files_created.append(blank_stl_path)
                except Exception as error:
                    stl_errors.append("Errore STL blank per {}: {}".format(beam_id, error))

                if not os.path.exists(stl_path):
                    stl_errors.append("Errore STL geometry per {}".format(beam_id))
                if not os.path.exists(blank_stl_path):
                    stl_errors.append("Errore STL blank per {}".format(beam_id))

                feature_records, feature_mesh_data = collect_non_joinery_features(beam)
                if feature_mesh_data:
                    try:
                        vertices, faces = feature_mesh_data
                        write_mesh_ascii_stl(features_stl_path, "{}_features".format(beam_id), vertices, faces)
                        feature_files_created.append(features_stl_path)
                    except Exception as error:
                        stl_errors.append("Errore STL features per {}: {}".format(beam_id, error))

                global_pos = all_beams_positions.get(name, {})

                beam_data = {
                    "beam ID": beam_id,
                    "name": name,
                    "module": k,
                    "is_key_beam": is_key_beam_by_guid.get(node, False),
                    "width (m)": round(w_m, 4) if w_m else None,
                    "height (m)": round(h_m, 4) if h_m else None,
                    "length (m)": round(length, 2),
                    "blank_length (m)": round(blank_length, 2) if blank_length else None,
                    "volume (cm³)": round(volume_m3 * 1_000_000, 2),
                    "weight (kg)": round(weight, 2),
                    "local_frame": local_frame,
                    "connected_beams": sorted([
                        beam_label_by_guid[nbr].lower()
                        for nbr in g.neighbors(node)
                        if nbr in beam_label_by_guid
                    ]),
                    "global_position": {
                        "centerline_start": global_pos.get("centerline_start"),
                        "centerline_end": global_pos.get("centerline_end"),
                        "midpoint": global_pos.get("midpoint"),
                        "midpoint_normalized": global_pos.get("midpoint_normalized")
                    },
                    "joints": {
                        "all": clean_joints,
                        "xlap": xlap,
                        "tbutt": tbutt,
                        "lmiter": lmiter
                    },
                    "features": feature_records,
                    "processing": feature_records,
                    "3d_model": "beams/{}/{}.stl".format(beam_id, beam_id),
                    "geometry_model": "beams/{}/{}.stl".format(beam_id, beam_id),
                    "blank_model": "beams/{}/{}_blank.stl".format(beam_id, beam_id)
                }
                if feature_files_created and feature_files_created[-1] == features_stl_path:
                    beam_data["features_model"] = "beams/{}/{}_features.stl".format(beam_id, beam_id)

                json_path = os.path.join(beam_folder, "{}.json".format(beam_id))
                with open(json_path, 'w') as f:
                    json.dump(beam_data, f, indent=2)
                json_files_created.append(json_path)

        # Global structure
        all_beams_list = []
        for k in all_labels:
            for node in ordered_by_module.get(k, []):
                label = beam_label_by_guid.get(node, "?")
                gpos = all_beams_positions.get(label, {})
                all_beams_list.append({
                    "beam_id": label.lower(),
                    "module": k,
                    "is_key_beam": is_key_beam_by_guid.get(node, False),
                    "centerline_start": gpos.get("centerline_start"),
                    "centerline_end": gpos.get("centerline_end"),
                    "midpoint": gpos.get("midpoint"),
                    "midpoint_normalized": gpos.get("midpoint_normalized"),
                    "connected_beams": sorted([
                        beam_label_by_guid[nbr].lower()
                        for nbr in g.neighbors(node)
                        if nbr in beam_label_by_guid
                    ])
                })

        structure_data = {
            "total_beams": len(all_beams_list),
            "bounding_box": {
                "min": [round(min_x3, 4), round(min_y3, 4), round(min_z3, 4)],
                "max": [round(max_x3, 4), round(max_y3, 4), round(max_z3, 4)]
            },
            "beams": all_beams_list
        }

        with open(global_structure_path, 'w') as f:
            json.dump(structure_data, f, indent=2)
        json_files_created.append(global_structure_path)

        json_export_out = "JSON: {} | STL geometry: {} | STL blank: {} | STL features: {} | Errori STL: {}".format(
            len(json_files_created), len(stl_files_created), len(blank_files_created),
            len(feature_files_created), len(stl_errors)
        )
        if stl_errors:
            json_export_out += "\n" + "\n".join(stl_errors[:5])

    # =========================
    # ASSEGNAZIONE OUTPUT GEOMETRIE
    # =========================
    A_geom_out = geom.get("A", [])
    B_geom_out = geom.get("B", [])
    C_geom_out = geom.get("C", [])
    D_geom_out = geom.get("D", [])
    E_geom_out = geom.get("E", [])
    F_geom_out = geom.get("F", [])
    G_geom_out = geom.get("G", [])
    H_geom_out = geom.get("H", [])

    return (
        debug_out,
        info_out,
        json_export_out,
        A_geom_out,
        B_geom_out,
        C_geom_out,
        D_geom_out,
        E_geom_out,
        F_geom_out,
        G_geom_out,
        H_geom_out,
        timber_model
    )


# =========================
# WEB EXPORT (Standalone)
# =========================

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
    """Export TimberModel JSON to web viewer format."""
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

    beam_records = []
    guid_to_beam_id = {}

    for index, (guid, element) in enumerate(elements):
        data = element["data"]
        beam_id, module, display_name = get_beam_identity(index, guid, data, module_sizes)
        guid_to_beam_id[guid] = beam_id
        frame = frame_from_data(data["frame"])
        blank_frame = blank_frame_from_beam_data(data)
        if blank_frame:
            frame["origin"] = blank_frame["origin"]
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
        blank_stl_path = beam_dir / "{}_blank.stl".format(beam_id)
        json_path = beam_dir / "{}.json".format(beam_id)

        vertices = beam_box_vertices(beam["frame"], beam["length"], beam["width"], beam["height"])
        write_ascii_stl(stl_path, beam_id, vertices)
        write_ascii_stl(blank_stl_path, "{}_blank".format(beam_id), vertices)

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
            "geometry_model": "{}/beams/{}/{}.stl".format(base_url.rstrip("/"), beam_id, beam_id),
            "blank_model": "{}/beams/{}/{}_blank.stl".format(base_url.rstrip("/"), beam_id, beam_id),
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

    return {
        "beam_count": len(beam_records),
        "joint_ref_count": sum(len(joints) for joints in joints_by_beam.values()),
    }