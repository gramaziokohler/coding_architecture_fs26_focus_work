import Rhino.Geometry as rg
import math

def create_geometry_text(text, position, text_height=0.03):
    """Genera le curve di un testo perfettamente piatto in Top View (XY) e centrato."""
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
            
    return joined

def run_packing(timber_model, origin, stock_length_beam_6x8, stock_length_beam_10x8, 
                stock_length_beam_12x14, saw_gap, horizontal_side_gap, row_tolerance, label_offset, price_lm):
    
    if timber_model is None:
        raise ValueError("ERRORE: Modello COMPAS mancante o non valido!")

    base_pt = origin if origin is not None else rg.Point3d(0, 0, 0)
    s_gap = float(saw_gap) if saw_gap is not None else 0.004
    p_lm = float(price_lm) if price_lm is not None else 15.0
    l_off = float(label_offset) if label_offset is not None else 0.03
    side_gap = float(horizontal_side_gap) if horizontal_side_gap is not None else 0.01

    total_target_gap = 0.01  
    h_gap = (total_target_gap - s_gap) / 2.0  
    beam_spacing = 0.6          
    distacco_tra_sezioni = 1.5   

    len_6x8 = float(stock_length_beam_6x8) if stock_length_beam_6x8 is not None else 5.0
    len_10x8 = float(stock_length_beam_10x8) if stock_length_beam_10x8 is not None else 6.0
    len_12x14 = float(stock_length_beam_12x14) if stock_length_beam_12x14 is not None else 6.0

    def get_assigned_stock_length(w, h):
        cm_w = round(w * 100.0, 1)
        cm_h = round(h * 100.0, 1)
        if (cm_w == 6.0 and cm_h == 8.0) or (cm_w == 8.0 and cm_h == 6.0): return len_6x8
        elif (cm_w == 10.0 and cm_h == 8.0) or (cm_w == 8.0 and cm_h == 10.0): return len_10x8
        elif (cm_w == 12.0 and cm_h == 14.0) or (cm_w == 14.0 and cm_h == 12.0): return len_12x14
        return 5.0

    # 1. LETTURA DEI METADATI DIRETTAMENTE DAL MODELLO COMPAS ELEVATO
    beams_by_section = {}
    
    for idx, beam in enumerate(timber_model.beams):
        beam_name = getattr(beam, 'name', "B{:02d}".format(idx + 1))
        
        rh_geo = None
        geo = beam.geometry
        if hasattr(geo, "to_rhino"): rh_geo = geo.to_rhino()
        elif hasattr(geo, "to_brep"): rh_geo = geo.to_brep().to_rhino()
        elif type(geo).__name__.endswith("RhinoBrep"):
            rh_geo = getattr(geo, "brep", getattr(geo, "native_brep", getattr(geo, "_brep", None)))
            
        if rh_geo is None: 
            continue
            
        # Raddrizzamento preliminare per identificare la sezione reale
        straight_brep = rh_geo.DuplicateBrep()
        if hasattr(beam, "frame") and beam.frame:
            pt = rg.Point3d(beam.frame.point.x, beam.frame.point.y, beam.frame.point.z)
            xaxis = rg.Vector3d(beam.frame.xaxis.x, beam.frame.xaxis.y, beam.frame.xaxis.z)
            yaxis = rg.Vector3d(beam.frame.yaxis.x, beam.frame.yaxis.y, beam.frame.yaxis.z)
            local_plane = rg.Plane(pt, xaxis, yaxis)
            
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
        
        if section_key not in beams_by_section: 
            beams_by_section[section_key] = []
            
        beams_by_section[section_key].append({
            "beam_obj": beam, 
            "geo_brep": rh_geo, 
            "name": beam_name,
            "length_x": beam_length, 
            "width_y": width_box, 
            "height_z": height_box, 
            "needed_len": needed_len
        })

    # 2. ESECUZIONE ALGORITMO BIN PACKING INDUSTRIALE
    packed_bars = []
    bar_global_counter = 1
    
    for section_key in sorted(beams_by_section.keys()):
        sec_w, sec_h = section_key
        current_allowed_s_len = get_assigned_stock_length(sec_w, sec_h)
        usable_cutting_length = current_allowed_s_len - (2.0 * side_gap)
        
        section_beams = sorted(beams_by_section[section_key], key=lambda x: x["length_x"], reverse=True)
        section_bars = []
        
        for item in section_beams:
            needed = item["needed_len"]
            placed = False
            for bar in section_bars:
                if bar["remaining"] >= needed:
                    current_start = bar["current_pos"]
                    bar["beams"].append({
                        "item_data": item, 
                        "start_pos": current_start, 
                        "visual_start_x": current_start + h_gap + side_gap
                    })
                    bar["remaining"] -= needed
                    bar["current_pos"] += needed
                    placed = True
                    break
            if not placed:
                new_bar = {
                    "id": bar_global_counter, 
                    "section": section_key, 
                    "stock_len_assigned": current_allowed_s_len,
                    "remaining": usable_cutting_length - needed, 
                    "current_pos": needed,
                    "beams": [{"item_data": item, "start_pos": 0.0, "visual_start_x": h_gap + side_gap}]
                }
                section_bars.append(new_bar)
                packed_bars.append(new_bar)
                bar_global_counter += 1

    # 3. GENERAZIONE LAYOUT DI TAGLIO ORIZZONTALE SDRAIATO
    arranged_boxes, max_len_boxes, stock_beams, max_len_lines, arranged_names, label_curves, max_len_num_txt, dimensions, report_sections = [], [], [], [], [], [], [], [], []
    total_waste_material, total_material_bought = 0.0, 0.0
    current_y_accumulator = base_pt.Y
    previous_section = None

    for bar in sorted(packed_bars, key=lambda b: b["id"]):
        sec_w, sec_h = bar["section"]
        if previous_section is not None and bar["section"] != previous_section: 
            current_y_accumulator += distacco_tra_sezioni
        elif previous_section is not None: 
            current_y_accumulator += beam_spacing
            
        y_pos = current_y_accumulator
        previous_section = bar["section"]
        total_waste_material += bar["remaining"] + (2.0 * side_gap)
        this_bar_stock_len = bar["stock_len_assigned"]
        total_material_bought += this_bar_stock_len

        # Generazione barre commerciali di stock
        stock_x_interval, stock_y_interval, stock_z_interval = rg.Interval(0, this_bar_stock_len), rg.Interval(0, sec_w), rg.Interval(0, sec_h)
        single_stock_bar = rg.Box(rg.Plane.WorldXY, stock_x_interval, stock_y_interval, stock_z_interval).ToBrep()
        bbox_stock = single_stock_bar.GetBoundingBox(True)
        single_stock_bar.Transform(rg.Transform.Translation(base_pt.X - bbox_stock.Min.X, y_pos - bbox_stock.Min.Y, base_pt.Z - bbox_stock.Min.Z))
        stock_beams.append(single_stock_bar)

        for b_info in sorted(bar["beams"], key=lambda x: x["start_pos"]):
            item = b_info["item_data"]
            target_x = base_pt.X + b_info["visual_start_x"]
            beam_obj = item["beam_obj"]
            
            # SDRAIAMENTO ORIZZONTALE: Trasformazione rigida da 3D a WorldXY piano di taglio
            pure_beam_geo = item["geo_brep"].DuplicateBrep()
            
            if hasattr(beam_obj, "frame") and beam_obj.frame:
                pt = rg.Point3d(beam_obj.frame.point.x, beam_obj.frame.point.y, beam_obj.frame.point.z)
                xaxis = rg.Vector3d(beam_obj.frame.xaxis.x, beam_obj.frame.xaxis.y, beam_obj.frame.xaxis.z)
                yaxis = rg.Vector3d(beam_obj.frame.yaxis.x, beam_obj.frame.yaxis.y, beam_obj.frame.yaxis.z)
                local_plane = rg.Plane(pt, xaxis, yaxis)
                
                flatten_xform = rg.Transform.PlaneToPlane(local_plane, rg.Plane.WorldXY)
                pure_beam_geo.Transform(flatten_xform)

            # Posizionamento lineare millimetrico dentro la barra annidata
            bbox_init = pure_beam_geo.GetBoundingBox(True)
            pure_beam_geo.Transform(rg.Transform.Translation(0.0 - bbox_init.Min.X, 0.0 - bbox_init.Min.Y, 0.0 - bbox_init.Min.Z))
            bbox_current_beam = pure_beam_geo.GetBoundingBox(True)
            pure_beam_geo.Transform(rg.Transform.Translation(target_x - bbox_current_beam.Min.X, y_pos - bbox_current_beam.Min.Y, base_pt.Z - bbox_current_beam.Min.Z))
            arranged_boxes.append(pure_beam_geo)

            # Generazione scatole di ingombro nominali
            raw_box_geo = rg.Box(rg.Plane.WorldXY, rg.Interval(0, item["length_x"]), rg.Interval(0, item["width_y"]), rg.Interval(0, item["height_z"])).ToBrep()
            bbox_current_raw = raw_box_geo.GetBoundingBox(True)
            raw_box_geo.Transform(rg.Transform.Translation(target_x - bbox_current_raw.Min.X, y_pos - bbox_current_raw.Min.Y, base_pt.Z - bbox_current_raw.Min.Z))
            max_len_boxes.append(raw_box_geo)

            new_bbox = pure_beam_geo.GetBoundingBox(True)
            exact_top_z = base_pt.Z + item["height_z"]
            
            # Linee di mezzeria d'ingombro
            max_len_lines.append(rg.Line(rg.Point3d(new_bbox.Min.X, new_bbox.Min.Y, exact_top_z + 0.01), rg.Point3d(new_bbox.Min.X + item["length_x"], new_bbox.Min.Y, exact_top_z + 0.01)))
            arranged_names.append(item["name"])

            # Annotazioni bidimensionali sul banco
            lbl_x, lbl_y = (new_bbox.Min.X + new_bbox.Max.X) / 2.0, (new_bbox.Min.Y + new_bbox.Max.Y) / 2.0
            label_curves.extend(create_geometry_text(item["name"], rg.Point3d(lbl_x, lbl_y, exact_top_z + l_off), text_height=0.04))
            max_len_num_txt.extend(create_geometry_text("{:.2f}m".format(item["length_x"]), rg.Point3d(lbl_x, lbl_y - 0.08, exact_top_z + l_off), text_height=0.04))

            dimensions.append("Stock beam n°: {} | {} | Sezione: {:.1f}x{:.1f}cm | L: {:.3f}m".format(bar["id"], item["name"], sec_w*100.0, sec_h*100.0, item["length_x"]))

    # 4. RENDICONTO STATISTICO ECONOMICO
    for sec in sorted(beams_by_section.keys()):
        sec_bars = [b for b in packed_bars if b["section"] == sec]
        sec_num_stocks = len(sec_bars)
        allocated_s_len = get_assigned_stock_length(sec[0], sec[1])
        sec_material = sum(b["stock_len_assigned"] for b in sec_bars)
        sec_waste = sum(b["remaining"] for b in sec_bars) + (sec_num_stocks * 2.0 * side_gap)
        sec_eff = ((sec_material - sec_waste) / sec_material) * 100.0 if sec_material > 0 else 0.0
        report_sections.append("--- PACKING REPORT: Querschnitt {:.2f} x {:.2f} m ---\nStock Length used: {:.2f} m\nStocks needed:     {} pcs\nTotal Material:    {:.2f} m\nTotal Waste:       {:.2f} m\nEfficiency:        {:.1f}%\nPrice/m:           {:.2f} EUR\nEstimated Cost:    {:.2f} EUR\n--------------------------------------------------".format(sec[0], sec[1], allocated_s_len, sec_num_stocks, sec_material, sec_waste, sec_eff, p_lm, sec_material * p_lm))

    total_efficiency = ((total_material_bought - total_waste_material) / total_material_bought) * 100.0 if total_material_bought > 0 else 0.0
    report_string = "==================================================\n        REPORT DETTAGLIATO NESTING INDUSTRIALE    \n==================================================\n" + "\n\n".join(report_sections) + "\n\n--- TOTAL PACKING SUMMARY ---\nTotal Stocks needed: {} pcs\nTotal Material:      {:.2f} m\nTotal Waste:         {:.2f} m\nTotal Efficiency:    {:.1f}%\nTotal Cost:          {:.2f} EUR\n-----------------------------\n==================================================".format(len(packed_bars), total_material_bought, total_waste_material, total_efficiency, total_material_bought * p_lm)

    return arranged_boxes, max_len_boxes, stock_beams, max_len_lines, arranged_names, label_curves, max_len_num_txt, dimensions, report_string