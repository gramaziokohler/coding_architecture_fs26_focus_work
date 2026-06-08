import math
from compas.geometry import (
    Point,
    Vector,
    Line,
    intersection_line_line,
    distance_point_point,
)
from compas_timber.fabrication import Drilling
from compas_timber.connections import (
    LMiterJoint,
    TButtJoint,
    TLapJoint,
    XLapJoint,
)
from a03_preferred_face_tbutt_joint import PreferredFaceTButtJoint


class DrillingProcessor:
    def __init__(
        self,
        timber_model,
        screw_diameter=0.006,
        screw_length=0.150,
        screw_spacing=0.040,
        max_drilling_depth=None,
    ):
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
        self.miter_counts = {}

        for beam in self.timber_model.beams:
            if hasattr(beam, "features"):
                old_drillings = [f for f in beam.features if isinstance(f, Drilling)]
                for d in old_drillings:
                    try:
                        beam.remove_feature(d)
                    except AttributeError:
                        beam.features.remove(d)

        joints = getattr(self.timber_model, "joints", None) or getattr(
            self.timber_model, "interactions", []
        )

        def get_uid(beam):
            if "edge" in beam.attributes:
                return str(beam.attributes["edge"])
            else:
                mid = beam.centerline.midpoint
                return f"{round(mid.x, 3)}_{round(mid.y, 3)}_{round(mid.z, 3)}"

        for joint in joints:
            elements = getattr(joint, "elements", None)
            if not elements and hasattr(joint, "main_beam"):
                elements = [joint.main_beam, getattr(joint, "cross_beam")]

            if not elements or len(elements) < 2 or not elements[0] or not elements[1]:
                continue

            uid_a = get_uid(elements[0])
            uid_b = get_uid(elements[1])
            pair_id = frozenset([uid_a, uid_b])

            if pair_id in self.processed_beam_pairs:
                continue

            self.processed_beam_pairs.add(pair_id)

            if isinstance(joint, TButtJoint):
                self._apply_butt_drilling(joint, elements[0], elements[1])
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
        log.append(
            f"BOXES TO BUY (100/box) : {boxes_needed} boxes ({boxes_needed * 100} screws)"
        )
        log.append("================================================================")

        self.summary_text = "\n".join(log)
        return self.timber_model

    def _apply_butt_drilling(self, joint, beam1, beam2):
        """Routes the TButtJoint to the appropriate drilling logic based on category."""
        cat1 = beam1.attributes.get("category", "inner")
        cat2 = beam2.attributes.get("category", "inner")

        if cat1 == "base" or cat2 == "base":
            return self._apply_foundation_butt_drilling(joint, beam1, beam2)
        else:
            return self._apply_standard_butt_drilling(joint, beam1, beam2, cat1, cat2)

    def _apply_foundation_butt_drilling(self, joint, beam1, beam2):
        """Handles drilling logic exclusively for foundation base connections."""
        cat1 = beam1.attributes.get("category", "inner")
        
        if cat1 == "base":
            cont_beam, abut_beam = beam1, beam2
        else:
            cont_beam, abut_beam = beam2, beam1

        line_a = abut_beam.centerline
        line_c = cont_beam.centerline

        res = intersection_line_line(line_a, line_c)
        if not res or res[0] is None:
            return False

        anchor_pt = Point(res[0][0], res[0][1], res[0][2])
        d_start = distance_point_point(anchor_pt, line_a.start)
        d_end = distance_point_point(anchor_pt, line_a.end)
        abut_end_pt = line_a.start if d_start < d_end else line_a.end

        dir_s = line_a.direction
        vec_to_mid = Vector.from_start_end(abut_end_pt, line_a.midpoint)
        if dir_s.dot(vec_to_mid) < 0:
            dir_s.scale(-1)
        dir_s.unitize()

        if isinstance(joint, PreferredFaceTButtJoint):
            joint_label = "TButtJoint - foundation screws"

            ref_side = cont_beam.ref_sides[joint.cross_beam_ref_side_index]
            plane_normal = ref_side.normal.copy()
            plane_normal.unitize()
            plane_pt = ref_side.point

            vec_to_anchor = Vector.from_start_end(plane_pt, anchor_pt)
            dist_to_plane = vec_to_anchor.dot(plane_normal)
            center_pt = Point(
                anchor_pt.x - plane_normal.x * dist_to_plane,
                anchor_pt.y - plane_normal.y * dist_to_plane,
                anchor_pt.z - plane_normal.z * dist_to_plane,
            )

            screw_dir = plane_normal
            anchor_depth = 0.080
            
            cos_angle = abs(dir_s.dot(screw_dir))
            sin_angle = math.sqrt(max(0.0, 1 - cos_angle**2))
            cross_sec = max(abut_beam.width, abut_beam.height)
            
            up_distance = cross_sec / max(0.1, sin_angle)
            
            req_screw_length = up_distance + anchor_depth
            req_screw_length = math.ceil(req_screw_length / 0.010) * 0.010
            
            up_distance = req_screw_length - anchor_depth

            foundation_axis = line_c.direction.copy()
            foundation_axis.unitize()
            offset_dir = foundation_axis.cross(screw_dir)
            if offset_dir.length < 1e-5:
                offset_dir = Vector(1, 0, 0)
            offset_dir.unitize()
            offset_vec = offset_dir * (self.screw_spacing / 2.0)

            tolerance = 0.050

            cnc_start = center_pt + (screw_dir * (up_distance + tolerance))
            cnc_end = center_pt - (screw_dir * (anchor_depth + tolerance))
            cnc_line_1 = Line(cnc_start + offset_vec, cnc_end + offset_vec)
            cnc_line_2 = Line(cnc_start - offset_vec, cnc_end - offset_vec)

            hw_start = center_pt + (screw_dir * up_distance)
            hw_end = center_pt - (screw_dir * anchor_depth)
            hw_line_1 = Line(hw_start + offset_vec, hw_end + offset_vec)
            hw_line_2 = Line(hw_start - offset_vec, hw_end - offset_vec)

        else:
            joint_label = "TButtJoint - foundation inner structure"
            tolerance = 0.050
            anchor_depth = 0.080
            c_thickness = max(cont_beam.width, cont_beam.height)
            req_screw_length = c_thickness + anchor_depth
            req_screw_length = math.ceil(req_screw_length / 0.010) * 0.010

            if res[1] is not None:
                anchor_on_cont = Point(res[1][0], res[1][1], res[1][2])
            else:
                anchor_on_cont = anchor_pt

            foundation_axis = line_c.direction
            foundation_axis.unitize()
            dot = dir_s.dot(foundation_axis)
            proj_dir = Vector(
                dir_s.x - foundation_axis.x * dot,
                dir_s.y - foundation_axis.y * dot,
                dir_s.z - foundation_axis.z * dot,
            )
            if proj_dir.length < 1e-5:
                if hasattr(joint, "cross_beam_ref_side_index") and hasattr(cont_beam, "ref_sides"):
                    try:
                        fn = cont_beam.ref_sides[joint.cross_beam_ref_side_index].normal
                        proj_dir = Vector(fn.x, fn.y, fn.z)
                    except (AttributeError, IndexError):
                        pass
                if proj_dir.length < 1e-5:
                    proj_dir = foundation_axis.cross(Vector(0, 0, 1))
                if proj_dir.length < 1e-5:
                    proj_dir = foundation_axis.cross(Vector(1, 0, 0))
            proj_dir.unitize()

            offset_dir = None
            if hasattr(joint, "cross_beam_ref_side_index") and hasattr(cont_beam, "ref_sides"):
                try:
                    ref_side = cont_beam.ref_sides[joint.cross_beam_ref_side_index]
                    ya = ref_side.yaxis
                    offset_dir = Vector(ya.x, ya.y, ya.z)
                except (AttributeError, IndexError):
                    pass
            if offset_dir is None or offset_dir.length < 1e-5:
                offset_dir = Vector(foundation_axis.x, foundation_axis.y, foundation_axis.z)
            if offset_dir.length < 1e-5:
                offset_dir = Vector(1, 0, 0)
            offset_dir.unitize()

            offset_vec = offset_dir * (self.screw_spacing / 2.0)

            cnc_start = anchor_on_cont - (proj_dir * (c_thickness + tolerance))
            cnc_end = anchor_on_cont + (proj_dir * (c_thickness + anchor_depth + tolerance))
            cnc_line_1 = Line(cnc_start + offset_vec, cnc_end + offset_vec)
            cnc_line_2 = Line(cnc_start - offset_vec, cnc_end - offset_vec)

            hw_start = anchor_on_cont - (proj_dir * (c_thickness / 2.0))
            hw_end = anchor_on_cont + (proj_dir * (c_thickness / 2.0 + anchor_depth))
            hw_line_1 = Line(hw_start + offset_vec, hw_end + offset_vec)
            hw_line_2 = Line(hw_start - offset_vec, hw_end - offset_vec)

        return self._generate_features(
            [cnc_line_1, cnc_line_2],
            [hw_line_1, hw_line_2],
            abut_beam,
            cont_beam,
            joint_label,
            req_screw_length,
        )

    def _apply_standard_butt_drilling(self, joint, beam1, beam2, cat1, cat2):
        """Handles drilling logic for arch and interior TButtJoint connections."""
        
        # 1. BULLETPROOF GEOMETRIC DETECTION
        # compas_timber arbitrarily assigns beam1 and beam2. We CANNOT trust it.
        # Geometrically find which beam actually ends at the joint (abutting) 
        # and which beam passes through (continuous).
        line1, line2 = beam1.centerline, beam2.centerline
        res = intersection_line_line(line1, line2)
        if not res or res[0] is None:
            return False

        pt1 = Point(res[0][0], res[0][1], res[0][2])
        pt2 = Point(res[1][0], res[1][1], res[1][2])
        
        # Calculate distance from intersection to endpoints of both beams
        d1_min = min(distance_point_point(pt1, line1.start), distance_point_point(pt1, line1.end))
        d2_min = min(distance_point_point(pt2, line2.start), distance_point_point(pt2, line2.end))
        
        # The beam ending closest to the intersection is the abutting beam
        if d1_min < d2_min:
            abut_beam, cont_beam = beam1, beam2
            pt_a, pt_c = pt1, pt2
            line_a, line_c = line1, line2
        else:
            abut_beam, cont_beam = beam2, beam1
            pt_a, pt_c = pt2, pt1
            line_a, line_c = line2, line1

        # 2. LABELING
        cat_abut = abut_beam.attributes.get("category", "")
        cat_cont = cont_beam.attributes.get("category", "")
        
        if "arch" in cat_abut or "arch" in cat_cont:
            joint_label = "TButtJoint - arch"
        else:
            joint_label = "TButtJoint - interior interior"

        # 3. EXACT TRAJECTORY MATH
        dist_centers = distance_point_point(pt_a, pt_c)

        d_start = distance_point_point(pt_a, line_a.start)
        d_end = distance_point_point(pt_a, line_a.end)
        abut_end_pt = line_a.start if d_start < d_end else line_a.end

        # dir_s points strictly INTO the abutting beam
        dir_s = line_a.direction.copy()
        vec_to_mid = Vector.from_start_end(pt_a, line_a.midpoint)
        if dir_s.dot(vec_to_mid) < 0:
            dir_s.scale(-1)
        dir_s.unitize()

        # Direction of continuous beam
        dir_c = line_c.direction.copy()
        dir_c.unitize()

        # Calculate angle between the beams to find diagonal traversal distance
        cos_alpha = abs(dir_s.dot(dir_c))
        sin_alpha = math.sqrt(max(0.0, 1.0 - cos_alpha**2))
        
        thickness_c = max(cont_beam.width, cont_beam.height)
        
        # Diagonal distance from center of continuous beam out to its face
        traversal_half = (thickness_c / 2.0 + dist_centers) / max(0.1, sin_alpha)
        
        # Enter exactly 8 cm deeply into the abutting beam AFTER exiting continuous beam
        anchor_depth = 0.080
        
        # Total screw length = Traversing ENTIRE continuous beam (2 * half) + anchor_depth
        req_screw_length = (2.0 * traversal_half) + anchor_depth
        
        # Ceil to the nearest 10mm to guarantee hardware procurement length
        req_screw_length = math.ceil(req_screw_length / 0.010) * 0.010
        
        # Since we rounded up, the extra length pushes deeper into the abutting beam
        actual_anchor_depth = req_screw_length - (2.0 * traversal_half)

        # Offset direction strictly side-by-side perpendicular to both centerlines
        offset_dir = dir_s.cross(dir_c)
        if offset_dir.length < 1e-5:
            if hasattr(abut_beam, "frame"):
                offset_dir = Vector(abut_beam.frame.yaxis.x, abut_beam.frame.yaxis.y, abut_beam.frame.yaxis.z)
            else:
                offset_dir = Vector(0, 0, 1)
                
        offset_dir.unitize()
        offset_vec = offset_dir * (self.screw_spacing / 2.0)

        tolerance = 0.050  

        # Drill starts flush with FAR face of continuous beam 
        cnc_start = pt_a - (dir_s * (traversal_half + tolerance))
        
        # Drill ends inside abutting beam
        cnc_end = pt_a + (dir_s * (traversal_half + actual_anchor_depth + tolerance))
        
        cnc_line_1 = Line(cnc_start + offset_vec, cnc_end + offset_vec)
        cnc_line_2 = Line(cnc_start - offset_vec, cnc_end - offset_vec)

        # Hardware lines start exactly flush and end exactly at screw length
        hw_start = pt_a - (dir_s * traversal_half)
        hw_end = pt_a + (dir_s * (traversal_half + actual_anchor_depth))
        
        hw_line_1 = Line(hw_start + offset_vec, hw_end + offset_vec)
        hw_line_2 = Line(hw_start - offset_vec, hw_end - offset_vec)

        return self._generate_features(
            [cnc_line_1, cnc_line_2],
            [hw_line_1, hw_line_2],
            abut_beam,
            cont_beam,
            joint_label,
            req_screw_length,
        )
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
    
    def _generate_features(
        self, cnc_lines, hw_lines, beam_1, beam_2, joint_label, req_screw_length
    ):
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
                    drill = Drilling.from_line_and_element(
                        cnc_line, beam, diameter=self.screw_diameter
                    )

                    if self.max_drilling_depth is not None:
                        try:
                            ref_side = beam.side_as_surface(drill.ref_side_index)
                            drill.depth = drill._calculate_depth(cnc_line, ref_side)
                        except Exception:
                            drill.depth = cnc_line.length

                        if drill.depth > self.max_drilling_depth:
                            drill.depth = self.max_drilling_depth
                            drill.depth_limited = True

                    if hasattr(beam, "add_feature"):
                        beam.add_feature(drill)
                    else:
                        beam.features.append(drill)

                    line_added_to_any = True
                except Exception as e:
                    print(
                        f"  [WARN] Drilling.from_line_and_element failed on {joint_label}: {e}"
                    )

            if line_added_to_any:
                self.drilling_count += 1
                self.screw_lines.append(hw_line)
                self.hardware_screws_by_type[joint_label] += 1
                self.screw_lengths_by_type[joint_label].append(req_screw_length)
                success = True
            else:
                self.failed_screw_info.append({"line": hw_line, "type": joint_label})

        return success