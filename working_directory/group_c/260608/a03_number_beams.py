# venv: ca-fs26-focus-work
# keyword: timber-labels, json-export, stl-generation
import Rhino.Geometry as rg
from compas.datastructures import Graph
import re
import json
import os

def run_labeling(timber_model, Index):
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
        debug_out = "ERRORE: {}".format(e)

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
            cells.append((min_x + dx * (i + 0.5), min_y + dy * (j + 0.5)))

    labels_keys = ["A", "B", "C", "D", "E", "F"]

    # =========================
    # 4. SEEDS
    # =========================
    def dist2(a, b): return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    seeds = {}
    for key, (cx, cy) in zip(labels_keys, cells):
        seeds[key] = min(pts, key=lambda n: dist2(pts[n], (cx, cy)))

    # =========================
    # 5. ASSEGNAZIONE SPAZIALE
    # =========================
    assignment = {}
    groups = {k: [] for k in seeds}
    for node, p in pts.items():
        best_k, best_d = None, 1e99
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
        visited, order, frontier = set([seed]), [seed], [seed]
        while len(order) < len(group_set):
            best_candidate, best_dist = None, 1e99
            for f in frontier:
                for nbr in g.neighbors(f):
                    if nbr in group_set and nbr not in visited:
                        px, py, pz = pts[f]
                        nx2, ny2, nz2 = pts[nbr]
                        d = (px - nx2) ** 2 + (py - ny2) ** 2 + (pz - nz2) ** 2
                        if d < best_dist: best_dist, best_candidate = d, nbr
            if best_candidate is None:
                for r in list(group_set - visited):
                    for v in visited:
                        d = (pts[v][0]-pts[r][0])**2 + (pts[v][1]-pts[r][1])**2 + (pts[v][2]-pts[r][2])**2
                        if d < best_dist: best_dist, best_candidate = d, r
            visited.add(best_candidate)
            order.append(best_candidate)
            frontier.append(best_candidate)
        return order

    # =========================
    # 6B. FUNZIONI GEOMETRICHE
    # =========================
    def get_line_start(line):
        return line.start if hasattr(line, "start") else (line.start_point if hasattr(line, "start_point") else line[0])
    def get_line_end(line):
        return line.end if hasattr(line, "end") else (line.end_point if hasattr(line, "end_point") else line[1])

    def point_on_centerline(beam, t):
        line = beam.centerline
        try: return line.point_at(t)
        except:
            a, b = get_line_start(line), get_line_end(line)
            return type(a)(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t)

    def joint_point_from_beams(ea, eb):
        best_pa, best_pb, best_d = None, None, 1e99
        samples = 25
        for i in range(samples + 1):
            ta = float(i) / samples
            pa = point_on_centerline(ea, ta)
            for j in range(samples + 1):
                tb = float(j) / samples
                pb = point_on_centerline(eb, tb)
                d = (pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2 + (pa.z - pb.z) ** 2
                if d < best_d: best_d, best_pa, best_pb = d, pa, pb
        return rg.Point3d((best_pa.x + best_pb.x) / 2.0, (best_pa.y + best_pb.y) / 2.0, (best_pa.z + best_pb.z) / 2.0)

    def parameter_on_centerline(beam, point):
        best_t, best_d = 0.0, 1e99
        samples = 50
        for i in range(samples + 1):
            t = float(i) / samples
            p = point_on_centerline(beam, t)
            d = (p.x - point.X) ** 2 + (p.y - point.Y) ** 2 + (p.z - point.Z) ** 2
            if d < best_d: best_d, best_t = d, t
        return best_t

    # =========================
    # 6C. SEZIONE, ORIENTAMENTO, PESO
    # =========================
    def get_beam_section(beam):
        for w_attr in ['width', 'w', 'b', 'breadth']:
            for h_attr in ['height', 'h', 'd', 'depth']:
                try:
                    w, h = getattr(beam, w_attr), getattr(beam, h_attr)
                    if w and h: return float(w), float(h)
                except: continue
        return None, None

    def get_orientation_string(w, h):
        if w is None or h is None: return "?x?cm"
        return "{}x{}cm".format(int(round(w * 100) if w < 1 else round(w)), int(round(h * 100) if h < 1 else round(h)))

    def get_beam_weight(beam, length):
        w, h = get_beam_section(beam)
        if w is None or h is None: return 0.0
        return (w if w < 1 else w / 100.0) * (h if h < 1 else h / 100.0) * length * 500

    # =========================
    # 6D. FUNZIONI STL
    # =========================
    def compas_mesh_to_rg(compas_mesh):
        rg_mesh = rg.Mesh()
        vertex_map = {}
        for i, v in enumerate(compas_mesh.vertices()):
            try: x, y, z = compas_mesh.vertex_coordinates(v)
            except: x, y, z = compas_mesh.vertex_attributes(v, ['x', 'y', 'z'])
            rg_mesh.Vertices.Add(x, y, z)
            vertex_map[v] = i
        for face in compas_mesh.faces():
            fv = list(compas_mesh.face_vertices(face))
            if len(fv) == 3: rg_mesh.Faces.AddFace(vertex_map[fv[0]], vertex_map[fv[1]], vertex_map[fv[2]])
            elif len(fv) == 4: rg_mesh.Faces.AddFace(vertex_map[fv[0]], vertex_map[fv[1]], vertex_map[fv[2]], vertex_map[fv[3]])
        rg_mesh.Normals.ComputeNormals()
        return rg_mesh

    def write_stl(rg_mesh, path):
        lines = ["solid beam"]
        rg_mesh.Normals.ComputeNormals()
        for i in range(rg_mesh.Faces.Count):
            face = rg_mesh.Faces[i]
            verts = rg_mesh.Vertices
            def write_tri(p0, p1, p2):
                ux, uy, uz = p1.X - p0.X, p1.Y - p0.Y, p1.Z - p0.Z
                vx, vy, vz = p2.X - p0.X, p2.Y - p0.Y, p2.Z - p0.Z
                nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
                length = (nx**2 + ny**2 + nz**2) ** 0.5
                if length > 0: nx /= length; ny /= length; nz /= length
                lines.append("  facet normal {} {} {}\n    outer loop\n      vertex {} {} {}\n      vertex {} {} {}\n      vertex {} {} {}\n    endloop\n  endfacet".format(nx, ny, nz, p0.X, p0.Y, p0.Z, p1.X, p1.Y, p1.Z, p2.X, p2.Y, p2.Z))
            write_tri(verts[face.A], verts[face.B], verts[face.C])
            if not face.IsTriangle: write_tri(verts[face.A], verts[face.C], verts[face.D])
        lines.append("endsolid beam")
        with open(path, 'w') as f: f.write("\n".join(lines))

    # ====================================================
    # 7. GENERAZIONE OUTPUT BEAMS (CENTRATE IN ASSE SUL TOP)
    # ====================================================
    geom = {k: [] for k in seeds}
    ordered_by_module = {}
    beam_label_by_guid = {}

    punti_scritte_out = []
    piani_scritte_out = []
    nomi_scritte_out = []

    for k in seeds:
        ordered = connected_growth(seeds[k], groups[k])
        ordered_by_module[k] = ordered

        for i, node in enumerate(ordered):
            beam = timber_model.get_element(node)
            number = i + 1
            name = "{}{}".format(k, number)
            geom[k].append(beam.geometry)
            beam_label_by_guid[node] = name

            w, h = get_beam_section(beam)
            local_frame = get_beam_local_frame(beam)
            dim_h = 0.14 if h is None else (h if h < 1.0 else h / 100.0)

            if local_frame:
                origine_centro = rg.Point3d(*local_frame["origin"])
                asse_x = rg.Vector3d(*local_frame["x_axis"])
                asse_z = rg.Vector3d(*local_frame["z_axis"])
                
                # Spostamento in asse lungo Z locale di metà altezza
                punto_top = origine_centro + (asse_z * (dim_h / 2.0))
                # Piano antispecchio ottimizzato
                piano_scritta = rg.Plane(punto_top, asse_x, asse_z)
            else:
                mx, my, mz = pts[node]
                punto_top = rg.Point3d(mx, my, mz + dim_h / 2.0)
                piano_scritta = rg.Plane.WorldXY
                piano_scritta.Origin = punto_top

            punti_scritte_out.append(punto_top)
            piani_scritte_out.append(piano_scritta)
            nomi_scritte_out.append(name)

    # =========================
    # 7B. JOINTS GLOBALI
    # =========================
    joint_number_by_pair = {}
    beam_joints = {node: [] for node in g.nodes()}
    joint_type_by_number = {}
    joint_points_out, joint_labels_out, joint_textdots_out = [], [], []

    counter = 1
    for joint in timber_model.joints:
        ea, eb = joint.elements
        ga, gb = str(ea.guid), str(eb.guid)
        pair_key = tuple(sorted([ga, gb]))
        is_new_joint = False
        if pair_key not in joint_number_by_pair:
            joint_number = "{:02d}".format(counter)
            joint_number_by_pair[pair_key] = joint_number
            joint_type_by_number[joint_number] = type(joint).__name__
            counter += 1
            is_new_joint = True
        else:
            joint_number = joint_number_by_pair[pair_key]

        jp = joint_point_from_beams(ea, eb)
        beam_joints[ga].append((parameter_on_centerline(ea, jp), joint_number))
        beam_joints[gb].append((parameter_on_centerline(eb, jp), joint_number))

        if is_new_joint:
            joint_points_out.append(jp)
            joint_labels_out.append(joint_number)
            joint_textdots_out.append(rg.TextDot(joint_number, jp))

    # =========================
    # 9. REPORT INFO & JSON DETTAGLIATI
    # =========================
    try: idx = int(Index)
    except: idx = 0

    summary_by_category = {k: [] for k in labels_keys}
    info_lines_master = []

    for k in labels_keys:
        for node in ordered_by_module.get(k, []):
            name = beam_label_by_guid.get(node, "?")
            beam = timber_model.get_element(node)
            try: length = beam.centerline.length
            except: length = 0.0
            w, h = get_beam_section(beam)
            full_info_string = "{} | L={:.2f}m | Sez={} | Peso={:.1f}kg".format(name, length, get_orientation_string(w, h), get_beam_weight(beam, length))
            summary_by_category[k].append(full_info_string)
            info_lines_master.append(full_info_string)

    def sort_key(line):
        match = re.match(r'([A-Z]+)(\d+)', line)
        return (match.group(1), int(match.group(2))) if match else (line, 0)

    info_list = sorted(info_lines_master, key=sort_key)
    info_out = info_list[idx] if (0 <= idx < len(info_list)) else (info_list[0] if info_list else "nessun beam")

    # =========================
    # 10B. POSIZIONI STRUTTURA GLOBALE
    # =========================
    all_beams_positions = {}
    all_pts_list = list(pts.values())
    min_x3, max_x3 = min(p[0] for p in all_pts_list), max(p[0] for p in all_pts_list)
    min_y3, max_y3 = min(p[1] for p in all_pts_list), max(p[1] for p in all_pts_list)
    min_z3, max_z3 = min(p[2] for p in all_pts_list), max(p[2] for p in all_pts_list)
    rx, ry, rz = max(max_x3-min_x3, 1.0), max(max_y3-min_y3, 1.0), max(max_z3-min_z3, 1.0)

    for node in g.nodes():
        label = beam_label_by_guid.get(node, node)
        px, py, pz = pts[node]
        beam = timber_model.get_element(node)
        try:
            cl = beam.centerline
            s = cl.start if hasattr(cl, "start") else get_line_start(cl)
            e = cl.end if hasattr(cl, "end") else get_line_end(cl)
            all_beams_positions[label] = {
                "guid": node, "module": assignment.get(node, "?"),
                "centerline_start": [round(s.x, 4), round(s.y, 4), round(s.z, 4)],
                "centerline_end":   [round(e.x, 4), round(e.y, 4), round(e.z, 4)],
                "midpoint": [round(px, 4), round(py, 4), round(pz, 4)],
                "midpoint_normalized": [round((px-min_x3)/rx, 4), round((py-min_y3)/ry, 4), round((pz-min_z3)/rz, 4)]
            }
        except:
            all_beams_positions[label] = {"guid": node, "module": assignment.get(node, "?"), "midpoint": [round(px, 4), round(py, 4), round(pz, 4)], "midpoint_normalized": [round((px-min_x3)/rx, 4), round((py-min_y3)/ry, 4), round((pz-min_z3)/rz, 4)]}

    # =========================
    # 11. EXPORT DISCO ATTIVO (JSON + STL)
    # =========================
    output_folder = "/Users/Ra/Desktop/web_data/beams"
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
            seen = set()
            clean_joints = [j[1] for j in joints_list if j[1] not in seen and not seen.add(j[1])]

            xlap, tbutt, lmiter = [], [], []
            for j_num in clean_joints:
                jt = joint_type_by_number.get(j_num, "")
                if jt == 'XLapJoint': xlap.append(j_num)
                elif jt == 'TButtJoint': tbutt.append(j_num)
                elif jt == 'LMiterJoint': lmiter.append(j_num)

            beam_id = name.lower()
            beam_folder = os.path.join(output_folder, beam_id)
            if not os.path.exists(beam_folder): os.makedirs(beam_folder)

            stl_res = save_stl(beam.geometry, beam_id, beam_folder)
            if stl_res and not stl_res.startswith("ERRORE"): stl_files_created.append(stl_res)
            else: stl_errors.append(stl_res)

            beam_data = {
                "beam ID": beam_id, "name": name, "module": k,
                "width (m)": round(w_m, 4) if w_m else None, "height (m)": round(h_m, 4) if h_m else None,
                "length (m)": round(length, 2), "volume (cm³)": round(volume_m3 * 1_000_000, 2), "weight (kg)": round(weight, 2),
                "local_frame": get_beam_local_frame(beam),
                "connected_beams": [beam_label_by_guid.get(nbr, "").lower() for nbr in g.neighbors(node) if beam_label_by_guid.get(nbr)],
                "global_position": all_beams_positions.get(name, {}),
                "joints": {"all": clean_joints, "xlap": xlap, "tbutt": tbutt, "lmiter": lmiter},
                "3d_model": "https://raw.githubusercontent.com/gramaziokohler/coding_architecture_fs26_focus_work/main/web_data/beams/{}/{}.stl".format(beam_id, beam_id)
            }
            with open(os.path.join(beam_folder, "{}.json".format(beam_id)), 'w') as f: json.dump(beam_data, f, indent=2)
            json_files_created.append(os.path.join(beam_folder, "{}.json".format(beam_id)))

    # Export Struttura Globale
    all_beams_list = []
    for k in labels_keys:
        for node in ordered_by_module.get(k, []):
            label = beam_label_by_guid.get(node, "?")
            all_beams_list.append({
                "beam_id": label.lower(), "module": k,
                "centerline_start": all_beams_positions.get(label, {}).get("centerline_start"),
                "centerline_end": all_beams_positions.get(label, {}).get("centerline_end"),
                "midpoint": all_beams_positions.get(label, {}).get("midpoint"),
                "midpoint_normalized": all_beams_positions.get(label, {}).get("midpoint_normalized"),
                "connected_beams": [beam_label_by_guid.get(nbr, "").lower() for nbr in g.neighbors(node) if beam_label_by_guid.get(nbr)]
            })
    if not os.path.exists(output_folder): os.makedirs(output_folder)
    with open(global_structure_path, 'w') as f: json.dump({"total_beams": len(all_beams_list), "bounding_box": {"min": [round(min_x3, 4), round(min_y3, 4), round(min_z3, 4)], "max": [round(max_x3, 4), round(max_y3, 4), round(max_z3, 4)]}, "beams": all_beams_list}, f, indent=2)

    json_export_out = "JSON: {} | STL: {} | Errori STL: {}".format(len(json_files_created)+1, len(stl_files_created), len(stl_errors))

    return (
        geom["A"], geom["B"], geom["C"], geom["D"], geom["E"], geom["F"],
        summary_by_category["A"], summary_by_category["B"], summary_by_category["C"], summary_by_category["D"], summary_by_category["E"], summary_by_category["F"],
        info_out, json_export_out, debug_out,
        punti_scritte_out, pianos_scritte_out = piani_scritte_out, nomi_scritte_out
    )