import math
from compas.geometry import Point, Vector, Line, intersection_line_line, distance_point_point, intersection_line_plane
from compas_timber.fabrication import Drilling
from compas_timber.connections import (
    LMiterJoint,
    TButtJoint,
    TLapJoint,
    XLapJoint,
)

# ---------------------------------------------------------------------------
# Geometry helpers for the true contact surface
# ---------------------------------------------------------------------------
def _poly_centroid_2d(pts):
    n = len(pts)
    if n == 0: return None
    if n < 3: return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
    A = cx = cy = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cr = x0 * y1 - x1 * y0
        A += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    if abs(A) < 1e-12:
        return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
    A *= 0.5
    return (cx / (6 * A), cy / (6 * A))

def _clip_convex(subject, clip):
    def inside(p, a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= -1e-12

    def inter(s, e, a, b):
        dc = (a[0] - b[0], a[1] - b[1])
        dp = (s[0] - e[0], s[1] - e[1])
        n1 = a[0] * b[1] - a[1] * b[0]
        n2 = s[0] * e[1] - s[1] * e[0]
        den = dc[0] * dp[1] - dc[1] * dp[0]
        if abs(den) < 1e-15: return e
        return ((n1 * dp[0] - n2 * dc[0]) / den, (n1 * dp[1] - n2 * dc[0]) / den)

    out = subject[:]
    m = len(clip)
    for i in range(m):
        a = clip[i]
        b = clip[(i + 1) % m]
        inp = out
        out = []
        if not inp: break
        s = inp[-1]
        for e in inp:
            if inside(e, a, b):
                if not inside(s, a, b): out.append(inter(s, e, a, b))
                out.append(e)
            elif inside(s, a, b):
                out.append(inter(s, e, a, b))
            s = e
    return out

def _signed_area_2d(p):
    a = 0.0
    n = len(p)
    for i in range(n):
        a += p[i][0] * p[(i + 1) % n][1] - p[(i + 1) % n][0] * p[i][1]
    return a / 2.0

def _ray_obb_exit(origin, direction, beam):
    cl = beam.centerline
    cen = cl.midpoint
    ax = [beam.frame.xaxis.unitized(), beam.frame.yaxis.unitized(), beam.frame.zaxis.unitized()]
    half = [cl.length / 2.0, beam.width / 2.0, beam.height / 2.0]
    o = Vector.from_start_end(cen, origin)
    tmin = -1e18
    tmax = 1e18
    for i in range(3):
        e = o.dot(ax[i])
        f = direction.dot(ax[i])
        if abs(f) > 1e-9:
            t1 = (-half[i] - e) / f
            t2 = (half[i] - e) / f
            if t1 > t2: t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
        elif (-half[i] - e) > 0 or (half[i] - e) < 0:
            return None
    if tmax < tmin: return None
    return tmax 

def _ray_obb_intersect(origin, direction, beam):
    cl = beam.centerline
    cen = cl.midpoint
    if not hasattr(beam, 'frame'): return None
    
    ax = [beam.frame.xaxis.unitized(), beam.frame.yaxis.unitized(), beam.frame.zaxis.unitized()]
    half = [cl.length / 2.0, beam.width / 2.0, beam.height / 2.0]
    
    o = Vector.from_start_end(cen, origin)
    tmin = -1e18
    tmax = 1e18
    
    for i in range(3):
        e = o.dot(ax[i])
        f = direction.dot(ax[i])
        if abs(f) > 1e-9:
            t1 = (-half[i] - e) / f
            t2 = (half[i] - e) / f
            if t1 > t2: t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
        elif (-half[i] - e) > 0 or (half[i] - e) < 0:
            return None
            
    if tmax < tmin or tmax < 0: 
        return None
        
    return tmin if tmin > 0 else 0.0

class DrillingProcessor:
    def __init__(self, timber_model, screw_diameter=0.006, screw_length=0.150, screw_spacing=0.030, max_drilling_depth=None, max_arch_penetration=None, drill_type="both"):
        self.timber_model = timber_model
        self.screw_diameter = screw_diameter
        self.screw_length = screw_length
        self.screw_spacing = screw_spacing 
        self.max_drilling_depth = max_drilling_depth
        self.max_arch_penetration = max_arch_penetration 
        self.drill_type = drill_type
        
        self.drilling_count = 0
        self.screw_lines = []
        self.screw_assigned_lengths = []
        self.failed_screw_info = []
        self.summary_text = ""
        self.joinery_errors = [] 
        
        self.processed_beam_pairs = set()
        self.debug_points = []
        self.contact_polylines = [] 
        
        self.hardware_screws_by_type = {}
        self.screw_lengths_by_type = {}
        self.extrema_screws_by_type = {}
        
        self.inventory_counts = {100: 0, 130: 0, 150: 0}
        self.miter_inventory_counts = {"Miter Standard": 0} 

    def process_drillings(self):
        print("--- Starting Drilling Generation ---")
        
        self.drilling_count = 0
        self.screw_lines = []
        self.screw_assigned_lengths = []
        self.failed_screw_info = []
        self.summary_text = "" 
        self.joinery_errors = [] 
        self.processed_beam_pairs = set()
        self.debug_points = [] 
        self.contact_polylines = [] 
        
        self.hardware_screws_by_type = {}
        self.screw_lengths_by_type = {}
        self.extrema_screws_by_type = {}
        
        self.inventory_counts = {100: 0, 130: 0, 150: 0}
        self.miter_inventory_counts = {"Miter Standard": 0}
        self.manual_foundation_inventory_counts = {"Foundation Screw Spec": 0} 
        
        miter_joints_detected = {"Lmitter arch": 0, "Lmitter foundation": 0}
        llap_joints_count = 0

        for beam in self.timber_model.beams:
            if hasattr(beam, 'features'):
                old_drillings = [f for f in beam.features if isinstance(f, Drilling)]
                for d in old_drillings:
                    try: beam.remove_feature(d)
                    except AttributeError: beam.features.remove(d)
        
        joints = getattr(self.timber_model, 'joints', None) or getattr(self.timber_model, 'interactions', [])
        
        for joint in joints:
            joint_classname = type(joint).__name__
            
            if joint_classname == "CutoffLLapJoint":
                llap_joints_count += 1
                self.inventory_counts[130] += 2
                continue

            elements = getattr(joint, 'elements', None)
            if not elements and hasattr(joint, 'main_beam'):
                elements = [joint.main_beam, getattr(joint, 'cross_beam')]
                
            if not elements or len(elements) < 2 or not elements[0] or not elements[1]:
                continue
                
            def get_uid(beam):
                if "edge" in beam.attributes: return str(beam.attributes["edge"])
                mid = beam.centerline.midpoint
                return f"{round(mid.x, 3)}_{round(mid.y, 3)}_{round(mid.z, 3)}"
                    
            uid_a = get_uid(elements[0])
            uid_b = get_uid(elements[1])
            pair_id = frozenset([uid_a, uid_b])
            
            if pair_id in self.processed_beam_pairs: continue 
            self.processed_beam_pairs.add(pair_id)
            
            if isinstance(joint, TButtJoint):
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
                    if d1 < d2: abut_beam, cont_beam = elements[0], elements[1]
                    else: abut_beam, cont_beam = elements[1], elements[0]

                cat_c = cont_beam.attributes.get("category", "inner")
                cat_a = abut_beam.attributes.get("category", "inner")
                
                if cat_c == "base" or cat_a == "base":
                    if cat_a == "base": cont_beam, abut_beam = abut_beam, cont_beam
                    self._apply_foundation_butt_drilling(joint, abut_beam, cont_beam)
                elif cat_c == "inner" and cat_a == "inner":
                    self._apply_inner_inner_butt_drilling(joint)
                else:
                    self._apply_standard_butt_drilling(joint)

            elif isinstance(joint, (XLapJoint, TLapJoint)):
                self._apply_lap_drilling(joint, elements[0], elements[1])
                
            elif isinstance(joint, LMiterJoint):
                cat1 = elements[0].attributes.get("category", "inner")
                cat2 = elements[1].attributes.get("category", "inner")
                label = "Lmitter foundation" if (cat1 == "base" or cat2 == "base") else "Lmitter arch"
                miter_joints_detected[label] += 1
                
                screws_to_add = 16 if "foundation" in label.lower() else 8
                self.miter_inventory_counts["Miter Standard"] += screws_to_add
            
        manual_foundation_screws = 20 * 4
        self.manual_foundation_inventory_counts["Foundation Screw Spec"] += manual_foundation_screws

        log = []
        log.append("================================================================")
        log.append("            PROCUREMENT & DRILLING SUMMARY                     ")
        log.append("================================================================")
        log.append(f"Unique Joints Processed Geometry: {len(self.processed_beam_pairs)}")
        log.append(f"Lap Joint : {llap_joints_count} ( 2x 130mm screws/joint)")
        log.append(f"Screw Foundation  : 20 ( 4x Separate Foundation screws/joint)")
        log.append("----------------------------------------------------------------")
        
        # --- NEW AGGREGATION BLOCK FOR T-BUTTS ---
        summary_counts = {}
        summary_lengths = {}
        
        for j_type, count in self.hardware_screws_by_type.items():
            if count == 0: continue
            
            # Group TButtJoints into distinct buckets
            if "TButtJoint" in j_type:
                if "foundation" in j_type.lower():
                    group_key = "TButtJoint - Foundation"
                elif "arch" in j_type.lower():
                    group_key = "TButtJoint - Arch"
                elif "inner-inner" in j_type.lower():
                    group_key = "TButtJoint - Inner-Inner"
                else:
                    group_key = "TButtJoint - Inner"
            else:
                group_key = j_type
                
            summary_counts[group_key] = summary_counts.get(group_key, 0) + count
            if group_key not in summary_lengths:
                summary_lengths[group_key] = []
            summary_lengths[group_key].extend(self.screw_lengths_by_type[j_type])

        # Generate summary printout from aggregated data
        for j_type in sorted(summary_counts.keys()):
            num_screws = summary_counts[j_type]
            lengths = summary_lengths[j_type]
            if num_screws > 0:
                min_len = min(lengths) if lengths else 0
                max_len = max(lengths) if lengths else 0
                log.append(f"[{j_type}]")
                log.append(f"  -> Screws Generated : {num_screws}")
                log.append(f"  -> Shortest Screw   : {min_len * 1000:.1f} mm")
                log.append(f"  -> Longest Screw    : {max_len * 1000:.1f} mm\n")
        # ----------------------------------------
                
        for m_type, count in sorted(miter_joints_detected.items()):
            if count > 0:
                screws = (count * 16) if "foundation" in m_type.lower() else (count * 8)
                log.append(f"[{m_type}]")
                log.append(f"  -> Unmodeled Screws : {screws} ({count} joints estimated)\n")

        log.append("----------------------------------------------------------------")
        log.append("                    INVENTORY TO PROCURE                        ")
        log.append("----------------------------------------------------------------")
        
        color_map = {100: "GREEN", 130: "BLUE", 150: "ORANGE"}
        
        for length in [100, 130, 150]:
            count = self.inventory_counts[length]
            boxes = math.ceil(count / 100.0)
            color_label = color_map[length]
            log.append(f" Screw {length} mm [{color_label:^6}] : {count:4} pcs  ->  {boxes} boxes (100/box)")
            
        found_total = self.manual_foundation_inventory_counts["Foundation Screw Spec"]
        found_boxes = math.ceil(found_total / 100.0)
        log.append(f" Foundation Screw : {found_total:4} pcs  ->  {found_boxes} boxes")

        miter_total = self.miter_inventory_counts["Miter Standard"]
        miter_boxes = math.ceil(miter_total / 100.0)
        log.append(f" Miter Arch : {miter_total:4} pcs  ->  {miter_boxes} boxes")
        log.append("================================================================")

        self.summary_text = "\n".join(log)
        return self.timber_model

    def _surface_entry(self, pos, screw_dir, beam):
        if not hasattr(beam, 'frame'): return None
        c = beam.centerline.midpoint
        vx, vy, vz = beam.frame.xaxis, beam.frame.yaxis, beam.frame.zaxis
        w, h = beam.width, beam.height
        planes = [(c + vy * (w/2.0), vy), (c - vy * (w/2.0), -vy), (c + vz * (h/2.0), vz), (c - vz * (h/2.0), -vz)]
        p1, p2 = pos, pos - screw_dir * 5.0 
        ray_line = Line(p1, p2)
        candidates = []
        for pt, normal in planes:
            res = intersection_line_plane(ray_line, (pt, normal))
            if res:
                res_pt = Point(*res)
                vec = Vector.from_start_end(pos, res_pt)
                if vec.dot(screw_dir) < 1e-5:
                    vec_c = Vector.from_start_end(c, res_pt)
                    if abs(vec_c.dot(vy)) <= (w/2.0) + 0.005 and abs(vec_c.dot(vz)) <= (h/2.0) + 0.005:
                        candidates.append(res_pt)
        if not candidates: return None
        candidates.sort(key=lambda pt: distance_point_point(pos, pt))
        return candidates[0]

    def _apply_foundation_butt_drilling(self, joint, abut_beam, cont_beam):
        joint_label = "TButtJoint - foundation"
        w, h = abut_beam.width, abut_beam.height

        c_mid = cont_beam.centerline.midpoint
        abut_mid = abut_beam.centerline.midpoint
        
        vy, vz = cont_beam.frame.yaxis.copy(), cont_beam.frame.zaxis.copy()
        vec_to_abut = Vector.from_start_end(c_mid, abut_mid)
        
        face_n = vz if abs(vec_to_abut.dot(vz)) > abs(vec_to_abut.dot(vy)) else vy
        if vec_to_abut.dot(face_n) < 0: face_n.scale(-1)
        face_n.unitize()

        thick_c = cont_beam.height if face_n.dot(vz) > 0.9 else cont_beam.width
        face_pt = c_mid + face_n * (thick_c / 2.0)

        ax_u = cont_beam.centerline.direction.copy()
        ax_v = face_n.cross(ax_u)
        ax_u.unitize(); ax_v.unitize()

        big = 1e3
        rect3d = [
            face_pt + ax_u * big + ax_v * big, face_pt - ax_u * big + ax_v * big,
            face_pt - ax_u * big - ax_v * big, face_pt + ax_u * big - ax_v * big,
        ]
        contact_plane = (face_pt, face_n)
        screw_dir = face_n * -1
        screw_dir.unitize()

        def to2d(P): return (Vector.from_start_end(face_pt, P).dot(ax_u), Vector.from_start_end(face_pt, P).dot(ax_v))
        def to3d(uv): return face_pt + ax_u * uv[0] + ax_v * uv[1]

        cl = abut_beam.centerline
        d_start = abs(Vector.from_start_end(face_pt, cl.start).dot(face_n))
        d_end = abs(Vector.from_start_end(face_pt, cl.end).dot(face_n))
        end_center = cl.start if d_start < d_end else cl.end

        axis = Vector.from_start_end(cl.midpoint, end_center)
        if axis.length < 1e-9: axis = cl.direction.copy()
        axis.unitize()

        abut_vy, abut_vz = abut_beam.frame.yaxis, abut_beam.frame.zaxis
        corners = [
            end_center + abut_vy * (w/2.0) + abut_vz * (h/2.0), end_center - abut_vy * (w/2.0) + abut_vz * (h/2.0),
            end_center - abut_vy * (w/2.0) - abut_vz * (h/2.0), end_center + abut_vy * (w/2.0) - abut_vz * (h/2.0),
        ]
        
        footprint_pts = []
        for corner in corners:
            res_pt = intersection_line_plane(Line(corner, corner + axis * 10.0), contact_plane)
            if res_pt: footprint_pts.append(Point(*res_pt))

        if len(footprint_pts) != 4:
            center_of_area = face_pt
        else:
            rect2d, foot2d = [to2d(P) for P in rect3d], [to2d(P) for P in footprint_pts]
            if _signed_area_2d(rect2d) < 0: rect2d = rect2d[::-1]
            if _signed_area_2d(foot2d) < 0: foot2d = foot2d[::-1]

            overlap2d = _clip_convex(foot2d, rect2d)
            center_uv = _poly_centroid_2d(overlap2d) if overlap2d else _poly_centroid_2d(foot2d)
            center_of_area = Point(*to3d(center_uv))

        along = axis - face_n * axis.dot(face_n)
        if along.length < 1e-6: along = abut_beam.frame.xaxis.copy()
        along.unitize()
        across = face_n.cross(along)
        if across.length < 1e-6: across = abut_beam.frame.yaxis.copy()
        across.unitize()
        offset_vec = across * (self.screw_spacing / 2.0)

        best_face, max_dot = None, -2.0
        for face in abut_beam.ref_sides[:4]:
            nrm = face.normal.copy()
            nrm.unitize()
            d = nrm.dot(face_n)
            if d > max_dot: max_dot, best_face = d, face
        arch_top_plane = (best_face.point, best_face.normal)

        penetration_cap = self.max_arch_penetration if self.max_arch_penetration else h
        calculated = []
        for sign in (offset_vec, -offset_vec):
            contact_pt = center_of_area + sign
            target_tail = contact_pt + screw_dir * 0.080 
            exit_dist = _ray_obb_exit(contact_pt, face_n, abut_beam)
            if exit_dist is None or exit_dist <= 1e-6:
                res_top = intersection_line_plane(Line(contact_pt, contact_pt + face_n * 5.0), arch_top_plane)
                exit_dist = distance_point_point(contact_pt, Point(*res_top)) if res_top else max(w, h)

            head_dist = min(exit_dist, penetration_cap)
            head = contact_pt + face_n * head_dist
            raw_len = distance_point_point(head, target_tail)
            req_len = math.ceil(raw_len / 0.010) * 0.010
            calculated.append({"head": head, "req_len": req_len})

        final_screw_length = max(item["req_len"] for item in calculated)
        
        # PHYSICAL CAP
        if final_screw_length > 0.150: final_screw_length = 0.150
            
        hw_lines = [Line(item["head"], item["head"] + screw_dir * final_screw_length) for item in calculated]
        return self._generate_features(hw_lines, [abut_beam], joint_label, final_screw_length)

    def _resolve_shallow_drilling(self, abut_beam, cont_beam, intersection_pt):
        dir_abut = abut_beam.centerline.direction.copy()
        vec_to_mid = Vector.from_start_end(intersection_pt, abut_beam.centerline.midpoint)
        if dir_abut.dot(vec_to_mid) < 0: dir_abut.scale(-1)
        dir_abut.unitize()
        
        dir_cont = cont_beam.centerline.direction.copy()
        dir_cont.unitize()
        if dir_cont.dot(dir_abut) < 0: dir_cont.scale(-1)
            
        plane_normal = dir_cont.cross(dir_abut)
        if plane_normal.length < 1e-5: plane_normal = Vector(0, 0, 1)
        plane_normal.unitize()
        
        target_angle_rad = math.radians(40.0)
        v_perp = plane_normal.cross(dir_cont)
        v_perp.unitize()
        if v_perp.dot(dir_abut) < 0: v_perp.scale(-1)
            
        ideal_screw_dir = dir_cont * math.cos(target_angle_rad) + v_perp * math.sin(target_angle_rad)
        ideal_screw_dir.unitize()
        screw_dir = ideal_screw_dir * -1

        walk_step, max_steps = 0.005, 120
        anchor_depth, fixed_screw_length = 0.060, 0.150
        abut_length = fixed_screw_length - anchor_depth 
        min_exit_dist = abut_length + 0.020 
        
        cat_a = abut_beam.attributes.get("category", "inner")
        cat_c = cont_beam.attributes.get("category", "inner")
        joint_label = "TButtJoint - arch (40° Fixed)" if cat_a == "arch" or cat_c == "arch" else "TButtJoint - inner (40° Fixed)"
        
        best_step, min_dist_to_centerline, best_hw_lines = None, float('inf'), []
        abut_A, abut_B = abut_beam.centerline.start, abut_beam.centerline.end
        abut_axis = Vector.from_start_end(abut_A, abut_B)
        abut_axis_len = abut_axis.length

        for step in range(max_steps):
            pierce_pt = intersection_pt + (dir_cont * (step * walk_step))
            exit_dist = _ray_obb_exit(pierce_pt, ideal_screw_dir, abut_beam)
            
            if exit_dist is not None and exit_dist >= min_exit_dist:
                head_pt = pierce_pt + (ideal_screw_dir * abut_length)
                tail_pt = pierce_pt + (screw_dir * anchor_depth)
                screw_mid = pierce_pt + (ideal_screw_dir * (abut_length / 2.0))
                dist_to_cl = Vector.from_start_end(abut_A, screw_mid).cross(abut_axis).length / abut_axis_len if abut_axis_len > 1e-5 else float('inf')
                
                if dist_to_cl < min_dist_to_centerline:
                    min_dist_to_centerline = dist_to_cl
                    best_step = step
                    
                    offset_dir = screw_dir.cross(dir_cont)
                    if offset_dir.length < 1e-5: offset_dir = Vector(0, 0, 1)
                    offset_dir.unitize()
                    offset_vec = offset_dir * (self.screw_spacing / 2.0)
                    
                    best_hw_lines = [Line(head_pt + offset_vec, tail_pt + offset_vec), Line(head_pt - offset_vec, tail_pt - offset_vec)]

        if best_step is not None:
            self._generate_features(best_hw_lines, [cont_beam], joint_label, fixed_screw_length)
            return True
        return False

    def _apply_standard_butt_drilling(self, joint):
        elements = [joint.main_beam, joint.cross_beam]
        line1, line2 = elements[0].centerline, elements[1].centerline
        res = intersection_line_line(line1, line2)
        if not res or res[0] is None: return

        pt_a, pt_b = Point(*res[0]), Point(*res[1])
        d1 = min(distance_point_point(pt_a, line1.start), distance_point_point(pt_a, line1.end))
        d2 = min(distance_point_point(pt_b, line2.start), distance_point_point(pt_b, line2.end))
        
        abut_beam, cont_beam, intersection_pt = (elements[0], elements[1], pt_a) if d1 < d2 else (elements[1], elements[0], pt_b)

        dir_abut = abut_beam.centerline.direction.copy()
        dir_cont = cont_beam.centerline.direction.copy()
        
        angle_rad = dir_abut.angle(dir_cont)
        angle_deg = math.degrees(angle_rad)
        acute_angle_deg = min(angle_deg, 180.0 - angle_deg)

        if acute_angle_deg < 40.0:
            if not self._resolve_shallow_drilling(abut_beam, cont_beam, intersection_pt):
                self.failed_screw_info.append({"line": Line(intersection_pt, intersection_pt + Vector(0, 0, 0.2)), "type": f"FAILED 40° SOLVE: {acute_angle_deg:.1f}°"})
            return

        centerline = abut_beam.centerline
        dir_into_abut = centerline.direction.copy()
        vec_to_mid = Vector.from_start_end(intersection_pt, centerline.midpoint)
        if dir_into_abut.dot(vec_to_mid) < 0: dir_into_abut.scale(-1)
        dir_into_abut.unitize()

        thickness_c = max(cont_beam.width, cont_beam.height)
        start_pt = intersection_pt - (dir_into_abut * (thickness_c / 2.0))
        
        anchor_depth = 0.060
        req_screw_length = math.ceil((thickness_c + anchor_depth) / 0.010) * 0.010
        
        # PHYSICAL CAP
        if req_screw_length > 0.150: req_screw_length = 0.150
            
        end_pt = start_pt + (dir_into_abut * req_screw_length)

        dir_cont.unitize()
        offset_dir = dir_into_abut.cross(dir_cont)
        if offset_dir.length < 1e-5: offset_dir = Vector(0, 0, 1) 
        offset_dir.unitize()
        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        
        hw_line_1 = Line(start_pt + offset_vec, end_pt + offset_vec)
        hw_line_2 = Line(start_pt - offset_vec, end_pt - offset_vec)
        
        cat_a = abut_beam.attributes.get("category", "inner")
        cat_c = cont_beam.attributes.get("category", "inner")
        joint_label = "TButtJoint - arch" if cat_a == "arch" or cat_c == "arch" else "TButtJoint - inner"
        
        self._generate_features([hw_line_1, hw_line_2], [cont_beam], joint_label, req_screw_length)

    def _apply_inner_inner_butt_drilling(self, joint):
        elements = [joint.main_beam, joint.cross_beam]
        line1, line2 = elements[0].centerline, elements[1].centerline
        
        res = intersection_line_line(line1, line2)
        if not res or res[0] is None: return

        pt_a = Point(*res[0])
        pt_b = Point(*res[1])
        
        d1 = min(distance_point_point(pt_a, line1.start), distance_point_point(pt_a, line1.end))
        d2 = min(distance_point_point(pt_b, line2.start), distance_point_point(pt_b, line2.end))
        
        if d1 < d2:
            abut_beam, cont_beam = elements[0], elements[1]
            intersection_pt = pt_a
        else:
            abut_beam, cont_beam = elements[1], elements[0]
            intersection_pt = pt_b

        dir_abut = abut_beam.centerline.direction.copy()
        vec_to_mid = Vector.from_start_end(intersection_pt, abut_beam.centerline.midpoint)
        if dir_abut.dot(vec_to_mid) < 0: 
            dir_abut.scale(-1)
        dir_abut.unitize()

        dir_cont = cont_beam.centerline.direction.copy()
        dir_cont.unitize()

        plane_normal = dir_cont.cross(dir_abut)
        if plane_normal.length < 1e-5: 
            plane_normal = Vector(0, 0, 1)
        plane_normal.unitize()

        perp_vec = plane_normal.cross(dir_cont)
        perp_vec.unitize()
        if perp_vec.dot(dir_abut) < 0:
            perp_vec.scale(-1)

        # Base Interface Calculations
        thickness_c = max(cont_beam.width, cont_beam.height)
        dot_val = dir_abut.dot(perp_vec)
        if abs(dot_val) > 1e-5:
            t_interface = (thickness_c / 2.0) / dot_val
            pt_interface = intersection_pt + (dir_abut * t_interface)
        else:
            pt_interface = intersection_pt + (perp_vec * (thickness_c / 2.0))
            
        min_clearance = 0.080 
        
        # -------------------------------------------------------------------
        # TOPOLOGICAL TRIANGLE EXTRACTION
        # -------------------------------------------------------------------
        triangle_beams = set()
        all_joints = getattr(self.timber_model, 'joints', None) or getattr(self.timber_model, 'interactions', [])
        for j in all_joints:
            elems = getattr(j, 'elements', None)
            if not elems and hasattr(j, 'main_beam'):
                elems = [j.main_beam, getattr(j, 'cross_beam')]
            if elems and (cont_beam in elems or abut_beam in elems):
                for e in elems:
                    if e is not None and e is not cont_beam and e is not abut_beam:
                        triangle_beams.add(e)

        # -------------------------------------------------------------------
        # EARLY EXIT GRID SEARCH
        # -------------------------------------------------------------------
        test_lengths = [0.150, 0.130]
        
        slide_steps = [0.0, 0.015, -0.015, 0.030, -0.030, 0.045, -0.045]
        cross_steps = [0.0, 0.010, -0.010, 0.020, -0.020]
        angle_steps = [0.0, 5.0, -5.0, 10.0, -10.0, 15.0, -15.0, 20.0, -20.0]
        
        best_config = None
        final_screw_length = None
        
        for current_length in test_lengths:
            for slide in slide_steps:
                for cross in cross_steps:
                    curr_interface = pt_interface + (dir_cont * slide) + (plane_normal * cross)
                    
                    for angle in angle_steps:
                        rad = math.radians(angle)
                        
                        curr_screw_dir = perp_vec * math.cos(rad) + dir_cont * math.sin(rad)
                        curr_screw_dir.unitize()
                        curr_tool_dir = curr_screw_dir * -1
                        
                        travel_dist = thickness_c / math.cos(rad) if math.cos(rad) > 0.1 else thickness_c
                        curr_start = curr_interface - (curr_screw_dir * travel_dist)
                        
                        offset_dir = plane_normal.copy()
                        offset_vec = offset_dir * (self.screw_spacing / 2.0)
                        
                        start_1 = curr_start + offset_vec
                        start_2 = curr_start - offset_vec
                        
                        # Rule A: Containment
                        exit_1 = _ray_obb_exit(start_1, curr_screw_dir, abut_beam)
                        exit_2 = _ray_obb_exit(start_2, curr_screw_dir, abut_beam)
                        
                        if exit_1 is None or exit_1 < (current_length + 0.002): continue
                        if exit_2 is None or exit_2 < (current_length + 0.002): continue
                        
                        # Rule B: Triangle Clearance
                        clearance_fail = False
                        for beam in triangle_beams:
                            d1 = _ray_obb_intersect(start_1, curr_tool_dir, beam)
                            if d1 is not None and d1 < min_clearance: clearance_fail = True; break
                            d2 = _ray_obb_intersect(start_2, curr_tool_dir, beam)
                            if d2 is not None and d2 < min_clearance: clearance_fail = True; break
                        
                        if clearance_fail: continue
                        
                        best_config = (start_1, start_2, curr_screw_dir)
                        final_screw_length = current_length
                        break
                        
                    if best_config: break
                if best_config: break
            if best_config: break
                    
        # Apply the fit
        if best_config:
            start_1, start_2, curr_screw_dir = best_config
            hw_line_1 = Line(start_1, start_1 + curr_screw_dir * final_screw_length)
            hw_line_2 = Line(start_2, start_2 + curr_screw_dir * final_screw_length)
            joint_label = "TButtJoint - inner-inner (Offset)"
            
        else:
            # FALLBACK: No space for offset 130mm/150mm screws.
            # Route TWO screws parallel to the centerline of the abutting beam.
            center_start_pt = intersection_pt - (dir_abut * (thickness_c / 2.0))
            
            offset_dir = plane_normal.copy()
            offset_vec = offset_dir * (self.screw_spacing / 2.0)
            
            start_1 = center_start_pt + offset_vec
            start_2 = center_start_pt - offset_vec
            
            final_screw_length = 0.130  
            
            hw_line_1 = Line(start_1, start_1 + (dir_abut * final_screw_length))
            hw_line_2 = Line(start_2, start_2 + (dir_abut * final_screw_length))
            joint_label = "TButtJoint - inner-inner (Parallel Fallback)"
            
        self._generate_features(
            [hw_line_1, hw_line_2],
            [cont_beam],
            joint_label,
            final_screw_length
        )

    def _apply_lap_drilling(self, joint, beam_a, beam_b):
        joint_label = type(joint).__name__
        line_a, line_b = beam_a.centerline, beam_b.centerline
        res = intersection_line_line(line_a, line_b)
        if not res or res[0] is None: return False
            
        pt_a, pt_b = Point(res[0][0], res[0][1], res[0][2]), Point(res[1][0], res[1][1], res[1][2])
        mid_pt = Point((pt_a.x + pt_b.x) / 2.0, (pt_a.y + pt_b.y) / 2.0, (pt_a.z + pt_b.z) / 2.0)
        
        dir_a, dir_b = line_a.direction, line_b.direction
        screw_dir = dir_a.cross(dir_b)
        
        if screw_dir.length < 1e-5: screw_dir = beam_a.frame.zaxis if hasattr(beam_a, 'frame') else Vector(0, 0, 1)
        else: screw_dir.unitize()
            
        offset_dir = dir_a + dir_b
        if offset_dir.length < 1e-5: offset_dir = dir_a 
        offset_dir.unitize()
        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        center_1, center_2 = mid_pt + offset_vec, mid_pt - offset_vec
        
        thickness_a = math.sqrt(beam_a.width**2 + beam_a.height**2)
        thickness_b = math.sqrt(beam_b.width**2 + beam_b.height**2)
        true_total_thickness = distance_point_point(pt_a, pt_b) + (thickness_a / 2.0) + (thickness_b / 2.0)
        
        req_screw_length = math.floor((true_total_thickness - 0.010) / 0.010) * 0.010 
        if req_screw_length < 0.040: req_screw_length = 0.040 
        
        # PHYSICAL CAP
        if req_screw_length > 0.150: req_screw_length = 0.150
            
        hw_line_1 = Line(center_1 - (screw_dir * (req_screw_length / 2.0)), center_1 + (screw_dir * (req_screw_length / 2.0)))
        hw_line_2 = Line(center_2 - (screw_dir * (req_screw_length / 2.0)), center_2 + (screw_dir * (req_screw_length / 2.0)))
        
        beam_top, beam_bottom = (beam_a, beam_b) if pt_a.z > pt_b.z else (beam_b, beam_a)

        if self.drill_type == "both": target_beams = [beam_a, beam_b]
        elif self.drill_type == "upper": target_beams = [beam_top]
        elif self.drill_type == "lower": target_beams = [beam_bottom]
        else: target_beams = [self._evaluate_majority_faces(beam_top, beam_bottom, screw_dir)]

        return self._generate_features([hw_line_1, hw_line_2], target_beams, joint_label, req_screw_length)
    
    def _evaluate_majority_faces(self, beam_top, beam_bottom, screw_dir):
        def get_pierced_face_normal(beam):
            if not hasattr(beam, 'frame'): return Vector(0,0,1)
            dots = {"xaxis": abs(screw_dir.dot(beam.frame.xaxis)), "yaxis": abs(screw_dir.dot(beam.frame.yaxis)), "zaxis": abs(screw_dir.dot(beam.frame.zaxis))}
            return max(dots, key=dots.get)

        top_hit = get_pierced_face_normal(beam_top)
        bottom_hit = get_pierced_face_normal(beam_bottom)

        if top_hit == "zaxis": return beam_top
        elif bottom_hit == "zaxis": return beam_bottom
        return beam_top

    def _generate_features(self, hw_lines, target_beams, joint_label, req_screw_length):
        success = False
        
        if joint_label not in self.hardware_screws_by_type:
            self.hardware_screws_by_type[joint_label] = 0
            self.screw_lengths_by_type[joint_label] = []

        req_mm = req_screw_length * 1000.0
        if req_mm <= 100: assigned_len = 100
        elif req_mm <= 130: assigned_len = 130
        else: assigned_len = 150

        def store_web_feature(beam, line):
            attributes = getattr(beam, "attributes", None)
            if attributes is None:
                attributes = {}
                setattr(beam, "attributes", attributes)
            web_features = attributes.setdefault("web_features", [])
            web_features.append({
                "type": "Screw", "joint_type": joint_label,
                "start": [float(line.start.x), float(line.start.y), float(line.start.z)],
                "end": [float(line.end.x), float(line.end.y), float(line.end.z)],
                "diameter_m": float(self.screw_diameter), "length_m": float(req_screw_length),
                "length_mm": round(float(req_screw_length) * 1000.0, 1),
                "assigned_length_mm": assigned_len,
            })
            
        for i in range(len(hw_lines)):
            hw_line = hw_lines[i]
            line_added_to_any = False
            
            for beam in target_beams:
                try:
                    drill = Drilling.from_line_and_element(hw_line, beam, diameter=self.screw_diameter)
                    if hasattr(beam, 'add_feature'): beam.add_feature(drill)
                    else: beam.features.append(drill)
                    store_web_feature(beam, hw_line)
                    line_added_to_any = True
                except Exception: pass
            
            if line_added_to_any:
                self.drilling_count += 1
                self.screw_lines.append(hw_line)
                self.hardware_screws_by_type[joint_label] += 1
                self.screw_lengths_by_type[joint_label].append(req_screw_length)
                
                self.screw_assigned_lengths.append(assigned_len)
                self.inventory_counts[assigned_len] += 1
                
                if joint_label not in self.extrema_screws_by_type:
                    self.extrema_screws_by_type[joint_label] = {"longest": {"line": hw_line, "length": req_screw_length}, "shortest": {"line": hw_line, "length": req_screw_length}}
                else:
                    if req_screw_length > self.extrema_screws_by_type[joint_label]["longest"]["length"]: self.extrema_screws_by_type[joint_label]["longest"] = {"line": hw_line, "length": req_screw_length}
                    if req_screw_length < self.extrema_screws_by_type[joint_label]["shortest"]["length"]: self.extrema_screws_by_type[joint_label]["shortest"] = {"line": hw_line, "length": req_screw_length}
                
                success = True
            else:
                self.failed_screw_info.append({"line": hw_line, "type": joint_label})
                
        return success