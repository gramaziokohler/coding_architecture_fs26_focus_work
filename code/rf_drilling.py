import math
from compas.geometry import Point, Vector, Line, intersection_line_line, distance_point_point, intersection_line_plane
from compas_timber.fabrication import Drilling
from compas_timber.connections import (
    LMiterJoint,
    TButtJoint,
    TLapJoint,
    XLapJoint,
    TStepJoint
)

class DrillingProcessor:
    def __init__(self, timber_model, screw_diameter=0.006, screw_length=0.150, screw_spacing=0.040, max_drilling_depth=None):
        self.timber_model = timber_model
        self.screw_diameter = screw_diameter
        self.screw_length = screw_length
        self.screw_spacing = screw_spacing 
        self.max_drilling_depth = max_drilling_depth
        
        self.drilling_count = 0
        self.screw_lines = []
        self.failed_screw_info = []
        self.summary_text = ""
        
        self.processed_beam_pairs = set()
        
        self.hardware_screws_by_type = {}
        self.screw_lengths_by_type = {}
        self.extrema_screws_by_type = {}
        self.miter_counts = {}

    def process_drillings(self):
        print("--- Starting Drilling Generation ---")
        
        self.drilling_count = 0
        self.screw_lines = []
        self.failed_screw_info = []
        self.summary_text = "" 
        self.processed_beam_pairs = set()
        
        self.hardware_screws_by_type = {}
        self.screw_lengths_by_type = {}
        self.extrema_screws_by_type = {}
        self.miter_counts = {}
        
        for beam in self.timber_model.beams:
            if hasattr(beam, 'features'):
                old_drillings = [f for f in beam.features if isinstance(f, Drilling)]
                for d in old_drillings:
                    try:
                        beam.remove_feature(d)
                    except AttributeError:
                        beam.features.remove(d)
        
        joints = getattr(self.timber_model, 'joints', None) or getattr(self.timber_model, 'interactions', [])
        
        for joint in joints:
            elements = getattr(joint, 'elements', None)
            if not elements and hasattr(joint, 'main_beam'):
                elements = [joint.main_beam, getattr(joint, 'cross_beam')]
                
            if not elements or len(elements) < 2 or not elements[0] or not elements[1]:
                continue
                
            def get_uid(beam):
                if "edge" in beam.attributes:
                    return str(beam.attributes["edge"])
                else:
                    mid = beam.centerline.midpoint
                    return f"{round(mid.x, 3)}_{round(mid.y, 3)}_{round(mid.z, 3)}"
                    
            uid_a = get_uid(elements[0])
            uid_b = get_uid(elements[1])
            pair_id = frozenset([uid_a, uid_b])
            
            if pair_id in self.processed_beam_pairs:
                continue 
                
            self.processed_beam_pairs.add(pair_id)
            
            # --- ROUTING SYSTEM ---
            if isinstance(joint, TButtJoint):
                # 1. Resolve beam identities
                if hasattr(joint, 'main_beam') and hasattr(joint, 'cross_beam'):
                    cont_beam = joint.main_beam
                    abut_beam = joint.cross_beam
                else:
                    line1, line2 = elements[0].centerline, elements[1].centerline
                    res = intersection_line_line(line1, line2)
                    if not res or res[0] is None: continue
                    mid_pt = Point(*res[0])
                    d1 = min(distance_point_point(mid_pt, line1.start), distance_point_point(mid_pt, line1.end))
                    d2 = min(distance_point_point(mid_pt, line2.start), distance_point_point(mid_pt, line2.end))
                    if d1 < d2:
                        abut_beam, cont_beam = elements[0], elements[1]
                    else:
                        abut_beam, cont_beam = elements[1], elements[0]

                # 2. Check categories and explicitly route to separate methods
                cat_c = cont_beam.attributes.get("category", "inner")
                cat_a = abut_beam.attributes.get("category", "inner")
                
                if cat_c == "base" or cat_a == "base":
                    # Fix identities if custom solver flipped them
                    if cat_a == "base":  
                        cont_beam, abut_beam = abut_beam, cont_beam
                    self._apply_foundation_butt_drilling(joint, abut_beam, cont_beam)
                else:
                    self._apply_standard_butt_drilling(joint)

            elif isinstance(joint, (XLapJoint, TLapJoint)):
                self._apply_lap_drilling(joint, elements[0], elements[1])
                
            elif isinstance(joint, LMiterJoint):
                cat1 = elements[0].attributes.get("category", "inner")
                cat2 = elements[1].attributes.get("category", "inner")
                if cat1 == "base" or cat2 == "base":
                    label = "Lmitter foundation"
                else:
                    label = "Lmitter arch"
                self.miter_counts[label] = self.miter_counts.get(label, 0) + 1
            
        # --- COMPILE PROCUREMENT SUMMARY TEXT ---
        log = []
        log.append("================ PROCUREMENT & DRILLING SUMMARY ================")
        log.append(f"Unique Joints Processed: {len(self.processed_beam_pairs)}")
        log.append("----------------------------------------------------------------")
        
        total_screws_overall = 0
        
        for j_type in sorted(self.hardware_screws_by_type.keys()):
            num_screws = self.hardware_screws_by_type[j_type]
            lengths = self.screw_lengths_by_type[j_type]
            total_screws_overall += num_screws
            
            if num_screws > 0:
                min_len = min(lengths) if lengths else 0
                max_len = max(lengths) if lengths else 0
                log.append(f"[{j_type}]")
                log.append(f"  -> Total Screws : {num_screws}")
                log.append(f"  -> Shortest Screw: {min_len * 1000:.1f} mm")
                log.append(f"  -> Longest Screw : {max_len * 1000:.1f} mm")
                log.append("")
                
        for m_type in sorted(self.miter_counts.keys()):
            count = self.miter_counts[m_type]
            if count > 0:
                if "foundation" in m_type.lower():
                    screws = count * 16
                    log.append(f"[{m_type}]")
                    log.append(f"  -> Total Screws : {screws} ({count} joints x 16)")
                    log.append("")
                else:
                    screws = count * 8
                    log.append(f"[{m_type}]")
                    log.append(f"  -> Total Screws : {screws} ({count} joints x 8)")
                    log.append("")
                
                total_screws_overall += screws
                
        boxes_needed = math.ceil(total_screws_overall / 100.0)
        
        log.append("----------------------------------------------------------------")
        log.append(f"TOTAL SCREWS REQUIRED  : {total_screws_overall}")
        log.append(f"BOXES TO BUY (100/box) : {boxes_needed} boxes ({boxes_needed * 100} screws)")
        log.append("================================================================")
        
        self.summary_text = "\n".join(log)
        return self.timber_model

    def _surface_entry(self, pos, screw_dir, beam):
        if not hasattr(beam, 'frame'): return None
        
        c = beam.centerline.midpoint
        vx, vy, vz = beam.frame.xaxis, beam.frame.yaxis, beam.frame.zaxis
        w, h = beam.width, beam.height
        
        planes = [
            (c + vy * (w/2.0), vy),
            (c - vy * (w/2.0), -vy),
            (c + vz * (h/2.0), vz),
            (c - vz * (h/2.0), -vz)
        ]
        
        p1 = pos
        p2 = pos - screw_dir * 5.0 
        ray_line = Line(p1, p2)
        
        candidates = []
        for pt, normal in planes:
            res = intersection_line_plane(ray_line, (pt, normal))
            if res:
                res_pt = Point(*res)
                vec = Vector.from_start_end(pos, res_pt)
                if vec.dot(screw_dir) < 1e-5:
                    vec_c = Vector.from_start_end(c, res_pt)
                    loc_y = abs(vec_c.dot(vy))
                    loc_z = abs(vec_c.dot(vz))
                    
                    if loc_y <= (w/2.0) + 0.005 and loc_z <= (h/2.0) + 0.005:
                        candidates.append(res_pt)
                        
        if not candidates: return None
        candidates.sort(key=lambda pt: distance_point_point(pos, pt))
        return candidates[0]

    # =====================================================================
    # EXPLICIT FOUNDATION BUTT DRILLING
    # =====================================================================
    def _apply_foundation_butt_drilling(self, joint, abut_beam, cont_beam):
        joint_label = "TButtJoint - foundation"
        
        line_a = abut_beam.centerline
        line_c = cont_beam.centerline
        
        res = intersection_line_line(line_a, line_c)
        if not res or res[0] is None: return False
        
        anchor_pt = Point(res[0][0], res[0][1], res[0][2])
        dir_s = line_a.direction
        d_start = distance_point_point(anchor_pt, line_a.start)
        d_end = distance_point_point(anchor_pt, line_a.end)
        
        if d_start > d_end:
            vec_to_far = Vector.from_start_end(anchor_pt, line_a.start)
        else:
            vec_to_far = Vector.from_start_end(anchor_pt, line_a.end)
            
        if dir_s.dot(vec_to_far) < 0:
            dir_s.scale(-1)
        dir_s.unitize()
        
        # Identify Contact End
        if distance_point_point(line_a.start, anchor_pt) <= distance_point_point(line_a.end, anchor_pt):
            joint_end = line_a.start
        else:
            joint_end = line_a.end

        # Horizontal direction along incoming beam
        along = Vector(dir_s.x, dir_s.y, 0.0)
        if along.length < 1e-6: along = Vector(1, 0, 0)
        along.unitize()

        screw_dir = Vector(0, 0, -1)                          
        base_pt = joint_end + along * (0.5 * cont_beam.width) 
        offset_dir = Vector(along.x, along.y, along.z)        
        offset_dir.unitize()
        target_beam = abut_beam                               

        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        
        cnc_lines = []
        hw_lines = []
        req_screw_length = self.screw_length 
        
        for pos in (base_pt + offset_vec, base_pt - offset_vec):
            head = self._surface_entry(pos, screw_dir, target_beam)
            if head is None:
                half = max(target_beam.width, target_beam.height) / 2.0
                head = pos - screw_dir * half
                
            tail = head + screw_dir * req_screw_length
            
            hw_lines.append(Line(head, tail))
            
            cnc_head = head - screw_dir * 0.010
            cnc_tail = tail + screw_dir * 0.010
            cnc_lines.append(Line(cnc_head, cnc_tail))

        return self._generate_features(cnc_lines, hw_lines, abut_beam, cont_beam, joint_label, req_screw_length)

# =====================================================================
    # EXPLICIT STANDARD BUTT DRILLING
    # =====================================================================
    def _apply_standard_butt_drilling(self, joint):
        """
        Straightforward logic: Extends the centerline of the abutting (cross) beam
        straight through the continuous (main) beam into the end-grain.
        """
        # 1. BULLETPROOF GEOMETRIC ROLE DETECTION
        # Ignore semantic labels. Find out which beam actually ends at the joint.
        elements = [joint.main_beam, joint.cross_beam]
        line1, line2 = elements[0].centerline, elements[1].centerline
        
        res = intersection_line_line(line1, line2)
        if not res or res[0] is None:
            return

        pt_a = Point(*res[0])
        pt_b = Point(*res[1])
        
        # Check which beam's endpoint is closer to the intersection
        d1 = min(distance_point_point(pt_a, line1.start), distance_point_point(pt_a, line1.end))
        d2 = min(distance_point_point(pt_b, line2.start), distance_point_point(pt_b, line2.end))
        
        # The abutting beam is the one ending at the joint (smaller distance to end)
        if d1 < d2:
            abut_beam, cont_beam = elements[0], elements[1]
            intersection_pt = pt_a
        else:
            abut_beam, cont_beam = elements[1], elements[0]
            intersection_pt = pt_b

        # 2. ESTABLISH THE DRILL AXIS
        # Now we are 100% sure we are using the centerline of the abutting beam
        centerline = abut_beam.centerline
        dir_into_abut = centerline.direction.copy()
        
        # Ensure the vector points INTO the abutting beam from the intersection
        vec_to_mid = Vector.from_start_end(intersection_pt, centerline.midpoint)
        if dir_into_abut.dot(vec_to_mid) < 0:
            dir_into_abut.scale(-1)
        dir_into_abut.unitize()

        # 3. CALCULATE DYNAMIC LENGTH & POINTS
        thickness_c = max(cont_beam.width, cont_beam.height)
        
        # Start at the exact far face of the continuous beam
        start_pt = intersection_pt - (dir_into_abut * (thickness_c / 2.0))
        
        # DYNAMIC LENGTH: Traverse full continuous beam + anchor 80mm into abutting beam
        anchor_depth = 0.080 
        raw_screw_length = thickness_c + anchor_depth
        req_screw_length = math.ceil(raw_screw_length / 0.010) * 0.010
        
        end_pt = start_pt + (dir_into_abut * req_screw_length)

        # 4. OFFSET FOR TWO SCREWS
        dir_cont = cont_beam.centerline.direction.copy()
        dir_cont.unitize()
        offset_dir = dir_into_abut.cross(dir_cont)
        
        if offset_dir.length < 1e-5:
            offset_dir = Vector(0, 0, 1) 
            
        offset_dir.unitize()
        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        
        # 5. GENERATE THE LINES
        hw_line_1 = Line(start_pt + offset_vec, end_pt + offset_vec)
        hw_line_2 = Line(start_pt - offset_vec, end_pt - offset_vec)
        
        extension = 0.050
        cnc_line_1 = Line(hw_line_1.start - (dir_into_abut * extension), hw_line_1.end + (dir_into_abut * extension))
        cnc_line_2 = Line(hw_line_2.start - (dir_into_abut * extension), hw_line_2.end + (dir_into_abut * extension))
        
        # 6. ROUTE TO FEATURE GENERATOR
        cat_a = abut_beam.attributes.get("category", "inner")
        cat_c = cont_beam.attributes.get("category", "inner")
        joint_label = "TButtJoint - arch" if cat_a == "arch" or cat_c == "arch" else "TButtJoint - inner"
        
        self._generate_features(
            [cnc_line_1, cnc_line_2], 
            [hw_line_1, hw_line_2], 
            abut_beam, 
            cont_beam, 
            joint_label, 
            req_screw_length
        )

    # =====================================================================
    # EXPLICIT LAP DRILLING
    # =====================================================================
    def _apply_lap_drilling(self, joint, beam_a, beam_b):
        joint_label = type(joint).__name__
        line_a, line_b = beam_a.centerline, beam_b.centerline
        
        res = intersection_line_line(line_a, line_b)
        if not res or res[0] is None: return False
            
        pt_a = Point(res[0][0], res[0][1], res[0][2])
        pt_b = Point(res[1][0], res[1][1], res[1][2])
        mid_pt = Point((pt_a.x + pt_b.x) / 2.0, (pt_a.y + pt_b.y) / 2.0, (pt_a.z + pt_b.z) / 2.0)
        
        dir_a, dir_b = line_a.direction, line_b.direction
        screw_dir = dir_a.cross(dir_b)
        
        if screw_dir.length < 1e-5:
            screw_dir = beam_a.frame.zaxis if hasattr(beam_a, 'frame') else Vector(0, 0, 1)
        else:
            screw_dir.unitize()
            
        offset_dir = dir_a + dir_b
        if offset_dir.length < 1e-5: offset_dir = dir_a 
        offset_dir.unitize()
        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        center_1 = mid_pt + offset_vec
        center_2 = mid_pt - offset_vec
        
        dist_centers = distance_point_point(pt_a, pt_b)
        
        thickness_a = math.sqrt(beam_a.width**2 + beam_a.height**2)
        thickness_b = math.sqrt(beam_b.width**2 + beam_b.height**2)
        true_total_thickness = dist_centers + (thickness_a / 2.0) + (thickness_b / 2.0)
        
        req_screw_length = true_total_thickness - 0.010 
        req_screw_length = math.floor(req_screw_length / 0.010) * 0.010 
        if req_screw_length < 0.040: req_screw_length = 0.040 
        
        hw_start_1 = center_1 - (screw_dir * (req_screw_length / 2.0))
        hw_end_1 = center_1 + (screw_dir * (req_screw_length / 2.0))
        hw_start_2 = center_2 - (screw_dir * (req_screw_length / 2.0))
        hw_end_2 = center_2 + (screw_dir * (req_screw_length / 2.0))
        
        hw_line_1 = Line(hw_start_1, hw_end_1)
        hw_line_2 = Line(hw_start_2, hw_end_2)
        
        cnc_overhang = 0.250 
        start_offset = (true_total_thickness / 2.0) + cnc_overhang
        
        cnc_start_1 = center_1 - (screw_dir * start_offset)
        cnc_end_1 = center_1 + (screw_dir * start_offset)
        cnc_start_2 = center_2 - (screw_dir * start_offset)
        cnc_end_2 = center_2 + (screw_dir * start_offset)
        
        cnc_line_1 = Line(cnc_start_1, cnc_end_1)
        cnc_line_2 = Line(cnc_start_2, cnc_end_2)
        
        return self._generate_features([cnc_line_1, cnc_line_2], [hw_line_1, hw_line_2], beam_a, beam_b, joint_label, req_screw_length)

    def _generate_features(self, cnc_lines, hw_lines, beam_1, beam_2, joint_label, req_screw_length): 
        success = False
        
        if joint_label not in self.hardware_screws_by_type:
            self.hardware_screws_by_type[joint_label] = 0
            self.screw_lengths_by_type[joint_label] = []
            
        for i in range(len(cnc_lines)):
            cnc_line = cnc_lines[i]
            hw_line = hw_lines[i]
            line_added_to_any = False
            
            for beam in [beam_1, beam_2]:
                try:
                    drill = Drilling.from_line_and_element(cnc_line, beam, diameter=self.screw_diameter)
                    
                    if self.max_drilling_depth is not None:
                        try:
                            ref_side = beam.side_as_surface(drill.ref_side_index)
                            drill.depth = drill._calculate_depth(cnc_line, ref_side)
                        except Exception:
                            drill.depth = cnc_line.length
                            
                        drill.depth_limited = True
                        if drill.depth > self.max_drilling_depth:
                            drill.depth = self.max_drilling_depth
                            
                    if hasattr(beam, 'add_feature'):
                        beam.add_feature(drill)
                    else:
                        beam.features.append(drill)
                        
                    line_added_to_any = True
                except Exception:
                    pass
            
            if line_added_to_any:
                self.drilling_count += 1
                self.screw_lines.append(hw_line)
                self.hardware_screws_by_type[joint_label] += 1
                self.screw_lengths_by_type[joint_label].append(req_screw_length)
                
                # Track longest and shortest screws per joint type
                if joint_label not in self.extrema_screws_by_type:
                    self.extrema_screws_by_type[joint_label] = {
                        "longest": {"line": hw_line, "length": req_screw_length},
                        "shortest": {"line": hw_line, "length": req_screw_length}
                    }
                else:
                    if req_screw_length > self.extrema_screws_by_type[joint_label]["longest"]["length"]:
                        self.extrema_screws_by_type[joint_label]["longest"] = {"line": hw_line, "length": req_screw_length}
                    if req_screw_length < self.extrema_screws_by_type[joint_label]["shortest"]["length"]:
                        self.extrema_screws_by_type[joint_label]["shortest"] = {"line": hw_line, "length": req_screw_length}
                
                success = True
            else:
                self.failed_screw_info.append({
                    "line": hw_line,
                    "type": joint_label
                })
                
        return success