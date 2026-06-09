import os
import sys
import re
import json
import math
import Rhino.Geometry as rg
from collections import deque, defaultdict
from compas.datastructures import Graph


# =============================================================================
# DEFAULT WEB EXPORT SETTINGS
# =============================================================================

DEFAULT_BASE_URL = "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data"
DEFAULT_DENSITY_KG_M3 = 500.0


def run_numbering(timber_model, Index, RunExport, OutputFolder):
    # =========================
    # INSTANZIAZIONE OUTPUT PREDEFINITI
    # =========================
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
    # FUNZIONI GENERALI WEB EXPORT
    # =========================
    def rounded(value, digits=4):
        return round(float(value), digits)

    def clean_id(value):
        value = str(value).strip()
        value = re.sub(r"\s+", "", value)
        value = re.sub(r"[^A-Za-z0-9_-]", "", value)
        return value.lower()

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

    def beam_box_vertices_from_frame(frame, length, width, height):
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

    def write_box_ascii_stl(path, name, vertices):
        faces = [
            (0, 2, 3, 1),
            (4, 5, 7, 6),
            (0, 1, 5, 4),
            (2, 6, 7, 3),
            (0, 4, 6, 2),
            (1, 3, 7, 5),
        ]

        write_mesh_ascii_stl(path, name, vertices, faces)

    def geometry_to_vertices_and_faces(geometry):
        """
        Best-effort conversione di geometria COMPAS in vertices/faces.
        Serve per esportare STL più realistici quando beam.geometry è convertibile.
        """
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

            try:
                if hasattr(candidate, "to_mesh"):
                    mesh = candidate.to_mesh()
            except:
                mesh = candidate

            try:
                if hasattr(mesh, "to_vertices_and_faces"):
                    vertices, faces = mesh.to_vertices_and_faces()
                elif hasattr(mesh, "vertices") and hasattr(mesh, "faces"):
                    vertices = mesh.vertices
                    faces = mesh.faces
                else:
                    continue

                offset = len(combined_vertices)

                combined_vertices.extend(
                    [[float(coord) for coord in vertex] for vertex in vertices]
                )

                combined_faces.extend(
                    [[int(index) + offset for index in face] for face in faces]
                )

            except:
                continue

        if not combined_vertices or not combined_faces:
            return None

        return combined_vertices, combined_faces

    def joint_kind(name):
        lower = (name or "").lower()

        if "xlap" in lower:
            return "xlap"
        if "tbutt" in lower:
            return "tbutt"
        if "lmiter" in lower:
            return "lmiter"

        return "other"

    # =========================
    # TEST RAPIDO GEOMETRIA
    # =========================
    try:
        test_beam = list(timber_model.beams)[0]
        g_obj = test_beam.geometry

        debug_out = "TIPO: {}\nATTR: {}".format(
            type(g_obj),
            [a for a in dir(g_obj) if not a.startswith("_")]
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
    pts = {
        n: g.node_attributes(n, ["x", "y", "z"])
        for n in g.nodes()
    }

    min_x = min(p[0] for p in pts.values())
    max_x = max(p[0] for p in pts.values())
    min_y = min(p[1] for p in pts.values())
    max_y = max(p[1] for p in pts.values())

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

                        d = (
                            (px - nx2) ** 2
                            + (py - ny2) ** 2
                            + (pz - nz2) ** 2
                        )

                        if d < best_dist:
                            best_dist = d
                            best_candidate = nbr

            if best_candidate is None:
                remaining = list(group_set - visited)

                for r in remaining:
                    for v in visited:
                        px, py, pz = pts[v]
                        rx, ry, rz = pts[r]

                        d = (
                            (px - rx) ** 2
                            + (py - ry) ** 2
                            + (pz - rz) ** 2
                        )

                        if d < best_dist:
                            best_dist = d
                            best_candidate = r

            visited.add(best_candidate)
            order.append(best_candidate)
            frontier.append(best_candidate)

        return order

    # =========================
    # 6B. FUNZIONI GEOMETRICHE PER METADATI
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

    def get_point_xyz(p):
        """
        Supporta sia COMPAS Point con .x/.y/.z
        sia Rhino Point3d con .X/.Y/.Z.
        """
        x = p.x if hasattr(p, "x") else p.X
        y = p.y if hasattr(p, "y") else p.Y
        z = p.z if hasattr(p, "z") else p.Z

        return x, y, z

    def point_on_centerline(beam, t):
        line = beam.centerline

        try:
            return line.point_at(t)

        except:
            a = get_line_start(line)
            b = get_line_end(line)

            ax, ay, az = get_point_xyz(a)
            bx, by, bz = get_point_xyz(b)

            return rg.Point3d(
                ax + (bx - ax) * t,
                ay + (by - ay) * t,
                az + (bz - az) * t
            )

    def joint_point_from_beams(ea, eb):
        best_pa = None
        best_pb = None
        best_d = 1e99
        samples = 25

        for i in range(samples + 1):
            ta = float(i) / samples
            pa = point_on_centerline(ea, ta)

            pax, pay, paz = get_point_xyz(pa)

            for j in range(samples + 1):
                tb = float(j) / samples
                pb = point_on_centerline(eb, tb)

                pbx, pby, pbz = get_point_xyz(pb)

                d = (
                    (pax - pbx) ** 2
                    + (pay - pby) ** 2
                    + (paz - pbz) ** 2
                )

                if d < best_d:
                    best_d = d
                    best_pa = pa
                    best_pb = pb

        ax, ay, az = get_point_xyz(best_pa)
        bx, by, bz = get_point_xyz(best_pb)

        return rg.Point3d(
            (ax + bx) / 2.0,
            (ay + by) / 2.0,
            (az + bz) / 2.0
        )

    def parameter_on_centerline(beam, point):
        best_t = 0.0
        best_d = 1e99
        samples = 50

        px = point.X if hasattr(point, "X") else point.x
        py = point.Y if hasattr(point, "Y") else point.y
        pz = point.Z if hasattr(point, "Z") else point.z

        for i in range(samples + 1):
            t = float(i) / samples
            p = point_on_centerline(beam, t)

            x, y, z = get_point_xyz(p)

            d = (
                (x - px) ** 2
                + (y - py) ** 2
                + (z - pz) ** 2
            )

            if d < best_d:
                best_d = d
                best_t = t

        return best_t

    # =========================
    # 6C. FUNZIONI SEZIONE, ORIENTAMENTO E PESO
    # =========================
    def get_beam_section(beam):
        for w_attr in ["width", "w", "b", "breadth"]:
            for h_attr in ["height", "h", "d", "depth"]:
                try:
                    w = getattr(beam, w_attr)
                    h = getattr(beam, h_attr)

                    if w and h:
                        return float(w), float(h)

                except:
                    continue

        try:
            sec = beam.section

            for w_attr in ["width", "w", "b", "breadth"]:
                for h_attr in ["height", "h", "d", "depth"]:
                    try:
                        w = getattr(sec, w_attr)
                        h = getattr(sec, h_attr)

                        if w and h:
                            return float(w), float(h)

                    except:
                        continue

        except:
            pass

        for container in ["blank", "shape", "profile"]:
            try:
                obj = getattr(beam, container)

                w = getattr(obj, "xsize", None) or getattr(obj, "width", None)
                h = getattr(obj, "ysize", None) or getattr(obj, "height", None)

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

    WOOD_DENSITY = DEFAULT_DENSITY_KG_M3

    def get_beam_weight(beam, length):
        w, h = get_beam_section(beam)

        if w is None or h is None:
            return 0.0

        w_m = w if w < 1 else w / 100.0
        h_m = h if h < 1 else h / 100.0

        volume = w_m * h_m * length

        return volume * WOOD_DENSITY

    # =========================
    # 6D. FUNZIONI STL RHINO + COMPAS
    # =========================
    def write_rhino_stl(rg_mesh, path):
        lines = ["solid beam"]

        rg_mesh.Normals.ComputeNormals()

        for i in range(rg_mesh.Faces.Count):
            face = rg_mesh.Faces[i]
            verts = rg_mesh.Vertices

            def write_tri(p0, p1, p2):
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

                lines.append("  facet normal {} {} {}".format(nx, ny, nz))

                lines.append(
                    "    outer loop\n"
                    "      vertex {} {} {}\n"
                    "      vertex {} {} {}\n"
                    "      vertex {} {} {}\n"
                    "    endloop\n"
                    "  endfacet".format(
                        p0.X, p0.Y, p0.Z,
                        p1.X, p1.Y, p1.Z,
                        p2.X, p2.Y, p2.Z
                    )
                )

            if face.IsTriangle:
                write_tri(verts[face.A], verts[face.B], verts[face.C])

            else:
                write_tri(verts[face.A], verts[face.B], verts[face.C])
                write_tri(verts[face.A], verts[face.C], verts[face.D])

        lines.append("endsolid beam")

        with open(path, "w") as f:
            f.write("\n".join(lines))

    def save_stl(beam, beam_id, beam_folder, local_frame, length, w_m, h_m):
        """
        Priorità:
        1. mesh reale COMPAS se convertibile in vertices/faces
        2. geometry.to_stl()
        3. Brep/Mesh Rhino nativa
        4. fallback box rettangolare dal local_frame
        """
        stl_path = os.path.join(beam_folder, "{}.stl".format(beam_id))
        geometry = beam.geometry

        # 1) COMPAS mesh realistica / processata
        try:
            mesh_data = geometry_to_vertices_and_faces(geometry)

            if mesh_data:
                vertices, faces = mesh_data
                write_mesh_ascii_stl(stl_path, beam_id, vertices, faces)

                if os.path.exists(stl_path):
                    return stl_path, "compas_mesh"

        except:
            pass

        # 2) to_stl diretto
        if hasattr(geometry, "to_stl"):
            try:
                geometry.to_stl(stl_path)

                if os.path.exists(stl_path):
                    return stl_path, "to_stl"

            except:
                pass

        # 3) Rhino native brep / mesh
        try:
            native = None

            if isinstance(geometry, rg.Brep):
                native = geometry

            elif isinstance(geometry, rg.Mesh):
                write_rhino_stl(geometry, stl_path)
                return stl_path, "rhino_mesh"

            elif hasattr(geometry, "native_brep") and geometry.native_brep:
                native = geometry.native_brep

            elif hasattr(geometry, "native_mesh") and geometry.native_mesh:
                write_rhino_stl(geometry.native_mesh, stl_path)
                return stl_path, "native_mesh"

            if native:
                meshp = rg.MeshingParameters.Default
                meshes = rg.Mesh.CreateFromBrep(native, meshp)

                if meshes:
                    joined = rg.Mesh()

                    for m in meshes:
                        joined.Append(m)

                    write_rhino_stl(joined, stl_path)

                    return stl_path, "rhino_brep"

        except:
            pass

        # 4) Fallback box dal frame locale
        try:
            if local_frame and w_m and h_m and length:
                vertices = beam_box_vertices_from_frame(
                    local_frame,
                    length,
                    w_m,
                    h_m
                )

                write_box_ascii_stl(stl_path, beam_id, vertices)

                if os.path.exists(stl_path):
                    return stl_path, "box_fallback"

        except:
            pass

        return None, "error"

    # =========================
    # 6E. FUNZIONE FRAME LOCALE BEAM
    # =========================
    def get_beam_local_frame(beam):
        try:
            line = beam.centerline

            start = line.start if hasattr(line, "start") else get_line_start(line)
            end = line.end if hasattr(line, "end") else get_line_end(line)

            sx, sy, sz = get_point_xyz(start)
            ex, ey, ez = get_point_xyz(end)

            dx, dy, dz = ex - sx, ey - sy, ez - sz
            length = (dx**2 + dy**2 + dz**2) ** 0.5

            if length < 1e-10:
                return None

            x_axis = [dx / length, dy / length, dz / length]

            ref = [1.0, 0.0, 0.0] if abs(x_axis[2]) > 0.9 else [0.0, 0.0, 1.0]

            cx = x_axis[1] * ref[2] - x_axis[2] * ref[1]
            cy = x_axis[2] * ref[0] - x_axis[0] * ref[2]
            cz = x_axis[0] * ref[1] - x_axis[1] * ref[0]

            c_len = (cx**2 + cy**2 + cz**2) ** 0.5

            if c_len < 1e-10:
                return None

            z_axis = [cx / c_len, cy / c_len, cz / c_len]

            y_axis = [
                z_axis[1] * x_axis[2] - z_axis[2] * x_axis[1],
                z_axis[2] * x_axis[0] - z_axis[0] * x_axis[2],
                z_axis[0] * x_axis[1] - z_axis[1] * x_axis[0],
            ]

            origin = [
                (sx + ex) / 2.0,
                (sy + ey) / 2.0,
                (sz + ez) / 2.0,
            ]

            return {
                "origin": [round(v, 4) for v in origin],
                "x_axis": [round(v, 4) for v in vector_normalize(x_axis)],
                "y_axis": [round(v, 4) for v in vector_normalize(y_axis)],
                "z_axis": [round(v, 4) for v in vector_normalize(z_axis)],
            }

        except:
            return None

    def make_structure_entry(beam_record):
        return {
            "beam_id": beam_record["beam_id"],
            "module": beam_record["module"],
            "centerline_start": beam_record["centerline_start"],
            "centerline_end": beam_record["centerline_end"],
            "midpoint": beam_record["midpoint"],
            "midpoint_normalized": beam_record["midpoint_normalized"],
            "connected_beams": beam_record["connected_beams"],
        }

    # =========================
    # 7. GENERAZIONE OUTPUT BEAMS
    # =========================
    geom = {k: [] for k in seeds}
    ordered_by_module = {}
    beam_label_by_guid = {}

    for k in seeds:
        ordered = connected_growth(seeds[k], groups[k])
        ordered_by_module[k] = ordered

        for i, node in enumerate(ordered):
            beam = timber_model.get_element(node)
            name = "{}{}".format(k, i + 1)

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
    # 7B. STRUTTURA INTERNA DEI CO-GIUNTI
    # =========================
    joint_number_by_pair = {}
    beam_joints = {node: [] for node in g.nodes()}
    joint_type_by_number = {}
    joint_details_by_number = {}
    connected_by_beam = defaultdict(set)
    counter = 1

    for joint in timber_model.joints:
        ea, eb = joint.elements

        ga = str(ea.guid)
        gb = str(eb.guid)

        pair_key = tuple(sorted([ga, gb]))

        if pair_key not in joint_number_by_pair:
            joint_number = "{:02d}".format(counter)
            joint_number_by_pair[pair_key] = joint_number
            joint_type_by_number[joint_number] = type(joint).__name__
            counter += 1

        else:
            joint_number = joint_number_by_pair[pair_key]

        jp = joint_point_from_beams(ea, eb)
        kind = joint_kind(type(joint).__name__)

        label_a = beam_label_by_guid.get(ga, ga).lower()
        label_b = beam_label_by_guid.get(gb, gb).lower()

        connected_by_beam[label_a].add(label_b)
        connected_by_beam[label_b].add(label_a)

        joint_details_by_number[joint_number] = {
            "id": joint_number,
            "type": type(joint).__name__,
            "kind": kind,
            "connected_beams": sorted([label_a, label_b]),
            "location": [
                round(jp.X, 4),
                round(jp.Y, 4),
                round(jp.Z, 4)
            ],
        }

        beam_joints[ga].append((parameter_on_centerline(ea, jp), joint_number))
        beam_joints[gb].append((parameter_on_centerline(eb, jp), joint_number))

    A_geom_out = geom["A"]
    B_geom_out = geom["B"]
    C_geom_out = geom["C"]
    D_geom_out = geom["D"]
    E_geom_out = geom["E"]
    F_geom_out = geom["F"]

    # =========================
    # 9. ELABORAZIONE DETTAGLI
    # =========================
    summary_by_category = {k: [] for k in labels_keys}
    info_lines_master = []

    for k in labels_keys:
        for node in ordered_by_module.get(k, []):
            name = beam_label_by_guid.get(node, "?")
            beam = timber_model.get_element(node)

            length = beam.centerline.length if hasattr(beam.centerline, "length") else 0.0

            w, h = get_beam_section(beam)
            orientation = get_orientation_string(w, h)
            weight = get_beam_weight(beam, length)

            w_m = w if (w is not None and w < 1) else (w / 100.0 if w is not None else None)
            h_m = h if (h is not None and h < 1) else (h / 100.0 if h is not None else None)

            volume_m3 = w_m * h_m * length if (w_m and h_m) else 0.0

            full_info_string = "{} | L={:.2f}m | Sez={} | Vol={:.2f}cm3 | Peso={:.1f}kg".format(
                name,
                length,
                orientation,
                volume_m3 * 1000000.0,
                weight,
            )

            summary_by_category[k].append(full_info_string)
            info_lines_master.append(full_info_string)

    def sort_key(line):
        match = re.match(r"([A-Z]+)(\d+)", line)

        return (match.group(1), int(match.group(2))) if match else (line, 0)

    info_list = sorted(info_lines_master, key=sort_key)

    info_out = (
        info_list[idx]
        if (0 <= idx < len(info_list))
        else (info_list[0] if info_list else "nessun beam")
    )

    # =========================
    # 10B. POSIZIONI GLOBALI TUTTI I BEAM
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

            s = get_line_start(cl)
            e = get_line_end(cl)

            sx, sy, sz = get_point_xyz(s)
            ex, ey, ez = get_point_xyz(e)

            all_beams_positions[label] = {
                "guid": node,
                "module": assignment.get(node, "?"),
                "centerline_start": [
                    round(sx, 4),
                    round(sy, 4),
                    round(sz, 4)
                ],
                "centerline_end": [
                    round(ex, 4),
                    round(ey, 4),
                    round(ez, 4)
                ],
                "midpoint": [
                    round(px, 4),
                    round(py, 4),
                    round(pz, 4)
                ],
                "midpoint_normalized": [
                    round((px - min_x3) / rx, 4),
                    round((py - min_y3) / ry, 4),
                    round((pz - min_z3) / rz, 4),
                ],
            }

        except:
            all_beams_positions[label] = {
                "guid": node,
                "module": assignment.get(node, "?"),
                "midpoint": [
                    round(px, 4),
                    round(py, 4),
                    round(pz, 4)
                ],
                "midpoint_normalized": [
                    round((px - min_x3) / rx, 4),
                    round((py - min_y3) / ry, 4),
                    round((pz - min_z3) / rz, 4),
                ],
            }

    # =========================
    # 11 & 12. EXPORT DINAMICO CON CARTELLA DA GRASSHOPPER
    # =========================
    if RunExport and OutputFolder:
        output_folder = str(OutputFolder)

        # OutputFolder viene trattata come cartella web_data.
        # Dentro vengono creati:
        # - structure.json
        # - beams/<beam_id>/<beam_id>.json
        # - beams/<beam_id>/<beam_id>.stl
        beams_root = os.path.join(output_folder, "beams")
        structure_path = os.path.join(output_folder, "structure.json")

        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        if not os.path.exists(beams_root):
            os.makedirs(beams_root)

        json_files_created = []
        stl_files_created = []
        stl_errors = []
        stl_source_counter = defaultdict(int)

        all_beams_list = []

        for k in labels_keys:
            for node in ordered_by_module.get(k, []):
                name = beam_label_by_guid.get(node, "?")
                beam = timber_model.get_element(node)

                try:
                    length = beam.centerline.length
                except:
                    length = 0.0

                w, h = get_beam_section(beam)

                w_m = (
                    w
                    if (w is not None and w < 1)
                    else (w / 100.0 if w is not None else None)
                )

                h_m = (
                    h
                    if (h is not None and h < 1)
                    else (h / 100.0 if h is not None else None)
                )

                weight = get_beam_weight(beam, length)
                volume_m3 = w_m * h_m * length if (w_m and h_m) else 0.0

                joints_list = sorted(
                    beam_joints.get(node, []),
                    key=lambda item: item[0]
                )

                seen = set()
                clean_joints = []

                for param, j_num in joints_list:
                    if j_num not in seen:
                        clean_joints.append(j_num)
                        seen.add(j_num)

                xlap = []
                tbutt = []
                lmiter = []
                other = []
                details = []

                for j_num in clean_joints:
                    j_type = joint_type_by_number.get(j_num, "")
                    kind = joint_kind(j_type)

                    if kind == "xlap":
                        xlap.append(j_num)

                    elif kind == "tbutt":
                        tbutt.append(j_num)

                    elif kind == "lmiter":
                        lmiter.append(j_num)

                    else:
                        other.append(j_num)

                    if j_num in joint_details_by_number:
                        details.append(joint_details_by_number[j_num])

                beam_id = clean_id(name)
                beam_folder = os.path.join(beams_root, beam_id)

                if not os.path.exists(beam_folder):
                    os.makedirs(beam_folder)

                local_frame = get_beam_local_frame(beam)

                stl_result, stl_source = save_stl(
                    beam,
                    beam_id,
                    beam_folder,
                    local_frame,
                    length,
                    w_m,
                    h_m
                )

                stl_source_counter[stl_source] += 1

                if stl_result:
                    stl_files_created.append(stl_result)

                else:
                    stl_errors.append("Errore STL per {}".format(beam_id))

                global_pos = all_beams_positions.get(name, {})

                connected_labels = sorted([
                    beam_label_by_guid[nbr].lower()
                    for nbr in g.neighbors(node)
                    if nbr in beam_label_by_guid
                ])

                # Unione tra connessioni da grafo e connessioni da joint details.
                connected_labels = sorted(
                    set(connected_labels)
                    | set(connected_by_beam.get(beam_id, []))
                )

                centerline_start = global_pos.get("centerline_start")
                centerline_end = global_pos.get("centerline_end")
                midpoint = global_pos.get("midpoint")
                midpoint_normalized = global_pos.get("midpoint_normalized")

                beam_data = {
                    "beam ID": beam_id,
                    "name": name,
                    "module": k,

                    "width (m)": round(w_m, 4) if w_m else None,
                    "height (m)": round(h_m, 4) if h_m else None,
                    "length (m)": round(length, 4),

                    "volume (cm3)": round(volume_m3 * 1000000.0, 2),
                    "volume (cm³)": round(volume_m3 * 1000000.0, 2),

                    "weight (kg)": round(weight, 2),

                    "local_frame": local_frame,

                    "connected_beams": connected_labels,

                    "global_position": {
                        "centerline_start": centerline_start,
                        "centerline_end": centerline_end,
                        "midpoint": midpoint,
                        "midpoint_normalized": midpoint_normalized,
                    },

                    "joints": {
                        "all": clean_joints,
                        "xlap": xlap,
                        "tbutt": tbutt,
                        "lmiter": lmiter,
                        "other": other,
                        "details": details,
                    },

                    "processing": [],

                    "3d_model": "{}/beams/{}/{}.stl".format(
                        DEFAULT_BASE_URL.rstrip("/"),
                        beam_id,
                        beam_id
                    ),
                }

                json_path = os.path.join(
                    beam_folder,
                    "{}.json".format(beam_id)
                )

                with open(json_path, "w") as f:
                    json.dump(beam_data, f, indent=2)

                json_files_created.append(json_path)

                all_beams_list.append(
                    make_structure_entry({
                        "beam_id": beam_id,
                        "module": k,
                        "centerline_start": centerline_start,
                        "centerline_end": centerline_end,
                        "midpoint": midpoint,
                        "midpoint_normalized": midpoint_normalized,
                        "connected_beams": connected_labels,
                    })
                )

        structure = {
            "total_beams": len(all_beams_list),
            "bounding_box": {
                "min": [
                    round(min_x3, 4),
                    round(min_y3, 4),
                    round(min_z3, 4)
                ],
                "max": [
                    round(max_x3, 4),
                    round(max_y3, 4),
                    round(max_z3, 4)
                ],
            },
            "beams": all_beams_list,
        }

        with open(structure_path, "w") as f:
            json.dump(structure, f, indent=2)

        json_files_created.append(structure_path)

        json_export_out = (
            "JSON: {} | STL: {} | Errori STL: {}\n"
            "STL source: compas_mesh={} | to_stl={} | rhino_brep={} | "
            "rhino_mesh={} | native_mesh={} | box_fallback={}"
        ).format(
            len(json_files_created),
            len(stl_files_created),
            len(stl_errors),
            stl_source_counter.get("compas_mesh", 0),
            stl_source_counter.get("to_stl", 0),
            stl_source_counter.get("rhino_brep", 0),
            stl_source_counter.get("rhino_mesh", 0),
            stl_source_counter.get("native_mesh", 0),
            stl_source_counter.get("box_fallback", 0),
        )

        if stl_errors:
            json_export_out += "\n" + "\n".join(stl_errors[:5])

    # =========================
    # 13. RETURN FINALE MODIFICATO (9 USCITE TOTALI)
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
        F_geom_out          # 8
    )