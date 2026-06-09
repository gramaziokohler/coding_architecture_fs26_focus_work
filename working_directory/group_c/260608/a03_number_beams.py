import os
import sys
import re
import json
import math
import Rhino.Geometry as rg
from collections import deque, defaultdict
from compas.datastructures import Graph

# =========================
# UTILITY FUNCTIONS
# =========================

def rounded(value, digits=4):
    """Round a value to specified digits."""
    return round(float(value), digits)

def clean_id(value):
    """Clean a string to be a valid ID."""
    value = str(value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[^A-Za-z0-9_-]", "", value)
    return value.lower()

def parse_module_sizes(value):
    """Parse module sizes string like 'A:36,B:31,C:30,D:27,E:27,F:31'"""
    sizes = []
    for item in value.split(","):
        if not item.strip():
            continue
        module, count = item.split(":", 1)
        sizes.append((module.strip().upper(), int(count)))
    return sizes

def sequential_identity(index, module_sizes):
    """Return (beam_id, module, display_name) for one beam based on index."""
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
    """Get first non-empty value from mapping using list of keys."""
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None

def vector_add(a, b):
    """Add two 3D vectors."""
    return [a[i] + b[i] for i in range(3)]

def vector_sub(a, b):
    """Subtract two 3D vectors."""
    return [a[i] - b[i] for i in range(3)]

def vector_scale(v, scale):
    """Scale a 3D vector."""
    return [v[i] * scale for i in range(3)]

def vector_cross(a, b):
    """Cross product of two 3D vectors."""
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]

def vector_length(v):
    """Length of a 3D vector."""
    return math.sqrt(sum(component * component for component in v))

def vector_normalize(v):
    """Normalize a 3D vector."""
    length = vector_length(v)
    if not length:
        return [0.0, 0.0, 0.0]
    return [component / length for component in v]

def joint_kind(name):
    """Classify joint type from name."""
    lower = (name or "").lower()
    if "xlap" in lower:
        return "xlap"
    if "tbutt" in lower:
        return "tbutt"
    if "lmiter" in lower:
        return "lmiter"
    return "other"

# =========================
# MAIN NUMBERING FUNCTION
# =========================

def run_numbering(
    timber_model, 
    Index, 
    RunExport, 
    OutputFolder,
    ModuleSizes="A:36,B:31,C:30,D:27,E:27,F:31",
    Density=500.0,
    BaseURL="https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data"
):
    """
    Main numbering and export function for timber beams.
    
    Args:
        timber_model: COMPAS TimberModel object
        Index: Index for info output (0-based)
        RunExport: Boolean to enable JSON/STL export
        OutputFolder: Path for export folder
        ModuleSizes: Module size string (e.g., "A:36,B:31,C:30")
        Density: Wood density in kg/m3
        BaseURL: Base URL for 3D model references
    """
    
    # =========================
    # INITIALIZATION
    # =========================
    debug_out = ""
    info_out = ""
    json_export_out = "Export non avviato (RunExport è False)."
    
    module_sizes = parse_module_sizes(ModuleSizes)
    module_labels = [m[0] for m in module_sizes]
    
    geom_out = {}  # Dynamic geometry outputs
    for label in module_labels:
        geom_out[label] = []

    try:
        idx = int(Index)
    except:
        idx = 0

    # =========================
    # QUICK GEOMETRY TEST
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
    # 1. BUILD GRAPH
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
    # 2. NODE DATA & BOUNDING BOX
    # =========================
    pts = {n: g.node_attributes(n, ['x', 'y', 'z']) for n in g.nodes()}

    min_x = min(p[0] for p in pts.values())
    max_x = max(p[0] for p in pts.values())
    min_y = min(p[1] for p in pts.values())
    max_y = max(p[1] for p in pts.values())

    # =========================
    # 3. SPATIAL GRID (dynamic based on module count)
    # =========================
    num_modules = len(module_sizes)
    nx = 3 if num_modules >= 3 else num_modules
    ny = 2 if num_modules > 3 else 1
    
    dx = (max_x - min_x) / nx if nx > 0 else 1.0
    dy = (max_y - min_y) / ny if ny > 0 else 1.0

    cells = []
    for i in range(nx):
        for j in range(ny):
            if len(cells) < num_modules:
                cx = min_x + dx * (i + 0.5)
                cy = min_y + dy * (j + 0.5)
                cells.append((cx, cy))

    # =========================
    # 4. SEEDS
    # =========================
    def dist2(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    seeds = {}
    for label, (cx, cy) in zip(module_labels, cells):
        seed = min(pts, key=lambda n: dist2(pts[n], (cx, cy)))
        seeds[label] = seed

    # =========================
    # 5. SPATIAL ASSIGNMENT
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
    # 6. CONSTRUCTIBLE GROWTH
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

            if best_candidate is not None:
                visited.add(best_candidate)
                order.append(best_candidate)
                frontier.append(best_candidate)
            else:
                break

        return order

    # =========================
    # 6B. GEOMETRIC HELPER FUNCTIONS
    # =========================
    def get_line_start(line):
        if hasattr(line, "start"): return line.start
        if hasattr(line, "start_point"): return line.start_point
        if hasattr(line, "point_at"): return line.point_at(0.0)
        return line[0]

    def get_line_end(line):
        if hasattr(line, "end"): return line.end
        if hasattr(line, "end_point"): return line.end_point
        if hasattr(line, "point_at"): return line.point_at(1.0)
        return line[1]

    def point_on_centerline(beam, t):
        line = beam.centerline
        try:
            return line.point_at(t)
        except:
            a = get_line_start(line)
            b = get_line_end(line)
            return type(a)(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t)

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
                d = (pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2 + (pa.z - pb.z) ** 2
                if d < best_d:
                    best_d = d
                    best_pa = pa
                    best_pb = pb
        return rg.Point3d((best_pa.x + best_pb.x) / 2.0, (best_pa.y + best_pb.y) / 2.0, (best_pa.z + best_pb.z) / 2.0)

    def parameter_on_centerline(beam, point):
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

    # =========================
    # 6C. SECTION, ORIENTATION & WEIGHT FUNCTIONS
    # =========================
    def get_beam_section(beam):
        for w_attr in ['width', 'w', 'b', 'breadth']:
            for h_attr in ['height', 'h', 'd', 'depth']:
                try:
                    w = getattr(beam, w_attr)
                    h = getattr(beam, h_attr)
                    if w and h: return float(w), float(h)
                except: continue
        try:
            sec = beam.section
            for w_attr in ['width', 'w', 'b', 'breadth']:
                for h_attr in ['height', 'h', 'd', 'depth']:
                    try:
                        w = getattr(sec, w_attr)
                        h = getattr(sec, h_attr)
                        if w and h: return float(w), float(h)
                    except: continue
        except: pass
        for container in ['blank', 'shape', 'profile']:
            try:
                obj = getattr(beam, container)
                w = getattr(obj, 'xsize', None) or getattr(obj, 'width', None)
                h = getattr(obj, 'ysize', None) or getattr(obj, 'height', None)
                if w and h: return float(w), float(h)
            except: continue
        return None, None

    def get_orientation_string(w, h):
        if w is None or h is None: return "?x?cm"
        w_cm = round(w * 100) if w < 1 else round(w)
        h_cm = round(h * 100) if h < 1 else round(h)
        return "{}x{}cm".format(int(w_cm), int(h_cm))

    def get_beam_weight(beam, length):
        w, h = get_beam_section(beam)
        if w is None or h is None: return 0.0
        w_m = w if w < 1 else w / 100.0
        h_m = h if h < 1 else h / 100.0
        volume = w_m * h_m * length
        return volume * Density

    # =========================
    # 6D. STL FUNCTIONS
    # =========================
    def compas_mesh_to_rg(compas_mesh):
        rg_mesh = rg.Mesh()
        vertices = list(compas_mesh.vertices())
        vertex_map = {}
        for i, v in enumerate(vertices):
            try: x, y, z = compas_mesh.vertex_coordinates(v)
            except:
                pt = compas_mesh.vertex_attributes(v, ['x', 'y', 'z'])
                x, y, z = pt
            rg_mesh.Vertices.Add(x, y, z)
            vertex_map[v] = i
        for face in compas_mesh.faces():
            fv = list(compas_mesh.face_vertices(face))
            if len(fv) == 3: rg_mesh.Faces.AddFace(vertex_map[fv[0]], vertex_map[fv[1]], vertex_map[fv[2]])
            elif len(fv) == 4: rg_mesh.Faces.AddFace(vertex_map[fv[0]], vertex_map[fv[1]], vertex_map[fv[2]], vertex_map[fv[3]])
        rg_mesh.Normals.ComputeNormals()
        rg_mesh.Compact()
        return rg_mesh

    def write_stl(rg_mesh, path):
        lines = ["solid beam"]
        rg_mesh.Normals.ComputeNormals()
        for i in range(rg_mesh.Faces.Count):
            face = rg_mesh.Faces[i]
            verts = rg_mesh.Vertices
            def write_tri(p0, p1, p2):
                ux = p1.X - p0.X; uy = p1.Y - p0.Y; uz = p1.Z - p0.Z
                vx = p2.X - p0.X; vy = p2.Y - p0.Y; vz = p2.Z - p0.Z
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                length = (nx**2 + ny**2 + nz**2) ** 0.5
                if length > 0: nx /= length; ny /= length; nz /= length
                lines.append("  facet normal {} {} {}".format(nx, ny, nz))
                lines.append("    outer loop\n      vertex {} {} {}\n      vertex {} {} {}\n      vertex {} {} {}\n    endloop\n  endfacet".format(p0.X,p0.Y,p0.Z, p1.X,p1.Y,p1.Z, p2.X,p2.Y,p2.Z))
            if face.IsTriangle: write_tri(verts[face.A], verts[face.B], verts[face.C])
            else:
                write_tri(verts[face.A], verts[face.B], verts[face.C])
                write_tri(verts[face.A], verts[face.C], verts[face.D])
        lines.append("endsolid beam")
        with open(path, 'w') as f: f.write("\n".join(lines))

    def save_stl(geometry, beam_id, beam_folder):
        stl_path = os.path.join(beam_folder, "{}.stl".format(beam_id))
        if hasattr(geometry, 'to_stl'):
            try:
                geometry.to_stl(stl_path)
                if os.path.exists(stl_path): return stl_path
            except: pass
        if hasattr(geometry, 'native_brep') or isinstance(geometry, rg.Brep):
            try:
                native = geometry.native_brep if hasattr(geometry, 'native_brep') else geometry
                meshp = rg.MeshingParameters.Default
                meshes = rg.Mesh.CreateFromBrep(native, meshp)
                if meshes:
                    joined = rg.Mesh()
                    for m in meshes: joined.Append(m)
                    write_stl(joined, stl_path)
                    return stl_path
            except: pass
        return None

    # =========================
    # 6E. LOCAL FRAME FUNCTION
    # =========================
    def get_beam_local_frame(beam):
        try:
            line = beam.centerline
            start = line.start if hasattr(line, "start") else get_line_start(line)
            end = line.end if hasattr(line, "end") else get_line_end(line)
            dx, dy, dz = end.x - start.x, end.y - start.y, end.z - start.z
            length = (dx**2 + dy**2 + dz**2) ** 0.5
            if length < 1e-10: return None
            x_axis = [dx/length, dy/length, dz/length]
            ref = [1.0, 0.0, 0.0] if abs(x_axis[2]) > 0.9 else [0.0, 0.0, 1.0]
            cx, cy, cz = x_axis[1]*ref[2] - x_axis[2]*ref[1], x_axis[2]*ref[0] - x_axis[0]*ref[2], x_axis[0]*ref[1] - x_axis[1]*ref[0]
            c_len = (cx**2 + cy**2 + cz**2) ** 0.5
            if c_len < 1e-10: return None
            z_axis = [cx/c_len, cy/c_len, cz/c_len]
            y_axis = [z_axis[1]*x_axis[2] - z_axis[2]*x_axis[1], z_axis[2]*x_axis[0] - z_axis[0]*x_axis[2], z_axis[0]*x_axis[1] - z_axis[1]*x_axis[0]]
            return {
                "origin": [rounded((start.x+end.x)/2.0), rounded((start.y+end.y)/2.0), rounded((start.z+end.z)/2.0)],
                "x_axis": [rounded(v) for v in x_axis], 
                "y_axis": [rounded(v) for v in y_axis], 
                "z_axis": [rounded(v) for v in z_axis]
            }
        except: 
            return None

    # =========================
    # 7. GENERATE BEAM OUTPUTS
    # =========================
    ordered_by_module = {}
    beam_label_by_guid = {}
    beam_index = 0

    for k in module_labels:
        ordered = connected_growth(seeds[k], groups[k])
        ordered_by_module[k] = ordered

        for i, node in enumerate(ordered):
            beam = timber_model.get_element(node)
            beam_id, module, display_name = sequential_identity(beam_index, module_sizes)
            
            rhino_geom = beam.geometry
            if hasattr(beam.geometry, "native_brep") and beam.geometry.native_brep:
                rhino_geom = beam.geometry.native_brep
            elif hasattr(beam.geometry, "native_mesh") and beam.geometry.native_mesh:
                rhino_geom = beam.geometry.native_mesh
            elif hasattr(beam.geometry, "to_rhino"):
                try: rhino_geom = beam.geometry.to_rhino()
                except: pass

            geom_out[k].append(rhino_geom)
            beam_label_by_guid[node] = beam_id
            beam_index += 1

    # =========================
    # 7B. JOINT STRUCTURE (for JSON metadata)
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
    # 9. DETAIL PROCESSING
    # =========================
    summary_by_category = {k: [] for k in module_labels}
    info_lines_master = []

    for k in module_labels:
        for node in ordered_by_module.get(k, []):
            name = beam_label_by_guid.get(node, "?")
            beam = timber_model.get_element(node)
            length = beam.centerline.length if hasattr(beam.centerline, 'length') else 0.0
            w, h = get_beam_section(beam)
            orientation = get_orientation_string(w, h)
            weight = get_beam_weight(beam, length)
            volume_m3 = (w if w < 1 else w / 100.0) * (h if h < 1 else h / 100.0) * length if (w and h) else 0.0

            full_info_string = "{} | L={:.2f}m | Sez={} | Vol={:.2f}cm3 | Peso={:.1f}kg".format(
                name, length, orientation, volume_m3 * 1_000_000, weight
            )
            summary_by_category[k].append(full_info_string)
            info_lines_master.append(full_info_string)

    def sort_key(line):
        match = re.match(r'([A-Z]+)(\d+)', line)
        return (match.group(1), int(match.group(2))) if match else (line, 0)

    info_list = sorted(info_lines_master, key=sort_key)
    info_out = info_list[idx] if (0 <= idx < len(info_list)) else (info_list[0] if info_list else "nessun beam")

    # =========================
    # 10B. GLOBAL POSITIONS FOR ALL BEAMS
    # =========================
    all_beams_positions = {}
    all_pts_list = list(pts.values())
    min_x3, max_x3 = min(p[0] for p in all_pts_list), max(p[0] for p in all_pts_list)
    min_y3, max_y3 = min(p[1] for p in all_pts_list), max(p[1] for p in all_pts_list)
    min_z3, max_z3 = min(p[2] for p in all_pts_list), max(p[2] for p in all_pts_list)
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
                "centerline_start": [rounded(s.x), rounded(s.y), rounded(s.z)], 
                "centerline_end": [rounded(e.x), rounded(e.y), rounded(e.z)],
                "midpoint": [rounded(px), rounded(py), rounded(pz)],
                "midpoint_normalized": [rounded((px - min_x3) / rx), rounded((py - min_y3) / ry), rounded((pz - min_z3) / rz)]
            }
        except:
            all_beams_positions[label] = {
                "guid": node, 
                "module": assignment.get(node, "?"),
                "midpoint": [rounded(px), rounded(py), rounded(pz)],
                "midpoint_normalized": [rounded((px - min_x3) / rx), rounded((py - min_y3) / ry), rounded((pz - min_z3) / rz)]
            }

    # =========================
    # 11 & 12. DYNAMIC EXPORT WITH FOLDER
    # =========================
    if RunExport and OutputFolder:
        output_folder = str(OutputFolder)
        global_structure_path = os.path.join(output_folder, "structure.json")
        json_files_created, stl_files_created, stl_errors = [], [], []

        beam_index = 0
        for k in module_labels:
            for node in ordered_by_module.get(k, []):
                beam = timber_model.get_element(node)
                beam_id, module, display_name = sequential_identity(beam_index, module_sizes)
                
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

                # Classify joints by type
                joint_details = []
                xlap, tbutt, lmiter = [], [], []
                for j_num in clean_joints:
                    j_type = joint_type_by_number.get(j_num, "")
                    kind = joint_kind(j_type)
                    
                    detail = {
                        "id": j_num,
                        "type": j_type,
                        "kind": kind,
                    }
                    joint_details.append(detail)
                    
                    if kind == 'xlap': xlap.append(j_num)
                    elif kind == 'tbutt': tbutt.append(j_num)
                    elif kind == 'lmiter': lmiter.append(j_num)

                beam_id_clean = clean_id(beam_id)
                beam_folder = os.path.join(output_folder, beam_id_clean)
                if not os.path.exists(beam_folder): 
                    os.makedirs(beam_folder)

                stl_result = save_stl(beam.geometry, beam_id_clean, beam_folder)
                if stl_result: 
                    stl_files_created.append(stl_result)
                else: 
                    stl_errors.append("Errore STL per {}".format(beam_id_clean))

                global_pos = all_beams_positions.get(beam_id, {})
                
                # Build beam JSON with improved joint structure
                beam_data = {
                    "beam ID": beam_id_clean, 
                    "name": display_name, 
                    "module": module,
                    "width (m)": rounded(w_m) if w_m else None, 
                    "height (m)": rounded(h_m) if h_m else None,
                    "length (m)": rounded(length, 2), 
                    "volume (cm³)": rounded(volume_m3 * 1_000_000, 2), 
                    "weight (kg)": rounded(weight, 2),
                    "local_frame": get_beam_local_frame(beam),
                    "connected_beams": sorted([
                        clean_id(beam_label_by_guid[nbr]) 
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
                        "lmiter": lmiter,
                        "details": joint_details
                    },
                    "3d_model": "{}/beams/{}/{}.stl".format(BaseURL.rstrip("/"), beam_id_clean, beam_id_clean)
                }

                json_path = os.path.join(beam_folder, "{}.json".format(beam_id_clean))
                with open(json_path, 'w') as f: 
                    json.dump(beam_data, f, indent=2)
                json_files_created.append(json_path)
                
                beam_index += 1

        # Build global structure file
        all_beams_list = []
        beam_index = 0
        for k in module_labels:
            for node in ordered_by_module.get(k, []):
                beam_id, module, _ = sequential_identity(beam_index, module_sizes)
                beam_id_clean = clean_id(beam_id)
                gpos = all_beams_positions.get(beam_id, {})
                all_beams_list.append({
                    "beam_id": beam_id_clean, 
                    "module": module,
                    "centerline_start": gpos.get("centerline_start"), 
                    "centerline_end": gpos.get("centerline_end"),
                    "midpoint": gpos.get("midpoint"), 
                    "midpoint_normalized": gpos.get("midpoint_normalized"),
                    "connected_beams": sorted([
                        clean_id(beam_label_by_guid[nbr]) 
                        for nbr in g.neighbors(node) 
                        if nbr in beam_label_by_guid
                    ])
                })
                beam_index += 1

        if not os.path.exists(output_folder): 
            os.makedirs(output_folder)
        
        structure_data = {
            "total_beams": len(all_beams_list), 
            "bounding_box": {
                "min": [rounded(min_x3), rounded(min_y3), rounded(min_z3)], 
                "max": [rounded(max_x3), rounded(max_y3), rounded(max_z3)]
            }, 
            "beams": all_beams_list
        }
        
        with open(global_structure_path, 'w') as f:
            json.dump(structure_data, f, indent=2)
        json_files_created.append(global_structure_path)

        json_export_out = "JSON: {} | STL: {} | Errori STL: {}".format(len(json_files_created), len(stl_files_created), len(stl_errors))
        if stl_errors: 
            json_export_out += "\n" + "\n".join(stl_errors[:5])

    # =========================
    # 13. RETURN (Dynamic based on module count)
    # =========================
    return_tuple = [debug_out, info_out, json_export_out]
    for label in module_labels:
        return_tuple.append(geom_out[label])
    
    return tuple(return_tuple)
