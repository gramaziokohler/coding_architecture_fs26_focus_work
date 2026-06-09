import os
import sys
import re
import json
import math
import Rhino.Geometry as rg
from collections import deque, defaultdict
from compas.datastructures import Graph

# =========================
# UTILITY FUNCTIONS (DA ESPORTER)
# =========================

def rounded(value, digits=4):
    """Round value or list."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [rounded(v, digits) for v in value]
    return round(float(value), digits)

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
    """Parse frame data (from beam.frame)."""
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

def point_data(value):
    """Extract point data from various formats."""
    if not value:
        return None
    if isinstance(value, dict):
        return value.get("data")
    return value

def joint_kind(name):
    """Classify joint type."""
    lower = (name or "").lower()
    if "xlap" in lower:
        return "xlap"
    if "tbutt" in lower:
        return "tbutt"
    if "lmiter" in lower:
        return "lmiter"
    return "other"

# =========================
# GET BEAM LOCAL FRAME (MIGLIORATO)
# =========================

def get_beam_local_frame(beam):
    """Extract local frame from beam.frame or centerline."""
    try:
        # PRIMO: Try beam.frame se esiste
        if hasattr(beam, "frame") and beam.frame:
            try:
                return frame_from_data(beam.frame)
            except:
                pass
        
        # SECONDO: Calcola da centerline
        line = beam.centerline
        
        # Get start/end
        if hasattr(line, "start_point"):
            start = line.start_point
            end = line.end_point
        elif hasattr(line, "start"):
            start = line.start
            end = line.end
        elif hasattr(line, "PointAtStart"):
            start = line.PointAtStart
            end = line.PointAtEnd
        else:
            return None
        
        # Vector along centerline
        dx = end.x - start.x
        dy = end.y - start.y
        dz = end.z - start.z
        length = (dx**2 + dy**2 + dz**2) ** 0.5
        
        if length < 1e-10:
            return None
        
        # X-axis normalizz
        x_axis = [dx/length, dy/length, dz/length]
        
        # Reference per Z-axis
        ref = [1.0, 0.0, 0.0] if abs(x_axis[2]) > 0.9 else [0.0, 0.0, 1.0]
        
        # Z-axis = cross(x_axis, ref)
        z_axis = vector_cross(x_axis, ref)
        z_axis = vector_normalize(z_axis)
        
        if not z_axis or vector_length(z_axis) < 0.001:
            z_axis = [0.0, 0.0, 1.0]
        
        # Y-axis = cross(z_axis, x_axis)
        y_axis = vector_cross(z_axis, x_axis)
        y_axis = vector_normalize(y_axis)
        
        # Origin nel midpoint
        origin = [(start.x + end.x) / 2.0, (start.y + end.y) / 2.0, (start.z + end.z) / 2.0]
        
        return {
            "origin": [rounded(v) for v in origin],
            "x_axis": [rounded(v) for v in x_axis],
            "y_axis": [rounded(v) for v in y_axis],
            "z_axis": [rounded(v) for v in z_axis],
            "length": rounded(length),
            "centerline_start": [rounded(start.x), rounded(start.y), rounded(start.z)],
            "centerline_end": [rounded(end.x), rounded(end.y), rounded(end.z)]
        }
    except Exception as e:
        return None

# =========================
# GET JOINT IN LOCAL COORDS
# =========================

def get_joint_local_position(joint, frame_a, frame_b):
    """Get joint position in local coordinate systems."""
    try:
        # Joint point
        if hasattr(joint, "point"):
            jp = joint.point
        elif hasattr(joint, "location"):
            jp = joint.location
        elif hasattr(joint, "frame"):
            jp = joint.frame.origin if hasattr(joint.frame, "origin") else joint.frame
        else:
            return None
        
        joint_point = [jp.x if hasattr(jp, 'x') else jp[0],
                       jp.y if hasattr(jp, 'y') else jp[1],
                       jp.z if hasattr(jp, 'z') else jp[2]]
        
        # Local coords in frame A
        local_a = None
        if frame_a:
            # Vector da origin a joint
            vec = vector_sub(joint_point, frame_a["origin"])
            local_a = {
                "distance_along_x": rounded(sum(vec[i] * frame_a["x_axis"][i] for i in range(3))),
                "offset_y": rounded(sum(vec[i] * frame_a["y_axis"][i] for i in range(3))),
                "offset_z": rounded(sum(vec[i] * frame_a["z_axis"][i] for i in range(3)))
            }
        
        # Local coords in frame B
        local_b = None
        if frame_b:
            vec = vector_sub(joint_point, frame_b["origin"])
            local_b = {
                "distance_along_x": rounded(sum(vec[i] * frame_b["x_axis"][i] for i in range(3))),
                "offset_y": rounded(sum(vec[i] * frame_b["y_axis"][i] for i in range(3))),
                "offset_z": rounded(sum(vec[i] * frame_b["z_axis"][i] for i in range(3)))
            }
        
        return {
            "global": [rounded(v) for v in joint_point],
            "local_frame_a": local_a,
            "local_frame_b": local_b
        }
    except:
        return None

# =========================
# MAIN NUMBERING FUNCTION
# =========================

def run_numbering(timber_model, Index, RunExport, OutputFolder):
    debug_out = ""
    info_out = ""
    json_export_out = "Export non avviato (RunExport è False)."
    
    A_geom_out, B_geom_out, C_geom_out = [], [], []
    D_geom_out, E_geom_out, F_geom_out = [], [], []
    
    try:
        idx = int(Index)
    except:
        idx = 0
    
    # TEST GEOMETRIA
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
    
    # =========================
    # 3. GRIGLIA 3x2 = 6 MODULI
    # =========================
    nx, ny = 3, 2
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
    # FUNZIONI GEOMETRICHE
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
    # SEZIONE, ORIENTAMENTO, PESO
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
    
    WOOD_DENSITY = 500
    def get_beam_weight(beam, length):
        w, h = get_beam_section(beam)
        if w is None or h is None: return 0.0
        w_m = w if w < 1 else w / 100.0
        h_m = h if h < 1 else h / 100.0
        volume = w_m * h_m * length
        return volume * WOOD_DENSITY
    
    # =========================
    # STL EXPORT
    # =========================
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
    # 7. GENERAZIONE OUTPUT BEAMS
    # =========================
    geom = {k: [] for k in seeds}
    ordered_by_module = {}
    beam_label_by_guid = {}
    beam_frames = {}
    
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
                try: rhino_geom = beam.geometry.to_rhino()
                except: pass
            
            geom[k].append(rhino_geom)
            beam_label_by_guid[node] = name
            beam_frames[node] = get_beam_local_frame(beam)
    
    # =========================
    # 7B. CO-GIUNTI CON POSIZIONI LOCALI
    # =========================
    joint_number_by_pair = {}
    beam_joints = {node: [] for node in g.nodes()}
    joint_type_by_number = {}
    joint_local_pos = {}
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
        frame_a = beam_frames.get(ga)
        frame_b = beam_frames.get(gb)
        
        # Posizioni locali
        local_pos = get_joint_local_position(joint, frame_a, frame_b)
        joint_local_pos[joint_number] = local_pos
        
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
    # 10. POSIZIONI GLOBALI
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
        frame = beam_frames.get(node)
        
        try:
            cl = beam.centerline
            s, e = get_line_start(cl), get_line_end(cl)
            
            all_beams_positions[label] = {
                "guid": node,
                "module": assignment.get(node, "?"),
                "centerline_start": [rounded(s.x), rounded(s.y), rounded(s.z)],
                "centerline_end": [rounded(e.x), rounded(e.y), rounded(e.z)],
                "midpoint": [rounded(px), rounded(py), rounded(pz)],
                "midpoint_normalized": [rounded((px - min_x3) / rx), rounded((py - min_y3) / ry), rounded((pz - min_z3) / rz)],
                "local_frame": frame
            }
        except:
            all_beams_positions[label] = {
                "guid": node,
                "module": assignment.get(node, "?"),
                "midpoint": [rounded(px), rounded(py), rounded(pz)],
                "midpoint_normalized": [rounded((px - min_x3) / rx), rounded((py - min_y3) / ry), rounded((pz - min_z3) / rz)],
                "local_frame": frame
            }
    
    # =========================
    # 11 & 12. EXPORT CON FRAME LOCALE E POSIZIONI JOINT
    # =========================
    if RunExport and OutputFolder:
        output_folder = str(OutputFolder)
        global_structure_path = os.path.join(output_folder, "structure.json")
        json_files_created, stl_files_created, stl_errors = [], [], []
        
        for k in labels_keys:
            for node in ordered_by_module.get(k, []):
                name = beam_label_by_guid.get(node, "?")
                beam = timber_model.get_element(node)
                try: length = beam.centerline.length
                except: length = 0.0
                
                w, h = get_beam_section(beam)
                w_m = w if (w is not None and w < 1) else (w / 100.0 if w is not None else None)
                h_m = h if (h is not None and h < 1) else (h / 100.0 if h is not None else None)
                weight = get_beam_weight(beam, length)
                volume_m3 = w_m * h_m * length if (w_m and h_m) else 0.0
                
                joints_list = sorted(beam_joints.get(node, []), key=lambda item: item[0])
                seen, clean_joints = set(), []
                for param, j_num in joints_list:
                    if j_num not in seen: clean_joints.append(j_num); seen.add(j_num)
                
                xlap, tbutt, lmiter = [], [], []
                for j_num in clean_joints:
                    j_type = joint_type_by_number.get(j_num, "")
                    if j_type == 'XLapJoint': xlap.append(j_num)
                    elif j_type == 'TButtJoint': tbutt.append(j_num)
                    elif j_type == 'LMiterJoint': lmiter.append(j_num)
                
                beam_id = name.lower()
                beam_folder = os.path.join(output_folder, beam_id)
                if not os.path.exists(beam_folder): os.makedirs(beam_folder)
                
                stl_result = save_stl(beam.geometry, beam_id, beam_folder)
                if stl_result: stl_files_created.append(stl_result)
                else: stl_errors.append("Errore STL per {}".format(beam_id))
                
                global_pos = all_beams_positions.get(name, {})
                frame = global_pos.get("local_frame")
                
                # Joint details con posizioni locali
                joint_details = []
                for j_num in clean_joints:
                    joint_details.append({
                        "id": j_num,
                        "type": joint_type_by_number.get(j_num, ""),
                        "position": joint_local_pos.get(j_num, {})
                    })
                
                beam_data = {
                    "beam ID": beam_id,
                    "name": name,
                    "module": k,
                    "width (m)": rounded(w_m, 4) if w_m else None,
                    "height (m)": rounded(h_m, 4) if h_m else None,
                    "length (m)": rounded(length, 2),
                    "volume (cm³)": rounded(volume_m3 * 1_000_000, 2),
                    "weight (kg)": rounded(weight, 2),
                    "local_frame": frame,
                    "connected_beams": [beam_label_by_guid[nbr].lower() for nbr in g.neighbors(node) if nbr in beam_label_by_guid],
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
                    "3d_model": "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data/beams/{}/{}.stl".format(beam_id, beam_id)
                }
                
                json_path = os.path.join(beam_folder, "{}.json".format(beam_id))
                with open(json_path, 'w') as f: json.dump(beam_data, f, indent=2)
                json_files_created.append(json_path)
        
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
                    "connected_beams": [beam_label_by_guid[nbr].lower() for nbr in g.neighbors(node) if nbr in beam_label_by_guid]
                })
        
        if not os.path.exists(output_folder): os.makedirs(output_folder)
        with open(global_structure_path, 'w') as f:
            json.dump({
                "total_beams": len(all_beams_list),
                "bounding_box": {
                    "min": [rounded(min_x3), rounded(min_y3), rounded(min_z3)],
                    "max": [rounded(max_x3), rounded(max_y3), rounded(max_z3)]
                },
                "beams": all_beams_list
            }, f, indent=2)
        json_files_created.append(global_structure_path)
        
        json_export_out = "JSON: {} | STL: {} | Errori STL: {}".format(
            len(json_files_created), len(stl_files_created), len(stl_errors)
        )
        if stl_errors: json_export_out += "\n" + "\n".join(stl_errors[:5])
    
    # =========================
    # 13. RETURN FINALE
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
