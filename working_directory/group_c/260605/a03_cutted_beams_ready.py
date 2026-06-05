import Rhino.Geometry as rg
import math
from compas.datastructures import Graph

class CutItem:
    def __init__(self, beam_id, beam_name, original_beam, width, length, height):
        self.id = beam_id
        self.name = beam_name
        self.original_beam = original_beam
        self.width = width
        self.length = length
        self.height = height
        self.center_pt = None

def create_geometry_text(text, position, text_height=0.03):
    te = rg.TextEntity()
    te.Text = text
    te.FontIndex = 0
    te.TextHeight = text_height
    plane = rg.Plane.WorldXY
    plane.Origin = position
    te.Plane = plane
    curves = te.Explode()
    if not curves: return []
    joined = rg.Curve.JoinCurves(curves, 0.001) or curves
    bbox = te.GetBoundingBox(True)
    if bbox.IsValid:
        center_x = (bbox.Max.X + bbox.Min.X) / 2.0
        center_y = (bbox.Max.Y + bbox.Min.Y) / 2.0
        move_to_center = rg.Transform.Translation(position.X - center_x, position.Y - center_y, 0)
        for crv in joined: crv.Transform(move_to_center)
    return joined

def get_pure_brep(cb):
    if cb is None: return None
    if hasattr(cb, "Geometry"): return cb.Geometry
    if hasattr(cb, "Value"): return cb.Value
    if type(cb).__name__.endswith("RhinoBrep") or hasattr(cb, "brep"):
        return getattr(cb, "brep", getattr(cb, "native_brep", getattr(cb, "_brep", cb)))
    return cb

def compas_frame_to_rhino_plane(compas_frame):
    pt = rg.Point3d(compas_frame.point.x, compas_frame.point.y, compas_frame.point.z)
    xaxis = rg.Vector3d(compas_frame.xaxis.x, compas_frame.xaxis.y, compas_frame.xaxis.z)
    yaxis = rg.Vector3d(compas_frame.yaxis.x, compas_frame.yaxis.y, compas_frame.yaxis.z)
    return rg.Plane(pt, xaxis, yaxis)

def run_packing(timber_model, origin, stock_length_beam_6x8, stock_length_beam_10x8, 
                stock_length_beam_12x14, saw_gap, price_lm, row_tolerance, label_offset):
    
    if timber_model is None or not hasattr(timber_model, "joints"):
        raise ValueError("ERRORE: Modello COMPAS mancante o non valido!")

    base_pt = origin if origin is not None else rg.Point3d(0, 0, 0)
    s_gap = float(saw_gap) if saw_gap is not None else 0.004
    p_lm = float(price_lm) if price_lm is not None else 15.0
    l_off = float(label_offset) if label_offset is not None else 0.03

    total_target_gap = 0.01  
    h_gap = (total_target_gap - s_gap) / 2.0  
    stock_edge_gap = 0.01  
    beam_spacing = 0.6          
    distacco_tra_sezioni = 1.5   

    len_6x8 = float(stock_length_beam_6x8) if stock_length_beam_6x8 is not None else 5.0
    len_10x8 = float(stock_length_beam_10x8) if stock_length_beam_10x8 is not None else (13.0 / 3.0)
    len_12x14 = float(stock_length_beam_12x14) if stock_length_beam_12x14 is not None else (13.0 / 3.0)

    def get_assigned_stock_length(w, h):
        cm_w = round(w * 100.0, 1)
        cm_h = round(h * 100.0, 1)
        if (cm_w == 6.0 and cm_h == 8.0) or (cm_w == 8.0 and cm_h == 6.0): return len_6x8
        elif (cm_w == 10.0 and cm_h == 8.0) or (cm_w == 8.0 and cm_h == 10.0): return len_10x8
        elif (cm_w == 12.0 and cm_h == 14.0) or (cm_w == 14.0 and cm_h == 12.0): return len_12x14
        return 5.0

    # 1. GENERAZIONE MAPPA NOMI INDUSTRIALI VIA COMPAS GRAPH
    g = Graph()
    for joint in timber_model.joints:
        ea, eb = joint.elements
        pa, pb = ea.centerline.midpoint, eb.centerline.midpoint
        na = g.add_node(str(ea.guid), x=pa.x, y=pa.y, z=pa.z)
        nb = g.add_node(str(eb.guid), x=pb.x, y=pb.y, z=pb.z)
        g.add_edge(na, nb)

    pts = {n: g.node_attributes(n, ['x','y','z']) for n in g.nodes()}
    min_x, max_x = min(p[0] for p in pts.values()), max(p[0] for p in pts.values())
    min_y, max_y = min(p[1] for p in pts.values()), max(p[1] for p in pts.values())
    nx, ny = 3, 2
    dx, dy = (max_x - min_x) / nx, (max_y - min_y) / ny

    cells = []
    for i in range(nx):
        for j in range(ny): cells.append((min_x + dx * (i + 0.5), min_y + dy * (j + 0.5)))

    labels_keys = ["A", "B", "C", "D", "E", "F"]
    def dist2(a, b): return (a[0]-b[0])**2 + (a[1]-b[1])**2

    seeds = {}
    for key, (cx, cy) in zip(labels_keys, cells):
        seeds[key] = min(pts, key=lambda n: dist2(pts[n], (cx, cy)))

    groups = {k: [] for k in seeds}
    for node, p in pts.items():
        best_k, best_d = None, 1e9
        for k, seed_node in seeds.items():
            sx, sy, _ = pts[seed_node]
            d = dist2(p, (sx, sy))
            if d < best_d: best_d, best_k = d, k
        groups[best_k].append(node)

    def connected_growth(seed, group_nodes):
        group_set = set(group_nodes)
        visited, order, frontier = set([seed]), [seed], [seed]
        while len(order) < len(group_set):
            best_candidate, best_dist = None, 1e9
            for f in frontier:
                for nbr in g.neighbors(f):
                    if nbr in group_set and nbr not in visited:
                        px, py, pz = pts[f]
                        nx_pt, ny_pt, nz_pt = pts[nbr]
                        d = (px-nx_pt)**2 + (py-ny_pt)**2 + (pz-nz_pt)**2
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

    guid_to_custom_name = {}
    for k in labels_keys:
        ordered = connected_growth(seeds[k], groups[k])
        for i, node in enumerate(ordered):
            beam = timber_model.get_element(node)
            if beam: guid_to_custom_name[str(beam.guid)] = "{}{}".format(k, i + 1)

    # 2. RADDRIZZAMENTO E RAGGRUPPAMENTO DEI BEAM PER SEZIONE
    beams_by_section = {}
    for idx, beam in enumerate(timber_model.beams):
        b_guid = str(beam.guid)
        correct_name = guid_to_custom_name.get(b_guid, "B{:02d}".format(idx + 1))
        raw_brep = get_pure_brep(beam.geometry)
        if raw_brep is None: continue
        straight_brep = raw_brep.DuplicateBrep()
        if hasattr(beam, "frame") and beam.frame:
            local_plane = compas_frame_to_rhino_plane(beam.frame)
            flatten_trans = rg.Transform.PlaneToPlane(local_plane, rg.Plane.WorldXY)
            straight_brep.Transform(flatten_trans)
        local_bbox = straight_brep.GetBoundingBox(True)
        if local_bbox and local_bbox.IsValid:
            size_box = local_bbox.Max - local_bbox.Min
            beam_length = size_box.X
            width_box, height_box = round(size_box.Y, 4), round(size_box.Z, 4)
        else:
            beam_length, width_box, height_box = beam.centerline.length, 0.12, 0.14

        needed_len = beam_length + total_target_gap
        section_key = (width_box, height_box)
        if section_key not in beams_by_section: beams_by_section[section_key] = []
        beams_by_section[section_key].append({
            "beam_obj": beam, "geo_brep": straight_brep, "name": correct_name,
            "length_x": beam_length, "width_y": width_box, "height_z": height_box, "needed_len": needed_len
        })

    # 3. ESECUZIONE ALGORITMO BIN PACKING
    packed_bars = []
    bar_global_counter = 1
    for section_key in sorted(beams_by_section.keys()):
        sec_w, sec_h = section_key
        current_allowed_s_len = get_assigned_stock_length(sec_w, sec_h)
        usable_cutting_length = current_allowed_s_len - (2.0 * stock_edge_gap)
        section_beams = sorted(beams_by_section[section_key], key=lambda x: x["length_x"], reverse=True)
        section_bars = []
        for item in section_beams:
            needed = item["needed_len"]
            placed = False
            for bar in section_bars:
                if bar["remaining"] >= needed:
                    current_start = bar["current_pos"]
                    bar["beams"].append({"item_data": item, "start_pos": current_start, "visual_start_x": current_start + h_gap + stock_edge_gap})
                    bar["remaining"] -= needed
                    bar["current_pos"] += needed
                    placed = True
                    break
            if not placed:
                new_bar = {
                    "id": bar_global_counter, "section": section_key, "stock_len_assigned": current_allowed_s_len,
                    "remaining": usable_cutting_length - needed, "current_pos": needed,
                    "beams": [{"item_data": item, "start_pos": 0.0, "visual_start_x": h_gap + stock_edge_gap}]
                }
                section_bars.append(new_bar)
                packed_bars.append(new_bar)
                bar_global_counter += 1

    # 4. GENERAZIONE DEL LAYOUT SPAZIALE COERENTE
    arranged_boxes, max_len_boxes, stock_beams, max_len_lines, arranged_names, label_curves, max_len_num_txt, dimensions = [], [], [], [], [], [], [], []
    total_waste_material, total_material_bought = 0.0, 0.0
    current_y_accumulator = base_pt.Y
    previous_section = None

    for bar in sorted(packed_bars, key=lambda b: b["id"]):
        sec_w, sec_h = bar["section"]
        if previous_section is not None and bar["section"] != previous_section: current_y_accumulator += distacco_tra_sezioni
        elif previous_section is not None: current_y_accumulator += beam_spacing
        y_pos = current_y_accumulator
        previous_section = bar["section"]
        total_waste_material += bar["remaining"] + (2.0 * stock_edge_gap)
        this_bar_stock_len = bar["stock_len_assigned"]
        total_material_bought += this_bar_stock_len

        stock_x_interval, stock_y_interval, stock_z_interval = rg.Interval(0, this_bar_stock_len), rg.Interval(0, sec_w), rg.Interval(0, sec_h)
        single_stock_bar = rg.Box(rg.Plane.WorldXY, stock_x_interval, stock_y_interval, stock_z_interval).ToBrep()
        bbox_stock = single_stock_bar.GetBoundingBox(True)
        single_stock_bar.Transform(rg.Transform.Translation(base_pt.X - bbox_stock.Min.X, y_pos - bbox_stock.Min.Y, base_pt.Z - bbox_stock.Min.Z))
        stock_beams.append(single_stock_bar)

        for b_info in sorted(bar["beams"], key=lambda x: x["start_pos"]):
            item = b_info["item_data"]
            target_x = base_pt.X + b_info["visual_start_x"]
            
            pure_beam_geo = item["geo_brep"].DuplicateBrep()
            bbox_init = pure_beam_geo.GetBoundingBox(True)
            pure_beam_geo.Transform(rg.Transform.Translation(0.0 - bbox_init.Min.X, 0.0 - bbox_init.Min.Y, 0.0 - bbox_init.Min.Z))
            bbox_current_beam = pure_beam_geo.GetBoundingBox(True)
            pure_beam_geo.Transform(rg.Transform.Translation(target_x - bbox_current_beam.Min.X, y_pos - bbox_current_beam.Min.Y, base_pt.Z - bbox_current_beam.Min.Z))
            arranged_boxes.append(pure_beam_geo)

            raw_box_geo = rg.Box(rg.Plane.WorldXY, rg.Interval(0, item["length_x"]), rg.Interval(0, item["width_y"]), rg.Interval(0, item["height_z"])).ToBrep()
            bbox_current_raw = raw_box_geo.GetBoundingBox(True)
            raw_box_geo.Transform(rg.Transform.Translation(target_x - bbox_current_raw.Min.X, y_pos - bbox_current_raw.Min.Y, base_pt.Z - bbox_current_raw.Min.Z))
            max_len_boxes.append(raw_box_geo)

            new_bbox = pure_beam_geo.GetBoundingBox(True)
            max_len_lines.append(rg.Line(rg.Point3d(new_bbox.Min.X, new_bbox.Min.Y, new_bbox.Min.Z + (item["height_z"] * 2.0)), rg.Point3d(new_bbox.Min.X + item["length_x"], new_bbox.Min.Y, new_bbox.Min.Z + (item["height_z"] * 2.0))))
            arranged_names.append(item["name"])

            lbl_x, lbl_y = (new_bbox.Min.X + new_bbox.Max.X) / 2.0, (new_bbox.Min.Y + new_bbox.Max.Y) / 2.0
            label_curves.extend(create_geometry_text(item["name"], rg.Point3d(lbl_x, lbl_y, new_bbox.Max.Z + l_off), text_height=0.04))
            max_len_num_txt.extend(create_geometry_text("{:.2f}m".format(item["length_x"]), rg.Point3d(lbl_x, lbl_y - 0.08, new_bbox.Max.Z + l_off), text_height=0.04))

            dimensions.append("Stock beam n°: {} | {} | Sezione: {:.1f}x{:.1f}cm | L: {:.3f}m".format(bar["id"], item["name"], sec_w*100.0, sec_h*100.0, item["length_x"]))

    # 5. RENDICONTO STATISTICO
    report_sections = []
    for sec in sorted(beams_by_section.keys()):
        sec_bars = [b for b in packed_bars if b["section"] == sec]
        sec_num_stocks = len(sec_bars)
        allocated_s_len = get_assigned_stock_length(sec[0], sec[1])
        sec_material = sum(b["stock_len_assigned"] for b in sec_bars)
        sec_waste = sum(b["remaining"] for b in sec_bars) + (sec_num_stocks * 2.0 * stock_edge_gap)
        sec_eff = ((sec_material - sec_waste) / sec_material) * 100.0 if sec_material > 0 else 0.0
        report_sections.append("--- PACKING REPORT: Querschnitt {:.2f} x {:.2f} m ---\nStock Length used: {:.2f} m\nStocks needed:     {} pcs\nTotal Material:    {:.2f} m\nTotal Waste:       {:.2f} m\nEfficiency:        {:.1f}%\nPrice/m:           {:.2f} EUR\nEstimated Cost:    {:.2f} EUR\n--------------------------------------------------".format(sec[0], sec[1], allocated_s_len, sec_num_stocks, sec_material, sec_waste, sec_eff, p_lm, sec_material * p_lm))

    total_efficiency = ((total_material_bought - total_waste_material) / total_material_bought) * 100.0 if total_material_bought > 0 else 0.0
    report = "==================================================\n        REPORT DETTAGLIATO DI SECOLO DI TAGLIO    \n==================================================\n" + "\n\n".join(report_sections) + "\n\n--- TOTAL PACKING SUMMARY ---\nTotal Stocks needed: {} pcs\nTotal Material:      {:.2f} m\nTotal Waste:         {:.2f} m\nTotal Efficiency:    {:.1f}%\nTotal Cost:          {:.2f} EUR\n-----------------------------\n==================================================".format(len(packed_bars), total_material_bought, total_waste_material, total_efficiency, total_material_bought * p_lm)

    # Restituisce una tupla contenente tutti i dati pronti per Grasshopper
    return arranged_boxes, max_len_boxes, stock_beams, max_len_lines, arranged_names, label_curves, max_len_num_txt, dimensions, report