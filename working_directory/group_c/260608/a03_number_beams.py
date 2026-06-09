import os
import sys
import re
import json
import math
import Rhino.Geometry as rg
from collections import deque
from compas.datastructures import Graph

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

    # =========================
    # UTILITY VETTORI
    # =========================
    def vector_add(a, b): return [a[i] + b[i] for i in range(3)]
    def vector_sub(a, b): return [a[i] - b[i] for i in range(3)]
    def vector_scale(v, s): return [v[i] * s for i in range(3)]
    def vector_cross(a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    def vector_length(v): return math.sqrt(sum(c*c for c in v))
    def vector_normalize(v):
        l = vector_length(v)
        return [c/l for c in v] if l else [0.0, 0.0, 0.0]

    def unwrap_vector(v):
        """Gestisce vettori COMPAS annidati tipo {"dtype": "...", "data": [x,y,z]}"""
        if isinstance(v, dict):
            v = v.get("data", v)
        if isinstance(v, dict):
            return [float(v.get("x", 0.0)), float(v.get("y", 0.0)), float(v.get("z", 0.0))]
        return [float(c) for c in v]

    # =========================
    # FRAME PARSING (robusto)
    # =========================
    def get_beam_frame(beam):
        """Legge beam.frame con fallback multipli, restituisce dict con origin/x_axis/y_axis/z_axis"""
        try:
            frame = beam.frame
            # COMPAS Frame object (caso piu' comune in Grasshopper)
            if hasattr(frame, 'point') and hasattr(frame, 'xaxis'):
                origin = [float(frame.point.x), float(frame.point.y), float(frame.point.z)]
                x_axis = vector_normalize([float(frame.xaxis.x), float(frame.xaxis.y), float(frame.xaxis.z)])
                y_axis = vector_normalize([float(frame.yaxis.x), float(frame.yaxis.y), float(frame.yaxis.z)])
                z_axis = vector_cross(x_axis, y_axis)
                return {"origin": origin, "x_axis": x_axis, "y_axis": y_axis, "z_axis": z_axis}
            # dict-like (JSON gia' caricato)
            if isinstance(frame, dict):
                data = frame.get("data", frame)
                raw_origin = data.get("point") or data.get("origin")
                raw_x = data.get("xaxis") or data.get("x_axis")
                raw_y = data.get("yaxis") or data.get("y_axis")
                if raw_origin and raw_x and raw_y:
                    origin = unwrap_vector(raw_origin)
                    x_axis = vector_normalize(unwrap_vector(raw_x))
                    y_axis = vector_normalize(unwrap_vector(raw_y))
                    z_axis = vector_cross(x_axis, y_axis)
                    return {"origin": origin, "x_axis": x_axis, "y_axis": y_axis, "z_axis": z_axis}
        except:
            pass

        # Fallback: ricava il frame dalla centerline
        try:
            cl = beam.centerline
            start = cl.start if hasattr(cl, 'start') else cl.point_at(0.0)
            end = cl.end if hasattr(cl, 'end') else cl.point_at(1.0)
            sx, sy, sz = float(start.x), float(start.y), float(start.z)
            ex, ey, ez = float(end.x), float(end.y), float(end.z)
            origin = [(sx+ex)/2, (sy+ey)/2, (sz+ez)/2]
            x_axis = vector_normalize([ex-sx, ey-sy, ez-sz])
            ref = [1.0, 0.0, 0.0] if abs(x_axis[2]) > 0.9 else [0.0, 0.0, 1.0]
            z_axis = vector_normalize(vector_cross(x_axis, ref))
            y_axis = vector_normalize(vector_cross(z_axis, x_axis))
            return {"origin": origin, "x_axis": x_axis, "y_axis": y_axis, "z_axis": z_axis}
        except:
            pass

        return {"origin": [0,0,0], "x_axis": [1,0,0], "y_axis": [0,1,0], "z_axis": [0,0,1]}

    def get_centerline_points(beam):
        """Restituisce (start, end) come liste [x,y,z] usando frame+length o centerline"""
        try:
            frame = get_beam_frame(beam)
            length = float(beam.length)
            start = vector_sub(frame["origin"], vector_scale(frame["x_axis"], length / 2.0))
            end = vector_add(frame["origin"], vector_scale(frame["x_axis"], length / 2.0))
            return start, end
        except:
            pass
        try:
            cl = beam.centerline
            s = cl.start if hasattr(cl, 'start') else cl.point_at(0.0)
            e = cl.end if hasattr(cl, 'end') else cl.point_at(1.0)
            return [float(s.x), float(s.y), float(s.z)], [float(e.x), float(e.y), float(e.z)]
        except:
            return [0,0,0], [0,0,0]

    # =========================
    # TEST RAPIDO
    # =========================
    try:
        test_beam = list(timber_model.beams)[0]
        fr = get_beam_frame(test_beam)
        debug_out = "FRAME: origin={} x={} y={} z={}".format(
            [round(v,3) for v in fr["origin"]],
            [round(v,3) for v in fr["x_axis"]],
            [round(v,3) for v in fr["y_axis"]],
            [round(v,3) for v in fr["z_axis"]]
        )
    except Exception as e:
        debug_out = "ERRORE TEST: {}".format(e)

    # =========================
    # 1. COSTRUZIONE GRAFO
    # =========================
    g = Graph()

    for joint in timber_model.joints:
        ea, eb = joint.elements
        pa = ea.centerline.midpoint
        pb = eb.centerline.midpoint
        na = g.add_node(str(ea.guid), x=float(pa.x), y=float(pa.y), z=float(pa.z))
        nb = g.add_node(str(eb.guid), x=float(pb.x), y=float(pb.y), z=float(pb.z))
        g.add_edge(na, nb)

    pts = {n: g.node_attributes(n, ['x', 'y', 'z']) for n in g.nodes()}

    min_x = min(p[0] for p in pts.values())
    max_x = max(p[0] for p in pts.values())
    min_y = min(p[1] for p in pts.values())
    max_y = max(p[1] for p in pts.values())

    # =========================
    # 3. GRIGLIA 3x2
    # =========================
    nx = 3; ny = 2
    dx = (max_x - min_x) / nx
    dy = (max_y - min_y) / ny
    cells = []
    for i in range(nx):
        for j in range(ny):
            cells.append((min_x + dx*(i+0.5), min_y + dy*(j+0.5)))

    labels_keys = ["A", "B", "C", "D", "E", "F"]

    def dist2(a, b): return (a[0]-b[0])**2 + (a[1]-b[1])**2

    seeds = {}
    for key, (cx, cy) in zip(labels_keys, cells):
        seeds[key] = min(pts, key=lambda n: dist2(pts[n], (cx, cy)))

    assignment = {}
    groups = {k: [] for k in seeds}
    for node, p in pts.items():
        best_k = min(seeds, key=lambda k: dist2(p, pts[seeds[k]]))
        assignment[node] = best_k
        groups[best_k].append(node)

    # =========================
    # 6. CRESCITA CONNESSA
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
                        px,py,pz = pts[f]; nx2,ny2,nz2 = pts[nbr]
                        d = (px-nx2)**2+(py-ny2)**2+(pz-nz2)**2
                        if d < best_dist:
                            best_dist = d; best_candidate = nbr
            if best_candidate is None:
                remaining = list(group_set - visited)
                for r in remaining:
                    for v in visited:
                        px,py,pz = pts[v]; rx,ry,rz = pts[r]
                        d = (px-rx)**2+(py-ry)**2+(pz-rz)**2
                        if d < best_dist:
                            best_dist = d; best_candidate = r
            if best_candidate is None: break
            visited.add(best_candidate)
            order.append(best_candidate)
            frontier.append(best_candidate)
        return order

    # =========================
    # SEZIONE E PESO
    # =========================
    def get_beam_section(beam):
        try:
            w = float(beam.width)
            h = float(beam.height)
            if w and h: return w, h
        except: pass
        for w_attr in ['width','w','b','breadth']:
            for h_attr in ['height','h','d','depth']:
                try:
                    w = getattr(beam, w_attr)
                    h = getattr(beam, h_attr)
                    if w and h: return float(w), float(h)
                except: continue
        try:
            sec = beam.section
            for w_attr in ['width','w','b']:
                for h_attr in ['height','h','d']:
                    try:
                        w = getattr(sec, w_attr); h = getattr(sec, h_attr)
                        if w and h: return float(w), float(h)
                    except: continue
        except: pass
        return None, None

    def get_orientation_string(w, h):
        if w is None or h is None: return "?x?cm"
        w_cm = round(w*100) if w < 1 else round(w)
        h_cm = round(h*100) if h < 1 else round(h)
        return "{}x{}cm".format(int(w_cm), int(h_cm))

    WOOD_DENSITY = 500.0
    def get_beam_weight(beam, length):
        w, h = get_beam_section(beam)
        if w is None or h is None: return 0.0
        w_m = w if w < 1 else w/100.0
        h_m = h if h < 1 else h/100.0
        return w_m * h_m * length * WOOD_DENSITY

    # =========================
    # STL
    # =========================
    def facet_normal(a, b, c):
        return vector_normalize(vector_cross(vector_sub(b,a), vector_sub(c,a)))

    def beam_box_vertices(frame, length, width, height):
        origin = frame["origin"][:]
        ax = vector_scale(frame["x_axis"], length/2.0)
        ay = vector_scale(frame["y_axis"], width/2.0)
        az = vector_scale(frame["z_axis"], height/2.0)
        verts = []
        for sx in (-1,1):
            for sy in (-1,1):
                for sz in (-1,1):
                    p = origin[:]
                    p = vector_add(p, vector_scale(ax, sx))
                    p = vector_add(p, vector_scale(ay, sy))
                    p = vector_add(p, vector_scale(az, sz))
                    verts.append(p)
        return verts

    def write_box_stl(path, name, vertices):
        faces = [(0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5)]
        with open(path, 'w') as fp:
            fp.write("solid {}\n".format(name))
            for face in faces:
                tris = [(face[0],face[1],face[2]),(face[0],face[2],face[3])]
                for tri in tris:
                    a,b,c = (vertices[i] for i in tri)
                    n = facet_normal(a,b,c)
                    fp.write("  facet normal {:.9g} {:.9g} {:.9g}\n".format(*n))
                    fp.write("    outer loop\n")
                    for v in (a,b,c):
                        fp.write("      vertex {:.9g} {:.9g} {:.9g}\n".format(*v))
                    fp.write("    endloop\n  endfacet\n")
            fp.write("endsolid {}\n".format(name))

    def geometry_to_mesh(geometry):
        candidates = geometry if isinstance(geometry, (list,tuple)) else [geometry]
        all_verts, all_faces = [], []
        for candidate in candidates:
            if candidate is None: continue
            mesh = candidate
            if hasattr(candidate, 'to_mesh'):
                try: mesh = candidate.to_mesh()
                except: continue
            if hasattr(mesh, 'to_vertices_and_faces'):
                try:
                    verts, faces = mesh.to_vertices_and_faces()
                    offset = len(all_verts)
                    all_verts.extend([[float(c) for c in v] for v in verts])
                    all_faces.extend([[int(i)+offset for i in f] for f in faces])
                except: pass
        return (all_verts, all_faces) if all_verts else None

    def write_mesh_stl(path, name, vertices, faces):
        with open(path, 'w') as fp:
            fp.write("solid {}\n".format(name))
            for face in faces:
                tris = [face] if len(face)==3 else [(face[0],face[i],face[i+1]) for i in range(1,len(face)-1)]
                for tri in tris:
                    a,b,c = ([float(c) for c in vertices[i]] for i in tri)
                    n = facet_normal(a,b,c)
                    fp.write("  facet normal {:.9g} {:.9g} {:.9g}\n".format(*n))
                    fp.write("    outer loop\n")
                    for v in (a,b,c):
                        fp.write("      vertex {:.9g} {:.9g} {:.9g}\n".format(*v))
                    fp.write("    endloop\n  endfacet\n")
            fp.write("endsolid {}\n".format(name))

    def save_stl(beam, beam_id, beam_folder, frame, w, h, length):
        stl_path = os.path.join(beam_folder, "{}.stl".format(beam_id))
        mesh_data = geometry_to_mesh(beam.geometry)
        if mesh_data:
            write_mesh_stl(stl_path, beam_id, mesh_data[0], mesh_data[1])
            return stl_path
        geom = beam.geometry
        native = None
        if hasattr(geom, 'native_brep') and geom.native_brep:
            native = geom.native_brep
        elif isinstance(geom, rg.Brep):
            native = geom
        if native:
            try:
                meshes = rg.Mesh.CreateFromBrep(native, rg.MeshingParameters.Default)
                if meshes:
                    joined = rg.Mesh()
                    for m in meshes: joined.Append(m)
                    verts = [[joined.Vertices[i].X, joined.Vertices[i].Y, joined.Vertices[i].Z] for i in range(joined.Vertices.Count)]
                    faces = []
                    for i in range(joined.Faces.Count):
                        face = joined.Faces[i]
                        if face.IsTriangle:
                            faces.append([face.A, face.B, face.C])
                        else:
                            faces.append([face.A, face.B, face.C, face.D])
                    write_mesh_stl(stl_path, beam_id, verts, faces)
                    return stl_path
            except: pass
        if w and h and length:
            w_m = w if w < 1 else w/100.0
            h_m = h if h < 1 else h/100.0
            verts = beam_box_vertices(frame, length, w_m, h_m)
            write_box_stl(stl_path, beam_id, verts)
            return stl_path
        return None

    # =========================
    # JOINT UTILITIES
    # =========================
    def point_on_centerline(beam, t):
        start, end = get_centerline_points(beam)
        return [start[i] + (end[i]-start[i])*t for i in range(3)]

    def joint_midpoint(ea, eb):
        best_pa, best_pb, best_d = None, None, 1e99
        samples = 20
        for i in range(samples+1):
            pa = point_on_centerline(ea, float(i)/samples)
            for j in range(samples+1):
                pb = point_on_centerline(eb, float(j)/samples)
                d = sum((pa[k]-pb[k])**2 for k in range(3))
                if d < best_d:
                    best_d = d; best_pa = pa; best_pb = pb
        return [(best_pa[k]+best_pb[k])/2.0 for k in range(3)]

    # =========================
    # 7. GENERAZIONE OUTPUT
    # =========================
    geom_out = {k: [] for k in labels_keys}
    ordered_by_module = {}
    beam_label_by_guid = {}

    for k in seeds:
        ordered = connected_growth(seeds[k], groups[k])
        ordered_by_module[k] = ordered
        for i, node in enumerate(ordered):
            beam = timber_model.get_element(node)
            name = "{}{}".format(k, i+1)
            rhino_geom = beam.geometry
            if hasattr(beam.geometry, 'native_brep') and beam.geometry.native_brep:
                rhino_geom = beam.geometry.native_brep
            elif hasattr(beam.geometry, 'native_mesh') and beam.geometry.native_mesh:
                rhino_geom = beam.geometry.native_mesh
            elif hasattr(beam.geometry, 'to_rhino'):
                try: rhino_geom = beam.geometry.to_rhino()
                except: pass
            geom_out[k].append(rhino_geom)
            beam_label_by_guid[node] = name

    # =========================
    # 7B. JOINTS
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
        jp = joint_midpoint(ea, eb)
        beam_joints[ga].append(joint_number)
        beam_joints[gb].append(joint_number)

    A_geom_out = geom_out["A"]
    B_geom_out = geom_out["B"]
    C_geom_out = geom_out["C"]
    D_geom_out = geom_out["D"]
    E_geom_out = geom_out["E"]
    F_geom_out = geom_out["F"]

    # =========================
    # 9. INFO
    # =========================
    info_lines_master = []
    for k in labels_keys:
        for node in ordered_by_module.get(k, []):
            name = beam_label_by_guid.get(node, "?")
            beam = timber_model.get_element(node)
            try: length = float(beam.length)
            except:
                s, e = get_centerline_points(beam)
                length = vector_length(vector_sub(e, s))
            w, h = get_beam_section(beam)
            orientation = get_orientation_string(w, h)
            weight = get_beam_weight(beam, length)
            vol = ((w if w<1 else w/100.0) * (h if h<1 else h/100.0) * length * 1e6) if (w and h) else 0.0
            info_lines_master.append("{} | L={:.2f}m | Sez={} | Vol={:.2f}cm3 | Peso={:.1f}kg".format(
                name, length, orientation, vol, weight))

    def sort_key(line):
        m = re.match(r'([A-Z]+)(\d+)', line)
        return (m.group(1), int(m.group(2))) if m else (line, 0)

    info_list = sorted(info_lines_master, key=sort_key)
    info_out = info_list[idx] if (0 <= idx < len(info_list)) else (info_list[0] if info_list else "nessun beam")

    # =========================
    # 10B. POSIZIONI GLOBALI
    # =========================
    all_pts_list = list(pts.values())
    min_x3, max_x3 = min(p[0] for p in all_pts_list), max(p[0] for p in all_pts_list)
    min_y3, max_y3 = min(p[1] for p in all_pts_list), max(p[1] for p in all_pts_list)
    min_z3, max_z3 = min(p[2] for p in all_pts_list), max(p[2] for p in all_pts_list)
    rx = max_x3-min_x3 or 1.0; ry = max_y3-min_y3 or 1.0; rz = max_z3-min_z3 or 1.0

    all_beams_positions = {}
    for node in g.nodes():
        label = beam_label_by_guid.get(node, node)
        px, py, pz = pts[node]
        beam = timber_model.get_element(node)
        s, e = get_centerline_points(beam)
        all_beams_positions[label] = {
            "guid": node,
            "module": assignment.get(node, "?"),
            "centerline_start": [round(v,4) for v in s],
            "centerline_end": [round(v,4) for v in e],
            "midpoint": [round(px,4), round(py,4), round(pz,4)],
            "midpoint_normalized": [round((px-min_x3)/rx,4), round((py-min_y3)/ry,4), round((pz-min_z3)/rz,4)]
        }

    # =========================
    # 11 & 12. EXPORT
    # =========================
    if RunExport and OutputFolder:
        output_folder = str(OutputFolder)
        if not os.path.exists(output_folder): os.makedirs(output_folder)
        global_structure_path = os.path.join(output_folder, "structure.json")
        json_files_created, stl_files_created, stl_errors = [], [], []

        for k in labels_keys:
            for node in ordered_by_module.get(k, []):
                name = beam_label_by_guid.get(node, "?")
                beam = timber_model.get_element(node)
                try: length = float(beam.length)
                except:
                    s, e = get_centerline_points(beam)
                    length = vector_length(vector_sub(e, s))

                w, h = get_beam_section(beam)
                w_m = (w if w<1 else w/100.0) if w else None
                h_m = (h if h<1 else h/100.0) if h else None
                weight = get_beam_weight(beam, length)
                volume_m3 = w_m * h_m * length if (w_m and h_m) else 0.0

                frame = get_beam_frame(beam)

                joints_list = beam_joints.get(node, [])
                seen, clean_joints = set(), []
                for j_num in joints_list:
                    if j_num not in seen:
                        clean_joints.append(j_num); seen.add(j_num)

                xlap, tbutt, lmiter = [], [], []
                for j_num in clean_joints:
                    j_type = joint_type_by_number.get(j_num, "")
                    if 'XLap' in j_type: xlap.append(j_num)
                    elif 'TButt' in j_type: tbutt.append(j_num)
                    elif 'LMiter' in j_type: lmiter.append(j_num)

                beam_id = name.lower()
                beam_folder = os.path.join(output_folder, beam_id)
                if not os.path.exists(beam_folder): os.makedirs(beam_folder)

                stl_result = save_stl(beam, beam_id, beam_folder, frame, w, h, length)
                if stl_result: stl_files_created.append(stl_result)
                else: stl_errors.append("Errore STL per {}".format(beam_id))

                global_pos = all_beams_positions.get(name, {})
                beam_data = {
                    "beam ID": beam_id,
                    "name": name,
                    "module": k,
                    "width (m)": round(w_m, 4) if w_m else None,
                    "height (m)": round(h_m, 4) if h_m else None,
                    "length (m)": round(length, 4),
                    "volume (cm3)": round(volume_m3 * 1e6, 2),
                    "weight (kg)": round(weight, 2),
                    "local_frame": {
                        "origin": [round(v,4) for v in frame["origin"]],
                        "x_axis": [round(v,4) for v in frame["x_axis"]],
                        "y_axis": [round(v,4) for v in frame["y_axis"]],
                        "z_axis": [round(v,4) for v in frame["z_axis"]],
                    },
                    "connected_beams": [beam_label_by_guid[nbr].lower() for nbr in g.neighbors(node) if nbr in beam_label_by_guid],
                    "global_position": {
                        "centerline_start": global_pos.get("centerline_start"),
                        "centerline_end": global_pos.get("centerline_end"),
                        "midpoint": global_pos.get("midpoint"),
                        "midpoint_normalized": global_pos.get("midpoint_normalized")
                    },
                    "joints": {
                        "all": clean_joints if clean_joints else "-",
                        "xlap": xlap if xlap else "-",
                        "tbutt": tbutt if tbutt else "-",
                        "lmiter": lmiter if lmiter else "-"
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
                beam_id = label.lower()
                gpos = all_beams_positions.get(label, {})
                all_beams_list.append({
                    "beam_id": beam_id,
                    "module": k,
                    "centerline_start": gpos.get("centerline_start"),
                    "centerline_end": gpos.get("centerline_end"),
                    "midpoint": gpos.get("midpoint"),
                    "midpoint_normalized": gpos.get("midpoint_normalized"),
                    "connected_beams": [beam_label_by_guid[nbr].lower() for nbr in g.neighbors(node) if nbr in beam_label_by_guid]
                })

        with open(global_structure_path, 'w') as f:
            json.dump({
                "total_beams": len(all_beams_list),
                "bounding_box": {
                    "min": [round(min_x3,4), round(min_y3,4), round(min_z3,4)],
                    "max": [round(max_x3,4), round(max_y3,4), round(max_z3,4)]
                },
                "beams": all_beams_list
            }, f, indent=2)
        json_files_created.append(global_structure_path)

        json_export_out = "JSON: {} | STL: {} | Errori STL: {}".format(
            len(json_files_created), len(stl_files_created), len(stl_errors))
        if stl_errors: json_export_out += "\n" + "\n".join(stl_errors[:5])

    return (
        debug_out,
        info_out,
        json_export_out,
        A_geom_out,
        B_geom_out,
        C_geom_out,
        D_geom_out,
        E_geom_out,
        F_geom_out
    )
