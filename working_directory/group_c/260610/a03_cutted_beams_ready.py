# venv: ca-fs26-focus-work
# keyword: timber-packing, 90-deg-beam-rotation, vacuum-area-boolean, blank-length-diagnostic
import Rhino.Geometry as rg
import math
from importlib import reload
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
    """Genera le curve di un testo perfettamente piatto in Top View (XY) con riempimento Hatch."""
    te = rg.TextEntity()
    te.Text = text
    te.FontIndex = 0
    te.TextHeight = text_height
    
    plane = rg.Plane.WorldXY
    plane.Origin = position
    te.Plane = plane
    
    curves = te.Explode()
    if not curves:
        return []
        
    joined = rg.Curve.JoinCurves(curves, 0.001) or curves
    bbox = te.GetBoundingBox(True)
    
    if bbox.IsValid:
        center_x = (bbox.Max.X + bbox.Min.X) / 2.0
        center_y = (bbox.Max.Y + bbox.Min.Y) / 2.0
        move_to_center = rg.Transform.Translation(position.X - center_x, position.Y - center_y, 0)
        for crv in joined:
            crv.Transform(move_to_center)
            
    output_objects = []
    if joined:
        hatches = rg.Hatch.Create(joined, 0, 0.0, 1.0, 0.001)
        if hatches:
            output_objects.extend(hatches)
        else:
            output_objects.extend(joined)
            
    return output_objects


def create_3d_text_engraving(text, position, text_height=0.03, engraving_depth=0.005):
    """Creates 3D solid text geometry centered at the specified position."""
    scale_factor = 1000.0

    work_height = text_height * scale_factor
    work_depth = engraving_depth * scale_factor

    fine_tol = 0.001
    boolean_tol = 0.01

    te = rg.TextEntity()
    te.Text = text
    te.Plane = rg.Plane.WorldXY
    te.FontIndex = 0
    te.TextHeight = work_height

    curves = te.Explode()
    if not curves:
        return None

    joined_curves = rg.Curve.JoinCurves(curves, fine_tol) or []
    text_breps = rg.Brep.CreatePlanarBreps(joined_curves, fine_tol)
    if not text_breps:
        return None

    solids = []
    for b in text_breps:
        for face in b.Faces:
            loops = [loop.To3dCurve() for loop in face.Loops]
            if not loops:
                continue

            ext = rg.Extrusion.Create(loops[0], work_depth, True)
            if ext:
                solid = ext.ToBrep()
                if len(loops) > 1:
                    for i in range(1, len(loops)):
                        inner_ext = rg.Extrusion.Create(loops[i], work_depth, True)
                        if inner_ext:
                            inner_solid = inner_ext.ToBrep()
                            if inner_solid:
                                diff = rg.Brep.CreateBooleanDifference(solid, inner_solid, boolean_tol)
                                if diff:
                                    solid = diff[0]
                solids.append(solid)

    final_3d = rg.Brep.MergeBreps(solids, boolean_tol)
    if not final_3d:
        return None

    text_bbox = final_3d.GetBoundingBox(True)
    cx = (text_bbox.Max.X + text_bbox.Min.X) / 2.0
    cy = (text_bbox.Max.Y + text_bbox.Min.Y) / 2.0
    cz = text_bbox.Max.Z 
    
    move_to_center = rg.Transform.Translation(-cx, -cy, -cz)
    final_3d.Transform(move_to_center)

    downscale_and_move = rg.Transform.Multiply(
        rg.Transform.Translation(position.X, position.Y, position.Z),
        rg.Transform.Scale(rg.Plane.WorldXY, 1.0/scale_factor, 1.0/scale_factor, 1.0/scale_factor)
    )
    final_3d.Transform(downscale_and_move)

    return final_3d


def get_pure_brep(cb):
    """Estrae la geometria pulita di Rhino svestendo i wrapper COMPAS."""
    if cb is None:
        return None
    if hasattr(cb, "Geometry"):
        return cb.Geometry
    if hasattr(cb, "Value"):
        return cb.Value
    if type(cb).__name__.endswith("RhinoBrep") or hasattr(cb, "brep"):
        return getattr(cb, "brep", getattr(cb, "native_brep", getattr(cb, "_brep", cb)))
    return cb


def compas_frame_to_rhino_plane(compas_frame):
    """Converte un Frame di COMPAS in un Plane di Rhino."""
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

    # 2. RADDRIZZAMENTO, ROTAZIONE DI 90° E RAGGRUPPAMENTO DEI BEAM PER SEZIONE
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
            
        # === FILP LONGITUDINALE DI 90 GRADI ALLINEATO ALL'ASSE X ===
        rotate_90_x = rg.Transform.Rotation(math.pi / 2.0, rg.Vector3d.XAxis, rg.Point3d(0, 0, 0))
        straight_brep.Transform(rotate_90_x)
        
        local_bbox = straight_brep.GetBoundingBox(True)
        if local_bbox and local_bbox.IsValid:
            size_box = local_bbox.Max - local_bbox.Min
            beam_length = size_box.X
            width_box, height_box = round(size_box.Y, 4), round(size_box.Z, 4)
        else:
            beam_length, width_box, height_box = beam.centerline.length, 0.12, 0.14

        # === DIAGNOSTICA DI TRACCIAMENTO SORGENTE BLANK_LENGTH ===
        compas_blank_len = None
        blank_source = "FALLBACK (Misura Taglio)"
        
        if hasattr(beam, "blank_length") and getattr(beam, "blank_length") is not None:
            compas_blank_len = getattr(beam, "blank_length")
            blank_source = "PROPRIETÀ_NATIVA (.blank_length)"
        elif hasattr(beam, "attributes") and isinstance(beam.attributes, dict) and "blank_length" in beam.attributes:
            compas_blank_len = beam.attributes["blank_length"]
            blank_source = "DIZIONARIO_ATTRIBUTI (['blank_length'])"
        elif hasattr(beam, "blank_len") and getattr(beam, "blank_len") is not None:
            compas_blank_len = getattr(beam, "blank_len")
            blank_source = "PROPRIETÀ_NATIVA_CORTA (.blank_len)"
        elif hasattr(beam, "attributes") and isinstance(beam.attributes, dict) and "blank_len" in beam.attributes:
            compas_blank_len = beam.attributes["blank_len"]
            blank_source = "DIZIONARIO_ATTRIBUTI_CORTO (['blank_len'])"
            
        if compas_blank_len is None:
            compas_blank_len = beam_length
        else:
            compas_blank_len = float(compas_blank_len)

        needed_len = compas_blank_len + total_target_gap
        
        section_key = (width_box, height_box)
        if section_key not in beams_by_section: beams_by_section[section_key] = []
        beams_by_section[section_key].append({
            "beam_obj": beam, "geo_brep": straight_brep, "name": correct_name,
            "length_x": beam_length, "blank_length": compas_blank_len, "blank_source": blank_source,
            "width_y": width_box, "height_z": height_box, "needed_len": needed_len
        })

    # 3. ESECUZIONE ALGORITMO BIN PACKING
    packed_bars = []
    bar_global_counter = 1
    for section_key in sorted(beams_by_section.keys()):
        sec_w, sec_h = section_key
        current_allowed_s_len = get_assigned_stock_length(sec_w, sec_h)
        usable_cutting_length = current_allowed_s_len - (2.0 * stock_edge_gap)
        
        # Packing calibrato sulle lunghezze grezze totali
        section_beams = sorted(beams_by_section[section_key], key=lambda x: x["blank_length"], reverse=True)
        
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

    # 4. GENERAZIONE DEL LAYOUT SPAZIALE COERENTE + SPOSTAMENTO VELOCE ENGRAVING + ADATTAMENTO CONTINUO VACUUM
    arranged_boxes, max_len_boxes, stock_beams, max_len_lines, arranged_names, label_curves, max_len_num_txt, engraving, dimensions, report_sections = [], [], [], [], [], [], [], [], [], []
    vacuum_surfaces_out = [] 
    failed_vacuums = [] 
    
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

        # === CONTENITORI COMMERCIALI (STOCK BEAMS) ===
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

            # === SCATOLE DI DIMENSIONE MASSIMA (MAX LEN BOXES) ===
            raw_box_geo = rg.Box(rg.Plane.WorldXY, rg.Interval(0, item["blank_length"]), rg.Interval(0, item["width_y"]), rg.Interval(0, item["height_z"])).ToBrep()
            bbox_current_raw = raw_box_geo.GetBoundingBox(True)
            raw_box_geo.Transform(rg.Transform.Translation(target_x - bbox_current_raw.Min.X, y_pos - bbox_current_raw.Min.Y, base_pt.Z - bbox_current_raw.Min.Z))
            max_len_boxes.append(raw_box_geo)

            new_bbox = pure_beam_geo.GetBoundingBox(True)
            exact_top_z = base_pt.Z + item["height_z"]
            
            max_len_lines.append(rg.Line(rg.Point3d(new_bbox.Min.X, new_bbox.Min.Y, exact_top_z + 0.01), rg.Point3d(new_bbox.Min.X + item["blank_length"], new_bbox.Min.Y, exact_top_z + 0.01)))
            arranged_names.append(item["name"])

            lbl_x = (new_bbox.Min.X + new_bbox.Max.X) / 2.0
            lbl_y_center = (new_bbox.Min.Y + new_bbox.Max.Y) / 2.0
            lbl_y_under = lbl_y_center - (sec_w / 2.0) - l_off

            length_in_cm = item["length_x"] * 100.0

            label_curves.extend(create_geometry_text(item["name"], rg.Point3d(lbl_x, lbl_y_under, exact_top_z), text_height=0.04))
            max_len_num_txt.extend(create_geometry_text("{:.1f}cm".format(length_in_cm), rg.Point3d(lbl_x, lbl_y_under - 0.06, exact_top_z), text_height=0.04))

            # === LOGICA DI CONTROLLO MATRICE A 5 PUNTI SULLA QUOTA SUPERIORE (TESTO) ===
            lbl_y = lbl_y_center
            test_x = lbl_x
            step = 0.02  
            max_shift = (item["length_x"] / 2.0) - 0.10  
            current_shift = 0.0
            
            t_height = 0.03  
            t_width_approx = len(item["name"]) * (t_height * 0.7) 
            
            while current_shift < max_shift:
                test_points = [
                    rg.Point3d(test_x, lbl_y, exact_top_z + 0.01),                       
                    rg.Point3d(test_x - t_width_approx/2, lbl_y - t_height/2, exact_top_z + 0.01), 
                    rg.Point3d(test_x + t_width_approx/2, lbl_y - t_height/2, exact_top_z + 0.01), 
                    rg.Point3d(test_x - t_width_approx/2, lbl_y + t_height/2, exact_top_z + 0.01), 
                    rg.Point3d(test_x + t_width_approx/2, lbl_y + t_height/2, exact_top_z + 0.01)  
                ]
                
                area_is_fully_solid = True
                for pt in test_points:
                    ray = rg.Line(pt, rg.Point3d(pt.X, pt.Y, base_pt.Z - 0.01)).ToNurbsCurve()
                    intersections = rg.Intersect.Intersection.CurveBrep(ray, pure_beam_geo, 0.001)
                    
                    point_hits_solid_wood = False
                    if intersections and len(intersections[2]) > 0:
                        highest_z = max(p.Z for p in intersections[2])
                        if abs(highest_z - exact_top_z) < 0.002:
                            point_hits_solid_wood = True
                            
                    if not point_hits_solid_wood:
                        area_is_fully_solid = False
                        break
                
                if area_is_fully_solid:
                    break  
                
                test_x -= step
                current_shift += step

            pt_engrave_loc = rg.Point3d(test_x, lbl_y, exact_top_z)
            solid_text = create_3d_text_engraving(text=item["name"], position=pt_engrave_loc, text_height=t_height, engraving_depth=0.005)
            
            if solid_text:
                engraving.append(solid_text)

            # === LOGICA ADATTIVA CONFRONTO DI AREA ESATTA VACUUM ===
            v_width = 0.075
            v_length = 0.14
            
            half_l = v_length / 2.0
            half_w = v_width / 2.0
            
            vacuums_placed_count = 0
            first_vacuum_x = None  
            
            min_v_x = new_bbox.Min.X + half_l
            max_v_x = new_bbox.Max.X - half_l
            target_area = v_length * v_width
            
            for v_ratio in [0.33, 0.66]:
                x_offset_from_center = (item["length_x"] * v_ratio) - (item["length_x"] / 2.0)
                current_v_x = test_x + x_offset_from_center
                
                if current_v_x < min_v_x:
                    current_v_x = min_v_x
                
                if first_vacuum_x is not None:
                    if current_v_x < first_vacuum_x + v_length + 0.01:
                        current_v_x = first_vacuum_x + v_length + 0.01
                
                step_v = 0.01
                vacuum_success = False
                
                while current_v_x <= max_v_x:
                    v_box_x = rg.Interval(current_v_x - half_l, current_v_x + half_l)
                    v_box_y = rg.Interval(lbl_y_center - half_w, lbl_y_center + half_w)
                    v_box_z = rg.Interval(base_pt.Z - 0.01, base_pt.Z + 0.02)
                    
                    test_box_brep = rg.Box(rg.Plane.WorldXY, v_box_x, v_box_y, v_box_z).ToBrep()
                    res_intersections = rg.Brep.CreateBooleanIntersection(pure_beam_geo, test_box_brep, 0.001)
                    
                    single_vacuum_safe = False
                    if res_intersections:
                        total_contact_area = 0.0
                        slice_plane = rg.Plane(rg.Point3d(0, 0, base_pt.Z + 0.001), rg.Vector3d.ZAxis)
                        
                        for piece in res_intersections:
                            contour_curves = rg.Brep.CreateContourCurves(piece, slice_plane)
                            if contour_curves:
                                for crv in contour_curves:
                                    if crv.IsClosed:
                                        amp = rg.AreaMassProperties.Compute(crv)
                                        if amp: total_contact_area += amp.Area
                                            
                        if abs(total_contact_area - target_area) < 1e-5:
                            single_vacuum_safe = True
                    
                    if single_vacuum_safe:
                        vacuum_success = True
                        break 
                        
                    current_v_x += step_v 
                
                if vacuum_success:
                    if first_vacuum_x is None:
                        first_vacuum_x = current_v_x
                        
                    vacuum_plane = rg.Plane(rg.Point3d(current_v_x, lbl_y_center, 0.0), rg.Vector3d.XAxis, rg.Vector3d.YAxis)
                    vacuum_surf = rg.PlaneSurface(
                        vacuum_plane, 
                        rg.Interval(-half_l, half_l), 
                        rg.Interval(-half_w, half_w)
                    )
                    vacuum_surfaces_out.append(vacuum_surf)
                    vacuums_placed_count += 1

            if vacuums_placed_count < 2:
                failed_vacuums.append(item["name"])

            # === AGGIUNTA LOG DI TRACCIAMENTO SUL PIN DIMENSIONS ===
            dimensions.append("Stock bar n°: {} | {} | Sezione: {:.1f}x{:.1f}cm | L_taglio: {:.3f}m | L_grezzo: {:.3f}m -> [SORGENTE DATI: {}]".format(
                bar["id"], item["name"], sec_w*100.0, sec_h*100.0, item["length_x"], item["blank_length"], item["blank_source"]
            ))

    # 5. RENDICONTO STATISTICO
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

    # === ESATTO ORDINE DI RETURN CONSERVATO INVARIATO ===

    return arranged_boxes, arranged_names, max_len_boxes, stock_beams, max_len_lines, label_curves, max_len_num_txt, engraving, dimensions, report, vacuum_surfaces_out, failed_vacuums