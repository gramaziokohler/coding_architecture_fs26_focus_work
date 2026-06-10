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
DEFAULT_MODULE_SIZES = "A:36,B:31,C:30,D:27,E:27,F:31"

NAME_KEYS = ("beam_id", "beam ID", "beam_name", "name", "label", "mark")
MODULE_KEYS = ("module", "module_id", "module_name", "fabrication_module", "assembly_module", "group")
NUMBER_KEYS = ("beam_number", "number", "sequence", "fabrication_number", "element_number", "index")

# =========================
# UTILITY FUNCTIONS
# =========================

def rounded(value, digits=4):
    """Round a value or list of values."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [rounded(v, digits) for v in value]
    return round(float(value), digits)

def clean_id(value):
    """Clean beam ID."""
    value = str(value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[^A-Za-z0-9_-]", "", value)
    return value.lower()

def parse_module_sizes(value):
    """Parse 'A:36,B:31,C:30' into list of (module, count)."""
    sizes = []
    for item in value.split(","):
        if not item.strip():
            continue
        module, count = item.split(":", 1)
        sizes.append((module.strip().upper(), int(count)))
    return sizes

def sequential_identity(index, module_sizes):
    """Generate beam_id from sequential index and module sizes."""
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
    """Get first non-empty value from mapping for given keys."""
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def set_beam_partitioning_attributes(beam, module, number, beam_id=None, display_name=None):
    """Persist partitioning metadata on a beam's attributes for later grouping/parsing."""
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
    """Return (beam_id, module, display_name) for one beam."""
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

def vector_length(v):
    return math.sqrt(sum(component * component for component in v))

def vector_normalize(v):
    length = vector_length(v)
    if not length:
        return [0.0, 0.0, 0.0]
    return [component / length for component in v]

def frame_from_data(frame_data):
    """Extract and normalize frame from JSON data."""
    data = frame_data.get("data", frame_data)
    origin = data.get("point") or data.get("origin")
    x_axis = data.get("xaxis") or data.get("x_axis")
    y_axis = data.get("yaxis") or data.get("y_axis")
    
    # Compute z_axis from cross product if not provided
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

# =========================
# BEAM GEOMETRY OPERATIONS
# =========================

def get_line_start(line):
    """Extract start point from line object."""
    if hasattr(line, "start"):
        return line.start
    if hasattr(line, "start_point"):
        return line.start_point
    if hasattr(line, "point_at"):
        return line.point_at(0.0)
    return line[0]

def get_line_end(line):
    """Extract end point from line object."""
    if hasattr(line, "end"):
        return line.end
    if hasattr(line, "end_point"):
        return line.end_point
    if hasattr(line, "point_at"):
        return line.point_at(1.0)
    return line[1]

def get_beam_section(beam):
    """Extract beam cross-section dimensions."""
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
    """Format section as string."""
    if w is None or h is None:
        return "?x?cm"
    w_cm = round(w * 100) if w < 1 else round(w)
    h_cm = round(h * 100) if h < 1 else round(h)
    return "{}x{}cm".format(int(w_cm), int(h_cm))

def get_beam_weight(beam, length, density=500):
    """Calculate beam weight from section and length."""
    w, h = get_beam_section(beam)
    if w is None or h is None:
        return 0.0
    w_m = w if w < 1 else w / 100.0
    h_m = h if h < 1 else h / 100.0
    volume = w_m * h_m * length
    return volume * density

def get_beam_local_frame(beam):
    """Extract local frame from beam centerline (for Grasshopper)."""
    try:
        line = beam.centerline
        start = line.start if hasattr(line, "start") else get_line_start(line)
        end = line.end if hasattr(line, "end") else get_line_end(line)
        dx = end.x - start.x
        dy = end.y - start.y
        dz = end.z - start.z
        length = (dx**2 + dy**2 + dz**2) ** 0.5
        if length < 1e-10:
            return None
        x_axis = [dx/length, dy/length, dz/length]
        ref = [1.0, 0.0, 0.0] if abs(x_axis[2]) > 0.9 else [0.0, 0.0, 1.0]
        cx = x_axis[1]*ref[2] - x_axis[2]*ref[1]
        cy = x_axis[2]*ref[0] - x_axis[0]*ref[2]
        cz = x_axis[0]*ref[1] - x_axis[1]*ref[0]
        c_len = (cx**2 + cy**2 + cz**2) ** 0.5
        if c_len < 1e-10:
            return None
        z_axis = [cx/c_len, cy/c_len, cz/c_len]
        y_axis = [
            z_axis[1]*x_axis[2] - z_axis[2]*x_axis[1],
            z_axis[2]*x_axis[0] - z_axis[0]*x_axis[2],
            z_axis[0]*x_axis[1] - z_axis[1]*x_axis[0]
        ]
        return {
            "origin": [round((start.x+end.x)/2.0, 4), round((start.y+end.y)/2.0, 4), round((start.z+end.z)/2.0, 4)],
            "x_axis": [round(v, 4) for v in x_axis],
            "y_axis": [round(v, 4) for v in y_axis],
            "z_axis": [round(v, 4) for v in z_axis]
        }
    except:
        return None

# =========================
# STL EXPORT FUNCTIONS
# =========================

def facet_normal(a, b, c):
    """Calculate normal for triangle face."""
    return vector_normalize(vector_cross(vector_sub(b, a), vector_sub(c, a)))

def triangulate_face(face):
    """Convert polygon face to triangles."""
    if len(face) < 3:
        return []
    if len(face) == 3:
        return [face]
    return [(face[0], face[index], face[index + 1]) for index in range(1, len(face) - 1)]

def write_mesh_ascii_stl(path, name, vertices, faces):
    """Write mesh as ASCII STL."""
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
    """Write box as ASCII STL."""
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
    """Create 8 vertices of a box from frame."""
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

def geometry_to_vertices_and_faces(geometry):
    """Convert COMPAS geometry to mesh data."""
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

# =========================
# JOINT FUNCTIONS
# =========================

def point_on_centerline(beam, t):
    """Get point on beam centerline at parameter t [0,1]."""
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
    """Find closest point between two beam centerlines."""
    best_pa, best_pb = None, None
    best_d = 1e99
    samples = 25
    for i in range(samples + 1):
        ta = float(i) / samples
        pa = point_on_centerline(ea, ta)
        for j in range(samples + 1):
            tb = float(j) / samples
            pb = point_on_centerline(eb, tb)
            d = (pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2 + (pa.z - pb.z) ** 2
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
    """Find parameter t on centerline closest to point."""
    best_t = 0.0
    best_d = 1e99
    samples = 50
    for i in range(samples + 1):
        t = float(i) / samples
        p = point_on_centerline(beam, t)
        d = (p.x - point.X) ** 2 + (p.y - point.Y) ** 2 + (p.z - point.Z) ** 2
        if d < best_d:
            best_d = d
            best_t = t
    return best_t

def point_data(value):
    """Extract point data from value."""
    if not value:
        return None
    if isinstance(value, dict):
        return value.get("data")
    return value

def joint_kind(name):
    """Classify joint by name."""
    lower = (name or "").lower()
    if "xlap" in lower:
        return "xlap"
    if "tbutt" in lower:
        return "tbutt"
    if "lmiter" in lower:
        return "lmiter"
    return "other"

def collect_joints(model_data, guid_to_beam_id):
    """Collect joint data from model."""
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
    
    Returns (10 outputs):
    0: debug_out
    1: info_out
    2: json_export_out
    3: A_geom_out
    4: B_geom_out
    5: C_geom_out
    6: D_geom_out
    7: E_geom_out
    8: F_geom_out
    9: timber_model (with module and number attributes on each beam)
    """
    
    debug_out = ""
    info_out = ""
    json_export_out = "Export non avviato (RunExport è False)."
    A_geom_out, B_geom_out, C_geom_out = [], [], []
    D_geom_out, E_geom_out, F_geom_out = [], [], []

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
    # 3. GRIGLIA 3x2 = 6 MODULI
    # =========================
    nx = 3
    ny = 2
    dx = (max_x - min_x) / nx
    dy = (max_y - min_y) / ny

    cells = []
    for i in range(nx):
        for j in range(ny):
            cx = min_x + dx * (i + 0.5)
            cy = min_y + dy * (j + 0.5)
            cells.append((cx, cy))

    labels_keys = ["A", "B", "C", "D", "E", "F"]

    # =========================
    # 4. SEEDS
    # =========================
    def dist2(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    seeds = {}
    for key, (cx, cy) in zip(labels_keys, cells):
        seed = min(pts, key=lambda n: dist2(pts[n], (cx, cy)))
        seeds[key] = seed

    # =========================
    # 5. ASSEGNAZIONE SPAZIALE
    # =========================
    assignment = {}
    groups = {k: [] for k in seeds}

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
                        d = (px - nx2) ** 2 + (py - ny2) ** 2 + (pz - nz2) ** 2
                        if d < best_dist:
                            best_dist = d
                            best_candidate = nbr

            if best_candidate is None:
                remaining = list(group_set - visited)
                for r in remaining:
                    for v in visited:
                        px, py, pz = pts[v]
                        rx, ry, rz = pts[r]
                        d = (px - rx) ** 2 + (py - ry) ** 2 + (pz - rz) ** 2
                        if d < best_dist:
                            best_dist = d
                            best_candidate = r

            visited.add(best_candidate)
            order.append(best_candidate)
            frontier.append(best_candidate)

        return order

    # =========================
    # 7. GENERAZIONE BEAM OUTPUT
    # =========================
    geom = {k: [] for k in labels_keys}
    ordered_by_module = {}
    beam_label_by_guid = {}

    for k in labels_keys:
        ordered = connected_growth(seeds[k], groups[k])
        ordered_by_module[k] = ordered

        for i, node in enumerate(ordered):
            beam = timber_model.get_element(node)
            name = "{}{}".format(k, i + 1)
            set_beam_partitioning_attributes(beam, k, i + 1, beam_id=name.lower(), display_name=name)

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
    summary_by_category = {k: [] for k in labels_keys}
    info_lines_master = []

    for k in labels_keys:
        for node in ordered_by_module.get(k, []):
            name = beam_label_by_guid.get(node, "?")
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
                name, length, orientation, volume_m3 * 1_000_000, weight
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
    # 10. EXPORT DINAMICO
    # =========================
    if RunExport and OutputFolder:
        output_folder = str(OutputFolder)
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        global_structure_path = os.path.join(output_folder, "structure.json")
        json_files_created, stl_files_created, stl_errors = [], [], []

        for k in labels_keys:
            for node in ordered_by_module.get(k, []):
                name = beam_label_by_guid.get(node, "?")
                beam = timber_model.get_element(node)
                
                try:
                    length = beam.centerline.length
                except:
                    length = 0.0

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
                beam_folder = os.path.join(output_folder, beam_id)
                if not os.path.exists(beam_folder):
                    os.makedirs(beam_folder)

                # STL Export
                stl_path = os.path.join(beam_folder, "{}.stl".format(beam_id))
                try:
                    if hasattr(beam.geometry, 'native_brep') or isinstance(beam.geometry, rg.Brep):
                        native = getattr(beam.geometry, 'native_brep', beam.geometry)
                        meshp = rg.MeshingParameters.Default
                        meshes = rg.Mesh.CreateFromBrep(native, meshp)
                        if meshes:
                            joined = rg.Mesh()
                            for m in meshes:
                                joined.Append(m)
                            stl_lines = ["solid {}".format(beam_id)]
                            for i in range(joined.Faces.Count):
                                face = joined.Faces[i]
                                verts = joined.Vertices
                                def add_tri(p0, p1, p2):
                                    ux = p1.X - p0.X
                                    uy = p1.Y - p0.Y
                                    uz = p1.Z - p0.Z
                                    vx = p2.X - p0.X
                                    vy = p2.Y - p0.Y
                                    vz = p2.Z - p0.Z
                                    nx = uy * vz - uz * vy
                                    ny = uz * vx - ux * vz
                                    nz = ux * vy - uy * vx
                                    length_n = (nx**2 + ny**2 + nz**2) ** 0.5
                                    if length_n > 0:
                                        nx /= length_n
                                        ny /= length_n
                                        nz /= length_n
                                    stl_lines.append("  facet normal {} {} {}".format(nx, ny, nz))
                                    stl_lines.append("    outer loop")
                                    stl_lines.append("      vertex {} {} {}".format(p0.X, p0.Y, p0.Z))
                                    stl_lines.append("      vertex {} {} {}".format(p1.X, p1.Y, p1.Z))
                                    stl_lines.append("      vertex {} {} {}".format(p2.X, p2.Y, p2.Z))
                                    stl_lines.append("    endloop")
                                    stl_lines.append("  endfacet")
                                if face.IsTriangle:
                                    add_tri(verts[face.A], verts[face.B], verts[face.C])
                                else:
                                    add_tri(verts[face.A], verts[face.B], verts[face.C])
                                    add_tri(verts[face.A], verts[face.C], verts[face.D])
                            stl_lines.append("endsolid {}".format(beam_id))
                            with open(stl_path, 'w') as f:
                                f.write("\n".join(stl_lines))
                            stl_files_created.append(stl_path)
                except:
                    pass

                if not os.path.exists(stl_path):
                    stl_errors.append("Errore STL per {}".format(beam_id))

                global_pos = all_beams_positions.get(name, {})
                beam_data = {
                    "beam ID": beam_id,
                    "name": name,
                    "module": k,
                    "width (m)": round(w_m, 4) if w_m else None,
                    "height (m)": round(h_m, 4) if h_m else None,
                    "length (m)": round(length, 2),
                    "volume (cm³)": round(volume_m3 * 1_000_000, 2),
                    "weight (kg)": round(weight, 2),
                    "local_frame": get_beam_local_frame(beam),
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
                    "3d_model": "beams/{}/{}.stl".format(beam_id, beam_id)
                }

                json_path = os.path.join(beam_folder, "{}.json".format(beam_id))
                with open(json_path, 'w') as f:
                    json.dump(beam_data, f, indent=2)
                json_files_created.append(json_path)

        # Global structure
        all_beams_list = []
        for k in labels_keys:
            for node in ordered_by_module.get(k, []):
                label = beam_label_by_guid.get(node, "?")
                gpos = all_beams_positions.get(label, {})
                all_beams_list.append({
                    "beam_id": label.lower(),
                    "module": k,
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

        json_export_out = "JSON: {} | STL: {} | Errori STL: {}".format(
            len(json_files_created), len(stl_files_created), len(stl_errors)
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

    # =========================
    # RETURN (10 OUTPUTS)
    # =========================
    return (
        debug_out,          # 0
        info_out,           # 1
        json_export_out,    # 2
        A_geom_out,         # 3
        B_geom_out,         # 4
        C_geom_out,         # 5
        D_geom_out,         # 6
        E_geom_out,         # 7
        F_geom_out,         # 8
        timber_model        # 9 - with module and number attributes on each beam
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
        json_path = beam_dir / "{}.json".format(beam_id)

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

    return {
        "beam_count": len(beam_records),
        "joint_ref_count": sum(len(joints) for joints in joints_by_beam.values()),
    }
