# venv: ca-fs26-focus-work
# keyword: timber-packing, 90-deg-beam-rotation, vacuum-area-boolean, blank-length-diagnostic
import Rhino.Geometry as rg
import math
from importlib import reload
from compas.geometry import Rotation, Vector

class CutItem:
    def __init__(self, beam_id, beam_name, original_beam, width, length, height):
        self.id = beam_id
        self.name = beam_name
        self.original_beam = original_beam
        self.width = width
        self.length = length
        self.height = height
        self.center_pt = None


def create_geometry_text(text, position, text_height=0.03, rotation=0.0):
    """Create editable 2D Rhino text, not exploded curves or hatches."""
    te = rg.TextEntity()
    te.Text = text
    te.FontIndex = 0
    te.TextHeight = text_height
    
    plane = rg.Plane.WorldXY
    plane.Origin = position
    te.Plane = plane

    bbox = te.GetBoundingBox(True)
    if bbox.IsValid:
        center_x = (bbox.Max.X + bbox.Min.X) / 2.0
        center_y = (bbox.Max.Y + bbox.Min.Y) / 2.0
        move_to_center = rg.Transform.Translation(position.X - center_x, position.Y - center_y, 0)
        te.Transform(move_to_center)

    if rotation != 0.0:
        te.Transform(rg.Transform.Rotation(rotation, rg.Vector3d.ZAxis, position))

    return [te]


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
    """Extracts the clean Rhino geometry by unwrapping COMPAS wrappers."""
    if cb is None:
        return None
    if hasattr(cb, "Geometry"):
        return cb.Geometry
    if hasattr(cb, "Value"):
        return cb.Value
    if type(cb).__name__.endswith("RhinoBrep") or hasattr(cb, "brep"):
        return getattr(cb, "brep", getattr(cb, "native_brep", getattr(cb, "_brep", cb)))
    return cb


def get_rhino_brep_from_compas_geometry(geo):
    """Converts COMPAS/Rhino wrapped geometry to a native Rhino Brep when possible."""
    if geo is None:
        return None
    if hasattr(geo, "to_rhino"):
        return geo.to_rhino()
    if hasattr(geo, "to_brep"):
        brep = geo.to_brep()
        if hasattr(brep, "to_rhino"):
            return brep.to_rhino()
        return get_pure_brep(brep)
    return get_pure_brep(geo)


def duplicate_rhino_geometry(geo):
    if geo is None:
        return None
    if hasattr(geo, "DuplicateBrep"):
        return geo.DuplicateBrep()
    if hasattr(geo, "Duplicate"):
        return geo.Duplicate()
    return None


def get_longest_brep_edge_length(brep):
    if brep is None or not hasattr(brep, "Edges"):
        return None
    edge_lengths = []
    for edge in brep.Edges:
        try:
            edge_lengths.append(float(edge.GetLength()))
        except:
            try:
                edge_lengths.append(float(edge.EdgeCurve.GetLength()))
            except:
                pass
    return max(edge_lengths) if edge_lengths else None


def get_blank_geometry_length(beam):
    blank = getattr(beam, "blank", None)
    for attr in ("length", "lenght", "xsize", "x_size", "size_x"):
        try:
            value = float(getattr(blank, attr))
            if value > 0:
                return value, "beam.blank.{}".format(attr)
        except:
            pass
    return None, "beam.blank measured geometry fallback"


def compas_frame_to_rhino_plane(compas_frame):
    """Converts a COMPAS Frame to a Rhino Plane."""
    pt = rg.Point3d(compas_frame.point.x, compas_frame.point.y, compas_frame.point.z)
    xaxis = rg.Vector3d(compas_frame.xaxis.x, compas_frame.xaxis.y, compas_frame.xaxis.z)
    yaxis = rg.Vector3d(compas_frame.yaxis.x, compas_frame.yaxis.y, compas_frame.yaxis.z)
    return rg.Plane(pt, xaxis, yaxis)


def run_packing(timber_model, origin, stock_length_beam_6x8, stock_length_beam_10x8, 
                stock_length_beam_12x14, saw_gap, price_lm, row_tolerance, label_offset):
    
    if timber_model is None or not hasattr(timber_model, "joints"):
        raise ValueError("ERROR: Missing or invalid COMPAS Model!")

    base_pt = origin if origin is not None else rg.Point3d(0, 0, 0)
    s_gap = float(saw_gap) if saw_gap is not None else 0.004
    p_lm = float(price_lm) if price_lm is not None else 15.0
    l_off = float(label_offset) if label_offset is not None else 0.03

    total_target_gap = 0.01  
    h_gap = (total_target_gap - s_gap) / 2.0  
    stock_edge_gap = 0.01  
    beam_spacing = 0.6
    section_gap = 1.5

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

    # 1. STRAIGHTENING, 90° ROTATION, AND GROUPING OF BEAMS BY SECTION
    beams_by_section = {}
    
    # NEW: Lists for rotation logic
    beams_to_rotate_info = [] # Stores (beam_object, original_name) for beams with more bottom joints
    rotated_beam_names = [] # Stores names of beams that were rotated

    # First Pass: Identify beams for rotation and collect initial joint data
    for idx, beam in enumerate(timber_model.beams):
        
        # === DIRECT NAME RETRIEVAL FROM THE PREVIOUS NAMING COMPONENT ===
        correct_name = None
        if hasattr(beam, "name") and beam.name:
            correct_name = str(beam.name)
        elif hasattr(beam, "attributes") and isinstance(beam.attributes, dict) and "name" in beam.attributes:
            correct_name = str(beam.attributes["name"])
            
        # Extreme fallback if the string is empty
        if not correct_name:
            correct_name = "B{:02d}".format(idx + 1)

        # Count joints to avoid rotating if the number of joints is the same
        u_count, b_count = 0, 0
        for joint in timber_model.get_joints_for_element(beam):
            r_idx = None
            j_name = type(joint).__name__
            if "TButt" in j_name and getattr(joint, "cross_beam", None) == beam:
                r_idx = getattr(joint, "cross_beam_ref_side_index", None)
            elif "Lap" in j_name:
                if getattr(joint, "beam_a", None) == beam:
                    r_idx = getattr(joint, "ref_side_index_a", None)
                elif getattr(joint, "beam_b", None) == beam:
                    r_idx = getattr(joint, "ref_side_index_b", None)
            if r_idx is not None:
                try:
                    norm = beam.ref_sides[int(r_idx)].normal
                    if norm.z > 0.7: u_count += 1
                    elif norm.z < -0.7: b_count += 1
                except: pass

        # NEW: Geometric check to ensure all beams "face up" in the layout.
        # This logic determines the "true up" for a slanted beam and checks if its
        # local Y-axis (which becomes the top in the CNC layout) is aligned with it.
        beam_x = beam.frame.xaxis.unitized()
        global_z = Vector(0, 0, 1)
        
        # If beam is vertical, this cross product is zero. Handle this case.
        if abs(beam_x.dot(global_z)) > 0.999:
            # For vertical beams, we can define 'up' based on the global Y axis.
            true_up = Vector(0, 1, 0)
        else:
            horizontal_ref = beam_x.cross(global_z)
            true_up = horizontal_ref.cross(beam_x)
            true_up.unitize()

        # Check if the beam's local Y-axis is pointing "down" relative to the true up.
        # AND do not turn 180 degrees if the number of joints is the same
        if beam.frame.yaxis.dot(true_up) < 0 and u_count != b_count:
            beams_to_rotate_info.append((beam, correct_name))
            
    # Second Pass: Apply rotations to identified beams
    for beam_obj, name in beams_to_rotate_info:
        rotation_axis = beam_obj.frame.xaxis
        rotation_matrix = Rotation.from_axis_and_angle(rotation_axis, math.pi) # 180 degrees
        beam_obj.frame.transform(rotation_matrix)
        rotated_beam_names.append(name)
        
    # Third Pass: Recalculate joint counts for the final summary (after rotations)
    raw_joint_face_summary = []
    for idx, beam in enumerate(timber_model.beams): # Iterate again to get post-rotation state

        # === DIRECT NAME RETRIEVAL ===
        correct_name = None
        if hasattr(beam, "name") and beam.name:
            correct_name = str(beam.name)
        elif hasattr(beam, "attributes") and isinstance(beam.attributes, dict) and "name" in beam.attributes:
            correct_name = str(beam.attributes["name"])
            
        if not correct_name:
            correct_name = "B{:02d}".format(idx + 1)

        # Count joints on upper and bottom faces (post-rotation state)
        u_count, b_count = 0, 0
        for joint in timber_model.get_joints_for_element(beam):
            r_idx = None
            j_name = type(joint).__name__
            if "TButt" in j_name and getattr(joint, "cross_beam", None) == beam:
                r_idx = getattr(joint, "cross_beam_ref_side_index", None)
            elif "Lap" in j_name:
                if getattr(joint, "beam_a", None) == beam:
                    r_idx = getattr(joint, "ref_side_index_a", None)
                elif getattr(joint, "beam_b", None) == beam:
                    r_idx = getattr(joint, "ref_side_index_b", None)
            if r_idx is not None:
                try:
                    norm = beam.ref_sides[int(r_idx)].normal
                    if norm.z > 0.7: u_count += 1
                    elif norm.z < -0.7: b_count += 1
                except: pass
        raw_joint_face_summary.append({"name": correct_name, "bottom": b_count, "upper": u_count})

        blank_geo = getattr(beam, "blank", None)
        raw_blank_brep = get_rhino_brep_from_compas_geometry(blank_geo)
        if raw_blank_brep is None:
            raise ValueError("Beam {} has no usable beam.blank geometry for packing.".format(correct_name))

        straight_blank_brep = duplicate_rhino_geometry(raw_blank_brep)
        if straight_blank_brep is None:
            raise ValueError("Beam {} beam.blank could not be duplicated as Rhino geometry.".format(correct_name))
        
        blank_frame = getattr(blank_geo, "frame", None) or getattr(beam, "frame", None)
        flatten_trans = None
        if blank_frame:
            local_plane = compas_frame_to_rhino_plane(blank_frame)
            flatten_trans = rg.Transform.PlaneToPlane(local_plane, rg.Plane.WorldXY)
            straight_blank_brep.Transform(flatten_trans)
            
        # Longitudinal 90-degree flip aligned with the X-axis
        rotate_90_x = rg.Transform.Rotation(math.pi / 2.0, rg.Vector3d.XAxis, rg.Point3d(0, 0, 0))
        straight_blank_brep.Transform(rotate_90_x)
        
        blank_edge_len = get_longest_brep_edge_length(straight_blank_brep)
        if blank_edge_len is None:
            raise ValueError("Beam {} beam.blank has no measurable Brep edges.".format(correct_name))

        native_blank_len, blank_source = get_blank_geometry_length(beam)
        chosen_packing_length = native_blank_len if native_blank_len is not None else blank_edge_len

        local_bbox = straight_blank_brep.GetBoundingBox(True)
        if local_bbox and local_bbox.IsValid:
            size_box = local_bbox.Max - local_bbox.Min
            width_box, height_box = round(size_box.Y, 4), round(size_box.Z, 4)
            blank_min_x, blank_min_y, blank_min_z = local_bbox.Min.X, local_bbox.Min.Y, local_bbox.Min.Z
        else:
            width_box, height_box = 0.12, 0.14
            blank_min_x, blank_min_y, blank_min_z = 0.0, 0.0, 0.0

        # Retrieval of the true final cut and shaped geometry.
        # It must receive the exact same flatten/rotation as beam.blank so its
        # offset inside the blank is preserved in the packing layout.
        straight_cut_brep = None
        cut_length = None
        raw_cut_brep = get_pure_brep(beam.geometry)
        if raw_cut_brep is not None:
            straight_cut_brep = duplicate_rhino_geometry(raw_cut_brep)
            if straight_cut_brep is not None:
                if flatten_trans:
                    straight_cut_brep.Transform(flatten_trans)
                straight_cut_brep.Transform(rotate_90_x)
                cut_bbox = straight_cut_brep.GetBoundingBox(True)
                if cut_bbox and cut_bbox.IsValid:
                    cut_length = (cut_bbox.Max - cut_bbox.Min).X

        needed_len = chosen_packing_length + total_target_gap
        
        section_key = (width_box, height_box)
        if section_key not in beams_by_section: beams_by_section[section_key] = []
        beams_by_section[section_key].append({
            "beam_obj": beam, 
            "blank_brep": straight_blank_brep, 
            "cut_brep": straight_cut_brep, 
            "name": correct_name,
            "length_x": chosen_packing_length, 
            "blank_length": chosen_packing_length, 
            "blank_length_native": native_blank_len,
            "cut_length": cut_length, 
            "blank_source": blank_source,
            "width_y": width_box, 
            "height_z": height_box, 
            "blank_min": (blank_min_x, blank_min_y, blank_min_z),
            "needed_len": needed_len
        })

    # Sort joint_face_summary by beam name (e.g., A1, A2, B1, B2)
    joint_face_summary = []
    # Sort joint_face_summary by beam name (e.g., A1, A2, B1, B2)
    def sort_key_for_beam_name(item):
        name = item["name"]
        import re
        match = re.match(r'([A-Z]+)(\d+)', name)
        return (match.group(1), int(match.group(2))) if match else (name, 0)

    for item in sorted(raw_joint_face_summary, key=sort_key_for_beam_name):
        joint_face_summary.append("beam {}, bottom: {}, upper: {}".format(item["name"], item["bottom"], item["upper"]))
    # 2. EXECUTION OF BIN PACKING ALGORITHM
    packed_bars = []
    bar_global_counter = 1
    for section_key in sorted(beams_by_section.keys()):
        sec_w, sec_h = section_key
        current_allowed_s_len = get_assigned_stock_length(sec_w, sec_h)
        usable_cutting_length = current_allowed_s_len - (2.0 * stock_edge_gap)
        
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

    # 3. GENERATION OF THE COHERENT SPATIAL LAYOUT
    arranged_boxes_not_rotated = []
    arranged_boxes_rotated = []
    max_len_boxes = []
    stock_beams = []
    max_len_lines = []
    arranged_names = []
    label_curves = []
    max_len_num_txt = []
    engraving_not_rotated = []
    engraving_rotated = []
    dimensions = []
    report_sections = []
    vacuum_surfaces_out = [] 
    failed_vacuums = [] 
    vacuum_free_lines = []
    vacuum_free_measures = []
    rotated_beam_names_set = set(rotated_beam_names)
    
    total_waste_material, total_material_bought = 0.0, 0.0
    current_y_accumulator = base_pt.Y
    previous_section = None

    for bar in sorted(packed_bars, key=lambda b: b["id"]):
        sec_w, sec_h = bar["section"]
        if previous_section is not None and bar["section"] != previous_section: current_y_accumulator += section_gap
        elif previous_section is not None: current_y_accumulator += beam_spacing
        y_pos = current_y_accumulator
        previous_section = bar["section"]
        total_waste_material += bar["remaining"] + (2.0 * stock_edge_gap)
        this_bar_stock_len = bar["stock_len_assigned"]
        total_material_bought += this_bar_stock_len

        # COMMERCIAL CONTAINERS (STOCK BEAMS)
        stock_x_interval, stock_y_interval, stock_z_interval = rg.Interval(0, this_bar_stock_len), rg.Interval(0, sec_w), rg.Interval(0, sec_h)
        single_stock_bar = rg.Box(rg.Plane.WorldXY, stock_x_interval, stock_y_interval, stock_z_interval).ToBrep()
        bbox_stock = single_stock_bar.GetBoundingBox(True)
        single_stock_bar.Transform(rg.Transform.Translation(base_pt.X - bbox_stock.Min.X, y_pos - bbox_stock.Min.Y, base_pt.Z - bbox_stock.Min.Z))
        stock_beams.append(single_stock_bar)

        for b_info in sorted(bar["beams"], key=lambda x: x["start_pos"]):
            item = b_info["item_data"]
            target_x = base_pt.X + b_info["visual_start_x"]
            
            if item["cut_brep"] is not None:
                real_beam_geo = item["cut_brep"].DuplicateBrep()
            else:
                real_beam_geo = item["blank_brep"].DuplicateBrep()

            blank_min_x, blank_min_y, blank_min_z = item["blank_min"]
            real_beam_geo.Transform(rg.Transform.Translation(
                target_x - blank_min_x,
                y_pos - blank_min_y,
                base_pt.Z - blank_min_z
            ))
            
            if item["name"] in rotated_beam_names_set:
                arranged_boxes_rotated.append(real_beam_geo)
            else:
                arranged_boxes_not_rotated.append(real_beam_geo)

            # MAXIMUM DIMENSION BOXES (MAX LEN BOXES WITH BLANK_LENGTH)
            raw_box_geo = rg.Box(rg.Plane.WorldXY, rg.Interval(0, item["blank_length"]), rg.Interval(0, item["width_y"]), rg.Interval(0, item["height_z"])).ToBrep()
            bbox_current_raw = raw_box_geo.GetBoundingBox(True)
            raw_box_geo.Transform(rg.Transform.Translation(target_x - bbox_current_raw.Min.X, y_pos - bbox_current_raw.Min.Y, base_pt.Z - bbox_current_raw.Min.Z))
            max_len_boxes.append(raw_box_geo)

            new_bbox = real_beam_geo.GetBoundingBox(True)
            exact_top_z = base_pt.Z + item["height_z"]
            
            max_len_lines.append(rg.Line(rg.Point3d(target_x, y_pos, exact_top_z + 0.01), rg.Point3d(target_x + item["blank_length"], y_pos, exact_top_z + 0.01)))
            arranged_names.append(item["name"])

            lbl_x = (new_bbox.Min.X + new_bbox.Max.X) / 2.0
            lbl_y_center = (new_bbox.Min.Y + new_bbox.Max.Y) / 2.0
            lbl_y_under = lbl_y_center - (sec_w / 2.0) - l_off

            length_in_cm = item["length_x"] * 100.0

            label_curves.extend(create_geometry_text(item["name"], rg.Point3d(lbl_x, lbl_y_under, exact_top_z), text_height=0.04))
            max_len_num_txt.extend(create_geometry_text("{:.1f}cm".format(length_in_cm), rg.Point3d(lbl_x, lbl_y_under - 0.06, exact_top_z), text_height=0.04))

            # --- 3D TEXT POSITIONING IN THE SAME ORIGINAL POSITION ---
            beam_obj = item["beam_obj"]
            c_origin = beam_obj.frame.point
            c_xaxis = beam_obj.frame.xaxis
            c_yaxis = beam_obj.frame.yaxis
            c_zaxis = beam_obj.frame.zaxis
            
            rh_origin = rg.Point3d(c_origin.x, c_origin.y, c_origin.z)
            rh_xaxis = rg.Vector3d(c_xaxis.x, c_xaxis.y, c_xaxis.z)
            rh_yaxis = rg.Vector3d(c_yaxis.x, c_yaxis.y, c_yaxis.z)
            rh_zaxis = rg.Vector3d(c_zaxis.x, c_zaxis.y, c_zaxis.z)

            beam_plane = rg.Plane(rh_origin, rh_xaxis, rh_yaxis)
            
            h_offset = 0.0
            for h_attr in ['height', 'h', 'd', 'depth']:
                if hasattr(beam_obj, h_attr):
                    h_offset = float(getattr(beam_obj, h_attr))
                    break
            
            orig_geo = get_rhino_brep_from_compas_geometry(beam_obj.geometry)
            if not orig_geo:
                orig_geo = get_rhino_brep_from_compas_geometry(getattr(beam_obj, "blank", None))

            if h_offset > 0:
                beam_plane.Translate(rh_zaxis * (h_offset / 2.0))
            else:
                if orig_geo:
                    bbox_orig = orig_geo.GetBoundingBox(True)
                    if bbox_orig.IsValid:
                        beam_plane.Translate(rh_zaxis * (bbox_orig.Max.Z - rh_origin.Z))

            beam_length_for_scan = item["blank_length_native"] if item["blank_length_native"] else item["length_x"]
            beam_plane.Translate(beam_plane.XAxis * (beam_length_for_scan / 2.0))
            
            step = 0.02  
            max_shift = (beam_length_for_scan / 2.0) - 0.10  
            current_shift = 0.0
            
            scan_plane = rg.Plane(beam_plane)
            
            t_height = 0.03
            t_width_approx = len(item["name"]) * (t_height * 0.7)
            t_height_box = t_height
            
            while current_shift < max_shift:
                test_points = [
                    scan_plane.Origin,
                    scan_plane.Origin - (scan_plane.XAxis * (t_width_approx / 2.0)) - (scan_plane.YAxis * (t_height_box / 2.0)),
                    scan_plane.Origin + (scan_plane.XAxis * (t_width_approx / 2.0)) - (scan_plane.YAxis * (t_height_box / 2.0)),
                    scan_plane.Origin - (scan_plane.XAxis * (t_width_approx / 2.0)) + (scan_plane.YAxis * (t_height_box / 2.0)),
                    scan_plane.Origin + (scan_plane.XAxis * (t_width_approx / 2.0)) + (scan_plane.YAxis * (t_height_box / 2.0))
                ]
                
                area_is_fully_solid = True
                if orig_geo:
                    for pt in test_points:
                        ray_start = pt + (scan_plane.Normal * 0.01)
                        ray_end = pt - (scan_plane.Normal * 0.01)
                        ray_line = rg.Line(ray_start, ray_end).ToNurbsCurve()
                        
                        intersections = rg.Intersect.Intersection.CurveBrep(ray_line, orig_geo, 0.001)
                        
                        point_hits_solid_wood = False
                        if intersections and len(intersections[2]) > 0:
                            highest_pt = min(intersections[2], key=lambda p: p.DistanceTo(pt))
                            if highest_pt.DistanceTo(pt) < 0.006:
                                point_hits_solid_wood = True
                                
                        if not point_hits_solid_wood:
                            area_is_fully_solid = False
                            break
                
                if area_is_fully_solid:
                    break  
                
                scan_plane.Translate(scan_plane.XAxis * step)
                current_shift += step

            beam_plane = rg.Plane(scan_plane)
            
            solid_text = create_3d_text_engraving(text=item["name"], position=rg.Point3d(0,0,0), text_height=t_height, engraving_depth=0.005)
            
            if solid_text:
                plane_to_plane_xform = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, beam_plane)
                solid_text.Transform(plane_to_plane_xform)
                solid_text.Transform(rg.Transform.Translation(-rh_zaxis * 0.005))
                
                blank_frame = getattr(getattr(beam_obj, "blank", None), "frame", None) or getattr(beam_obj, "frame", None)
                if blank_frame:
                    local_plane = compas_frame_to_rhino_plane(blank_frame)
                    flatten_trans = rg.Transform.PlaneToPlane(local_plane, rg.Plane.WorldXY)
                    solid_text.Transform(flatten_trans)
                
                rotate_90_x = rg.Transform.Rotation(math.pi / 2.0, rg.Vector3d.XAxis, rg.Point3d(0, 0, 0))
                solid_text.Transform(rotate_90_x)
                
                layout_translation = rg.Transform.Translation(
                    target_x - blank_min_x,
                    y_pos - blank_min_y,
                    base_pt.Z - blank_min_z
                )
                solid_text.Transform(layout_translation)
                
                if item["name"] in rotated_beam_names_set:
                    engraving_rotated.append(solid_text)
                else:
                    engraving_not_rotated.append(solid_text)

            test_x = lbl_x  # Restore test_x from the center for the vacuum logic below

            # ADAPTIVE LOGIC FOR EXACT VACUUM AREA COMPARISON
            v_width = 0.075
            v_length = 0.14
            half_l = v_length / 2.0
            half_w = v_width / 2.0
            vacuums_placed_count = 0
            first_vacuum_x = None  
            placed_vacuum_xs = []
            
            min_v_x = new_bbox.Min.X + half_l
            max_v_x = new_bbox.Max.X - half_l
            target_area = v_length * v_width
            
            for v_ratio in [0.33, 0.66]:
                x_offset_from_center = (item["length_x"] * v_ratio) - (item["length_x"] / 2.0)
                current_v_x = test_x + x_offset_from_center
                if current_v_x < min_v_x: current_v_x = min_v_x
                if first_vacuum_x is not None:
                    if current_v_x < first_vacuum_x + v_length + 0.01: current_v_x = first_vacuum_x + v_length + 0.01
                
                step_v = 0.01
                vacuum_success = False
                
                while current_v_x <= max_v_x:
                    v_box_x = rg.Interval(current_v_x - half_l, current_v_x + half_l)
                    v_box_y = rg.Interval(lbl_y_center - half_w, lbl_y_center + half_w)
                    v_box_z = rg.Interval(base_pt.Z - 0.01, base_pt.Z + 0.02)
                    
                    test_box_brep = rg.Box(rg.Plane.WorldXY, v_box_x, v_box_y, v_box_z).ToBrep()
                    res_intersections = rg.Brep.CreateBooleanIntersection(real_beam_geo, test_box_brep, 0.001)
                    
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
                                            
                        if abs(total_contact_area - target_area) < 1e-5: single_vacuum_safe = True
                    
                    if single_vacuum_safe:
                        vacuum_success = True
                        break 
                    current_v_x += step_v 
                
                if vacuum_success:
                    if first_vacuum_x is None: first_vacuum_x = current_v_x
                    vacuum_plane = rg.Plane(rg.Point3d(current_v_x, lbl_y_center, 0.0), rg.Vector3d.XAxis, rg.Vector3d.YAxis)
                    vacuum_surf = rg.PlaneSurface(vacuum_plane, rg.Interval(-half_l, half_l), rg.Interval(-half_w, half_w))
                    vacuum_surfaces_out.append(vacuum_surf)
                    vacuums_placed_count += 1
                    placed_vacuum_xs.append(current_v_x)

            if vacuums_placed_count < 2:
                failed_vacuums.append(item["name"])

            seg_points = [target_x]
            for v_x in placed_vacuum_xs:
                seg_points.append(v_x - half_l)
                seg_points.append(v_x + half_l)
            seg_points.append(target_x + item["blank_length"])
            
            lbl_y_over = lbl_y_center + (sec_w / 2.0) + l_off
            
            for i in range(0, len(seg_points), 2):
                x1 = seg_points[i]
                x2 = seg_points[i+1]
                if x2 - x1 > 0.001:
                    l_val = rg.Line(rg.Point3d(x1, lbl_y_over, exact_top_z), rg.Point3d(x2, lbl_y_over, exact_top_z))
                    vacuum_free_lines.append(l_val)
                    
                    local_x1_cm = (x1 - target_x) * 100.0
                    local_x2_cm = (x2 - target_x) * 100.0
                    
                    if i > 0:
                        txt1 = create_geometry_text("{:.1f}cm".format(local_x1_cm), rg.Point3d(x1, lbl_y_over + 0.04, exact_top_z), text_height=0.02, rotation=math.pi/2.0)
                        vacuum_free_measures.extend(txt1)
                    if i < len(seg_points) - 2:
                        txt2 = create_geometry_text("{:.1f}cm".format(local_x2_cm), rg.Point3d(x2, lbl_y_over + 0.04, exact_top_z), text_height=0.02, rotation=math.pi/2.0)
                        vacuum_free_measures.extend(txt2)

            cut_length_txt = "{:.3f}m".format(item["cut_length"]) if item["cut_length"] is not None else "n/a"
            native_blank_txt = "{:.3f}m".format(item["blank_length_native"]) if item["blank_length_native"] is not None else "n/a"
            dimensions.append("Stock bar n°: {} | {} | Sezione: {:.1f}x{:.1f}cm | L_cut_geom: {} | L_blank_pack: {:.3f}m | L_blank_native: {} -> [SORGENTE DATI: {}]".format(
                bar["id"], item["name"], sec_w*100.0, sec_h*100.0, cut_length_txt, item["blank_length"], native_blank_txt, item["blank_source"]
            ))

    # 4. STATISTICAL REPORT
    for sec in sorted(beams_by_section.keys()):
        sec_bars = [b for b in packed_bars if b["section"] == sec]
        sec_num_stocks = len(sec_bars)
        allocated_s_len = get_assigned_stock_length(sec[0], sec[1])
        sec_material = sum(b["stock_len_assigned"] for b in sec_bars)
        sec_waste = sum(b["remaining"] for b in sec_bars) + (sec_num_stocks * 2.0 * stock_edge_gap)
        sec_eff = ((sec_material - sec_waste) / sec_material) * 100.0 if sec_material > 0 else 0.0
        report_sections.append("--- PACKING REPORT: Cross-section {:.2f} x {:.2f} m ---\nStock Length used: {:.2f} m\nStocks needed:     {} pcs\nTotal Material:    {:.2f} m\nTotal Waste:       {:.2f} m\nEfficiency:        {:.1f}%\nPrice/m:           {:.2f} EUR\nEstimated Cost:    {:.2f} EUR\n--------------------------------------------------".format(sec[0], sec[1], allocated_s_len, sec_num_stocks, sec_material, sec_waste, sec_eff, p_lm, sec_material * p_lm))

    total_efficiency = ((total_material_bought - total_waste_material) / total_material_bought) * 100.0 if total_material_bought > 0 else 0.0
    report = "==================================================\n        DETAILED CUTTING REPORT    \n==================================================\n" + "\n\n".join(report_sections) + "\n\n--- TOTAL PACKING SUMMARY ---\nTotal Stocks needed: {} pcs\nTotal Material:      {:.2f} m\nTotal Waste:         {:.2f} m\nTotal Efficiency:    {:.1f}%\nTotal Cost:          {:.2f} EUR\n-----------------------------\n==================================================".format(len(packed_bars), total_material_bought, total_waste_material, total_efficiency, total_material_bought * p_lm)

    # Sort rotated_beam_names by beam name (e.g., A1, A2, B1, B2)
    def sort_key_for_name_only(name):
        import re
        match = re.match(r'([A-Z]+)(\d+)', name)
        if match:
            return (match.group(1), int(match.group(2)))
        return (name, 0)
    
    rotated_beam_names.sort(key=sort_key_for_name_only)

    return arranged_boxes_not_rotated, arranged_boxes_rotated, arranged_names, max_len_boxes, stock_beams, max_len_lines, label_curves, max_len_num_txt, engraving_not_rotated, engraving_rotated, dimensions, report, vacuum_surfaces_out, failed_vacuums, joint_face_summary, rotated_beam_names, vacuum_free_lines, vacuum_free_measures
