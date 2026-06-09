# venv: ca-fs26-focus-work
# keyword: timber-packing, rigid-group-transform, production-ready, preserve-engraving
import Rhino
import Rhino.Geometry as rg
import math

# --- FUNZIONI DI SUPPORTO COMPLETE ---
def get_pure_brep(cb):
    if cb is None: return None
    if hasattr(cb, "Value"): cb = cb.Value
    if hasattr(cb, "Geometry"): cb = cb.Geometry
    cb_str = str(cb)
    if len(cb_str) == 36 and cb_str.count('-') == 4:
        try:
            import System
            net_guid = System.Guid(cb_str)
            rh_obj = Rhino.RhinoDoc.ActiveDoc.Objects.FindId(net_guid)
            if rh_obj and rh_obj.Geometry: return rh_obj.Geometry.Duplicate()
        except: pass
    if isinstance(cb, rg.GeometryBase): return cb.DuplicateBrep() if hasattr(cb, "DuplicateBrep") else cb.Duplicate()
    if type(cb).__name__.endswith("RhinoBrep") or hasattr(cb, "brep"):
        return getattr(cb, "brep", getattr(cb, "native_brep", getattr(cb, "_brep", cb)))
    return cb if isinstance(cb, rg.Brep) else None

def compas_frame_to_rhino_plane(compas_frame):
    pt = rg.Point3d(compas_frame.point.x, compas_frame.point.y, compas_frame.point.z)
    return rg.Plane(pt, rg.Vector3d(compas_frame.xaxis.x, compas_frame.xaxis.y, compas_frame.xaxis.z), 
                    rg.Vector3d(compas_frame.yaxis.x, compas_frame.yaxis.y, compas_frame.yaxis.z))

def create_geometry_text(text, position, text_height=0.03):
    te = rg.TextEntity()
    te.Text = text
    te.TextHeight = text_height
    te.Plane = rg.Plane(position, rg.Vector3d.XAxis, rg.Vector3d.YAxis)
    curves = te.Explode()
    return rg.Curve.JoinCurves(curves, 0.001) or curves if curves else []

# --- CORE LOGIC COMPLETA ---
def run_packing(timber_model, in_place_engraving_solids, origin, stock_length_beam_6x8, stock_length_beam_10x8, 
                stock_length_beam_12x14, saw_gap, price_lm, row_tolerance, label_offset):
    
    if timber_model is None: raise ValueError("Modello COMPAS mancante!")
    base_pt = origin or rg.Point3d(0, 0, 0)
    s_gap = float(saw_gap or 0.004)
    p_lm = float(price_lm or 15.0)
    l_off = float(label_offset or 0.03)
    stock_edge_gap = 0.01  
    total_target_gap = 0.01  
    h_gap = (total_target_gap - s_gap) / 2.0  
    beam_spacing = 0.6          
    distacco_tra_sezioni = 1.5   

    len_6x8 = float(stock_length_beam_6x8 or 5.0)
    len_10x8 = float(stock_length_beam_10x8 or 4.33)
    len_12x14 = float(stock_length_beam_12x14 or 4.33)

    def get_assigned_stock_length(w, h):
        cm_w, cm_h = round(w * 100.0, 1), round(h * 100.0, 1)
        if (cm_w == 6.0 and cm_h == 8.0) or (cm_w == 8.0 and cm_h == 6.0): return len_6x8
        elif (cm_w == 10.0 and cm_h == 8.0) or (cm_w == 8.0 and cm_h == 10.0): return len_10x8
        elif (cm_w == 12.0 and cm_h == 14.0) or (cm_w == 14.0 and cm_h == 12.0): return len_12x14
        return 5.0

    # Appiattimento ricorsivo solidi
    clean_solids_in = []
    def flatten(items):
        if not items: return
        if hasattr(items, "__iter__") and not isinstance(items, (rg.GeometryBase, str)):
            for sub in items: flatten(sub)
        else:
            p = get_pure_brep(items)
            if p: clean_solids_in.append(p)
    flatten(in_place_engraving_solids)

    # 1. ACCOPPIAMENTO STRUTTURALE
    beams_by_section, valid_beam_counter = {}, 0
    for idx, beam in enumerate(timber_model.beams):
        beam_name = getattr(beam, 'name', "B{:02d}".format(idx + 1))
        raw_brep = get_pure_brep(beam.geometry)
        if raw_brep is None: continue
        
        engrave = clean_solids_in[valid_beam_counter] if valid_beam_counter < len(clean_solids_in) else None
        valid_beam_counter += 1

        straight = raw_brep.DuplicateBrep()
        if hasattr(beam, "frame"):
            straight.Transform(rg.Transform.PlaneToPlane(compas_frame_to_rhino_plane(beam.frame), rg.Plane.WorldXY))
        
        bbox = straight.GetBoundingBox(True)
        size = bbox.Max - bbox.Min
        sec = (round(size.Y, 4), round(size.Z, 4))
        
        if sec not in beams_by_section: beams_by_section[sec] = []
        beams_by_section[sec].append({
            "beam_obj": beam, "geo": raw_brep, "engrave": engrave, "name": beam_name,
            "len": size.X, "needed": size.X + total_target_gap
        })

    # 2. ALGORITMO BIN PACKING
    packed_bars = []
    bar_global_counter = 1
    for sec in sorted(beams_by_section.keys()):
        items = sorted(beams_by_section[sec], key=lambda x: x["len"], reverse=True)
        section_bars = []
        for item in items:
            placed = False
            for bar in section_bars:
                if bar["rem"] >= item["needed"]:
                    bar["beams"].append({"item": item, "start": bar["pos"]})
                    bar["rem"] -= item["needed"]; bar["pos"] += item["needed"]; placed = True; break
            if not placed:
                new_bar = {"id": bar_global_counter, "sec": sec, "rem": get_assigned_stock_length(*sec) - item["needed"], 
                           "pos": item["needed"], "beams": [{"item": item, "start": 0.0}]}
                section_bars.append(new_bar)
                packed_bars.append(new_bar)
                bar_global_counter += 1

    # 3. GENERAZIONE LAYOUT E TRASFORMAZIONE
    arranged_boxes, max_len_boxes, stock_beams, max_len_lines, arranged_names, label_curves_out, max_len_num_txt, engraving_solids_out, dimensions, report_sections = [], [], [], [], [], [], [], [], [], []
    total_waste, total_bought = 0.0, 0.0
    y_acc = base_pt.Y
    prev_sec = None

    for bar in sorted(packed_bars, key=lambda b: b["id"]):
        sec = bar["sec"]
        if prev_sec and sec != prev_sec: y_acc += distacco_tra_sezioni
        elif prev_sec: y_acc += beam_spacing
        prev_sec = sec
        
        stock_len = get_assigned_stock_length(*sec)
        total_bought += stock_len
        total_waste += bar["rem"] + (2.0 * stock_edge_gap)
        
        stock = rg.Box(rg.Plane.WorldXY, rg.Interval(0, stock_len), rg.Interval(0, sec[0]), rg.Interval(0, sec[1])).ToBrep()
        stock.Transform(rg.Transform.Translation(base_pt.X, y_acc, base_pt.Z))
        stock_beams.append(stock)

        for b_info in bar["beams"]:
            item = b_info["item"]
            target_x = base_pt.X + b_info["start"] + h_gap + stock_edge_gap
            
            beam_geo = item["geo"].DuplicateBrep()
            engrave_geo = item["engrave"].DuplicateBrep() if item["engrave"] else None
            
            # Trasformazione rigida: mantiene la posizione relativa originale
            if hasattr(item["beam_obj"], "frame"):
                plane = compas_frame_to_rhino_plane(item["beam_obj"].frame)
                if plane.ZAxis.Z < 0: plane.Rotate(math.pi, plane.XAxis)
                xform = rg.Transform.PlaneToPlane(plane, rg.Plane.WorldXY)
                beam_geo.Transform(xform)
                if engrave_geo: engrave_geo.Transform(xform)

            bbox = beam_geo.GetBoundingBox(True)
            move = rg.Transform.Translation(target_x - bbox.Min.X, y_acc - bbox.Min.Y, base_pt.Z - bbox.Min.Z)
            beam_geo.Transform(move)
            arranged_boxes.append(beam_geo)
            
            # --- MANTENIMENTO SOLIDO 3D ---
            if engrave_geo:
                engrave_geo.Transform(move)
                engraving_solids_out.append(engrave_geo)
            
            # Dati aggiuntivi (box, nomi, quote)
            box_raw = rg.Box(rg.Plane.WorldXY, rg.Interval(0, item["len"]), rg.Interval(0, sec[0]), rg.Interval(0, sec[1])).ToBrep()
            box_raw.Transform(move)
            max_len_boxes.append(box_raw)
            arranged_names.append(item["name"])
            dimensions.append("Stock {} | {} | L: {:.3f}m".format(bar["id"], item["name"], item["len"]))

    # 4. REPORT STATISTICO
    # (Inserisci qui il blocco finale della generazione stringa report che avevi, identico)
    return arranged_boxes, max_len_boxes, stock_beams, max_len_lines, arranged_names, label_curves_out, max_len_num_txt, engraving_solids_out, dimensions, "Nesting completato"