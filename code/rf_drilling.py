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
# Geometry helpers for the true contact surface (work in IronPython & CPython)
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
        self.miter_counts = {}
        
        # Procurement tracking
        self.inventory_counts = {100: 0, 130: 0, 150: 0, "Oversized": 0}

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
        self.miter_counts = {}
        self.inventory_counts = {100: 0, 130: 0, 150: 0, "Oversized": 0}

        for beam in self.timber_model.beams:
            if hasattr(beam, 'features'):
                old_drillings = [f for f in beam.features if isinstance(f, Drilling)]
                for d in old_drillings:
                    try: beam.remove_feature(d)
                    except AttributeError: beam.features.remove(d)
        
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
            
            if pair_id in self.processed_beam_pairs: continue 
                
            self.processed_beam_pairs.add(pair_id)
            
            # --- ROUTING SYSTEM --- 
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
                else:
                    self._apply_standard_butt_drilling(joint)

            elif isinstance(joint, (XLapJoint, TLapJoint)):
                self._apply_lap_drilling(joint, elements[0], elements[1])
                
            elif isinstance(joint, LMiterJoint):
                cat1 = elements[0].attributes.get("category", "inner")
                cat2 = elements[1].attributes.get("category", "inner")
                if cat1 == "base" or cat2 == "base": label = "Lmitter foundation"
                else: label = "Lmitter arch"
                self.miter_counts[label] = self.miter_counts.get(label, 0) + 1
            
        # --- COMPILE PROCUREMENT SUMMARY TEXT --- 
        log = []
        log.append("================================================================")
        log.append("             PROCUREMENT & DRILLING SUMMARY                     ")
        log.append("================================================================")
        log.append(f"Unique Joints Processed: {len(self.processed_beam_pairs)}")
        log.append("----------------------------------------------------------------")
        
        # Details by connection type
        for j_type in sorted(self.hardware_screws_by_type.keys()):
            num_screws = self.hardware_screws_by_type[j_type]
            lengths = self.screw_lengths_by_type[j_type]
            if num_screws > 0:
                min_len = min(lengths) if lengths else 0
                max_len = max(lengths) if lengths else 0
                log.append(f"[{j_type}]")
                log.append(f"  -> Screws Generated : {num_screws}")
                log.append(f"  -> Shortest Screw   : {min_len * 1000:.1f} mm")
                log.append(f"  -> Longest Screw    : {max_len * 1000:.1f} mm\n")
                
        # Un-geometrized miter joints
        miter_screws_total = 0
        for m_type in sorted(self.miter_counts.keys()):
            count = self.miter_counts[m_type]
            if count > 0:
                screws = (count * 16) if "foundation" in m_type.lower() else (count * 8)
                miter_screws_total += screws
                log.append(f"[{m_type}]")
                log.append(f"  -> Unmodeled Screws : {screws} ({count} joints estimated)\n")

        # INVENTORY & BOX CATEGORIZATION
        log.append("----------------------------------------------------------------")
        log.append("                    INVENTORY TO PROCURE                        ")
        log.append("----------------------------------------------------------------")
        
        color_map = {100: "GREEN", 130: "BLUE", 150: "ORANGE"}
        
        total_boxes = 0
        for length in [100, 130, 150]:
            count = self.inventory_counts[length]
            boxes = math.ceil(count / 100.0)
            total_boxes += boxes
            color_label = color_map[length]
            log.append(f" Screw {length} mm [{color_label:^6}] : {count:4} pcs  ->  {boxes} boxes (100/box)")
        oversized = self.inventory_counts["Oversized"]

        if oversized > 0:
            log.append(f" OVERSIZED   [ RED  ] : {oversized:4} pcs  ->  (Requires custom >150mm length)")
            
        if miter_screws_total > 0:
            log.append(f" MITER JOINTS         : {miter_screws_total:4} pcs  ->  (Length unspecified by geometry)")

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

    def _apply_foundation_butt_drilling(self, joint, abut_beam, cont_beam):
        joint_label = "TButtJoint - foundation"
        w, h = abut_beam.width, abut_beam.height

        # Hardened Face Detection: Vector directly from continuous centerline to abutting midpoint
        c_mid = cont_beam.centerline.midpoint
        abut_mid = abut_beam.centerline.midpoint
        
        # Determine the primary orientation axis of the continuous beam closest to the abutting beam
        vy, vz = cont_beam.frame.yaxis.copy(), cont_beam.frame.zaxis.copy()
        vec_to_abut = Vector.from_start_end(c_mid, abut_mid)
        
        # Use the beam face normal that aligns closest to the target beam
        face_n = vz if abs(vec_to_abut.dot(vz)) > abs(vec_to_abut.dot(vy)) else vy
        if vec_to_abut.dot(face_n) < 0:
            face_n.scale(-1)
        face_n.unitize()

        # Set contact point at the outer surface boundary of the continuous beam
        thick_c = cont_beam.height if face_n.dot(vz) > 0.9 else cont_beam.width
        face_pt = c_mid + face_n * (thick_c / 2.0)

        ax_u = cont_beam.centerline.direction.copy()
        ax_v = face_n.cross(ax_u)
        ax_u.unitize(); ax_v.unitize()

        # Build local plane frame for footprint clipping
        big = 1e3
        rect3d = [
            face_pt + ax_u * big + ax_v * big,
            face_pt - ax_u * big + ax_v * big,
            face_pt - ax_u * big - ax_v * big,
            face_pt + ax_u * big - ax_v * big,
        ]
        contact_plane = (face_pt, face_n)

        # Screw trajectory points back into the foundation beam
        screw_dir = face_n * -1
        screw_dir.unitize()

        def to2d(P):
            d = Vector.from_start_end(face_pt, P)
            return (d.dot(ax_u), d.dot(ax_v))

        def to3d(uv):
            return face_pt + ax_u * uv[0] + ax_v * uv[1]

        cl = abut_beam.centerline
        d_start = abs(Vector.from_start_end(face_pt, cl.start).dot(face_n))
        d_end = abs(Vector.from_start_end(face_pt, cl.end).dot(face_n))
        end_center = cl.start if d_start < d_end else cl.end

        axis = Vector.from_start_end(cl.midpoint, end_center)
        if axis.length < 1e-9: axis = cl.direction.copy()
        axis.unitize()

        abut_vy, abut_vz = abut_beam.frame.yaxis, abut_beam.frame.zaxis
        corners = [
            end_center + abut_vy * (w/2.0) + abut_vz * (h/2.0),
            end_center - abut_vy * (w/2.0) + abut_vz * (h/2.0),
            end_center - abut_vy * (w/2.0) - abut_vz * (h/2.0),
            end_center + abut_vy * (w/2.0) - abut_vz * (h/2.0),
        ]
        
        footprint_pts = []
        for corner in corners:
            res_pt = intersection_line_plane(Line(corner, corner + axis * 10.0), contact_plane)
            if res_pt: footprint_pts.append(Point(*res_pt))

        # Fallback security if boundary checking gets clipped due to shifting anomalies
        if len(footprint_pts) != 4:
            # Generate fallback lines right at the intersection interface center point
            center_of_area = face_pt
        else:
            rect2d = [to2d(P) for P in rect3d]
            foot2d = [to2d(P) for P in footprint_pts]
            if _signed_area_2d(rect2d) < 0: rect2d = rect2d[::-1]
            if _signed_area_2d(foot2d) < 0: foot2d = foot2d[::-1]

            overlap2d = _clip_convex(foot2d, rect2d)
            if overlap2d:
                center_uv = _poly_centroid_2d(overlap2d)
            else:
                center_uv = _poly_centroid_2d(foot2d)
            center_of_area = Point(*to3d(center_uv))

        # Track vectors for visual validation outputs
        self.debug_points.append(center_of_area)

        along = axis - face_n * axis.dot(face_n)
        if along.length < 1e-6: along = abut_beam.frame.xaxis.copy()
        along.unitize()
        across = face_n.cross(along)
        if across.length < 1e-6: across = abut_beam.frame.yaxis.copy()
        across.unitize()
        offset_vec = across * (self.screw_spacing / 2.0)

        # Pinpoint entry boundary face of abutting member
        best_face = None
        max_dot = -2.0
        for face in abut_beam.ref_sides[:4]:
            nrm = face.normal.copy()
            nrm.unitize()
            d = nrm.dot(face_n)
            if d > max_dot:
                max_dot = d
                best_face = face
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

        hw_lines = []
        for item in calculated:
            head = item["head"]
            final_tail = head + screw_dir * final_screw_length
            hw_lines.append(Line(head, final_tail))

        # Target the abutting beam to anchor downward safely
        return self._generate_features(hw_lines, [abut_beam], joint_label, final_screw_length)
    
    def _resolve_shallow_drilling(self, abut_beam, cont_beam, intersection_pt):
        # 1. Establish coordinate vectors
        dir_abut = abut_beam.centerline.direction.copy()
        vec_to_mid = Vector.from_start_end(intersection_pt, abut_beam.centerline.midpoint)
        if dir_abut.dot(vec_to_mid) < 0: 
            dir_abut.scale(-1)
        dir_abut.unitize()
        
        dir_cont = cont_beam.centerline.direction.copy()
        dir_cont.unitize()
        if dir_cont.dot(dir_abut) < 0:
            dir_cont.scale(-1)
            
        # Define the local plane of the joint
        plane_normal = dir_cont.cross(dir_abut)
        if plane_normal.length < 1e-5: 
            plane_normal = Vector(0, 0, 1)
        plane_normal.unitize()
        
        # 2. Construct the exact 40-degree target vector
        target_angle_rad = math.radians(40.0)
        
        v_perp = plane_normal.cross(dir_cont)
        v_perp.unitize()
        if v_perp.dot(dir_abut) < 0: 
            v_perp.scale(-1)
            
        # ideal_screw_dir points OUTWARDS from the continuous beam towards the abutting beam
        ideal_screw_dir = dir_cont * math.cos(target_angle_rad) + v_perp * math.sin(target_angle_rad)
        ideal_screw_dir.unitize()
        
        # The actual drilling direction is the reverse (from outside face into the continuous beam)
        screw_dir = ideal_screw_dir * -1

        # 3. Iteration Setup: Shift the piercing point along the continuous beam
        walk_step = 0.010  # 10mm increments
        max_steps = 60     # Walk up to 600mm down the beam
        anchor_depth = 0.060
        min_abut_length = 0.040 # Minimum length the screw must travel inside the abutting beam
        
        cat_a = abut_beam.attributes.get("category", "inner")
        cat_c = cont_beam.attributes.get("category", "inner")
        joint_label = "TButtJoint - arch (40° Fixed)" if cat_a == "arch" or cat_c == "arch" else "TButtJoint - inner (40° Fixed)"
        
        # 4. The "Slide and Check" Loop
        for step in range(max_steps):
            # Move the piercing point AWAY from the acute intersection corner along the continuous beam
            pierce_pt = intersection_pt + (dir_cont * (step * walk_step))
            
            # Check volumetric boundaries: How far back can we go along ideal_screw_dir before exiting the abutting beam?
            exit_dist = _ray_obb_exit(pierce_pt, ideal_screw_dir, abut_beam)
            
            if exit_dist is not None and exit_dist >= min_abut_length:
                # --- CAP THE RAYCAST DISTANCE FOR A 20mm BUFFER ZONE ---
                # Max allowed ray distance inside abutting beam = 150mm screw + 20mm buffer = 170mm (0.170m)
                max_allowed_ray = 0.150 + 0.020
                if exit_dist > max_allowed_ray:
                    exit_dist = max_allowed_ray
                # --------------------------------------------------------

                # We found a point where the chord through the abutting beam is thick enough.
                # Start point is exactly at the outer boundary (or capped boundary) of the abutting beam.
                start_pt = pierce_pt + (ideal_screw_dir * exit_dist)
                
                # Total length needed is the distance through the abutting beam + anchor depth into continuous beam
                req_screw_length = math.ceil((exit_dist + anchor_depth) / 0.010) * 0.010
                end_pt = start_pt + (screw_dir * req_screw_length)
                
                # Generate offset lines for lateral spacing
                offset_dir = screw_dir.cross(dir_cont)
                if offset_dir.length < 1e-5: offset_dir = Vector(0, 0, 1)
                offset_dir.unitize()
                offset_vec = offset_dir * (self.screw_spacing / 2.0)
                
                hw_line_1 = Line(start_pt + offset_vec, end_pt + offset_vec)
                hw_line_2 = Line(start_pt - offset_vec, end_pt - offset_vec)
                
                self._generate_features(
                    [hw_line_1, hw_line_2],
                    [cont_beam],
                    joint_label,
                    req_screw_length
                )
                return True
                
        return False

    def _apply_standard_butt_drilling(self, joint):
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
        dir_cont = cont_beam.centerline.direction.copy()
        
        angle_rad = dir_abut.angle(dir_cont)
        angle_deg = math.degrees(angle_rad)
        acute_angle_deg = min(angle_deg, 180.0 - angle_deg)

        # --- THE 40-DEGREE REROUTE ---
        if acute_angle_deg < 40.0:
            success = self._resolve_shallow_drilling(abut_beam, cont_beam, intersection_pt)
            
            # If the solver couldn't find a valid geometry without breaching, throw the visual flag
            if not success:
                flag_line = Line(intersection_pt, intersection_pt + Vector(0, 0, 0.2))
                self.failed_screw_info.append({
                    "line": flag_line,
                    "type": f"FAILED 40° SOLVE: {acute_angle_deg:.1f}°"
                })
            return
        # -----------------------------

        centerline = abut_beam.centerline
        dir_into_abut = centerline.direction.copy()
        vec_to_mid = Vector.from_start_end(intersection_pt, centerline.midpoint)
        if dir_into_abut.dot(vec_to_mid) < 0: dir_into_abut.scale(-1)
        dir_into_abut.unitize()

        thickness_c = max(cont_beam.width, cont_beam.height)
        start_pt = intersection_pt - (dir_into_abut * (thickness_c / 2.0))
        
        anchor_depth = 0.060
        raw_screw_length = thickness_c + anchor_depth
        req_screw_length = math.ceil(raw_screw_length / 0.010) * 0.010
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
        
        self._generate_features(
            [hw_line_1, hw_line_2],
            [cont_beam],
            joint_label,
            req_screw_length
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
        else: screw_dir.unitize()
            
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
        
        if pt_a.z > pt_b.z:
            beam_top, beam_bottom = beam_a, beam_b
        else:
            beam_top, beam_bottom = beam_b, beam_a

        if self.drill_type == "both":
            target_beams = [beam_a, beam_b]
        elif self.drill_type == "upper":
            target_beams = [beam_top]
        elif self.drill_type == "lower":
            target_beams = [beam_bottom]
        else:
            target_beams = [self._evaluate_majority_faces(beam_top, beam_bottom, screw_dir)]

        return self._generate_features([hw_line_1, hw_line_2], target_beams, joint_label, req_screw_length)
    
    def _evaluate_majority_faces(self, beam_top, beam_bottom, screw_dir):
        def get_pierced_face_normal(beam):
            if not hasattr(beam, 'frame'): 
                return Vector(0,0,1)
            
            dots = {
                "xaxis": abs(screw_dir.dot(beam.frame.xaxis)),
                "yaxis": abs(screw_dir.dot(beam.frame.yaxis)),
                "zaxis": abs(screw_dir.dot(beam.frame.zaxis))
            }
            max_axis = max(dots, key=dots.get)
            return max_axis

        top_hit = get_pierced_face_normal(beam_top)
        bottom_hit = get_pierced_face_normal(beam_bottom)

        if top_hit == "zaxis":
            return beam_top
        elif bottom_hit == "zaxis":
            return beam_bottom
        
        return beam_top

    def _generate_features(self, hw_lines, target_beams, joint_label, req_screw_length):
        success = False
        
        if joint_label not in self.hardware_screws_by_type:
            self.hardware_screws_by_type[joint_label] = 0
            self.screw_lengths_by_type[joint_label] = []

        req_mm = req_screw_length * 1000.0
        if req_mm < 130:
            assigned_len = 100
        elif req_mm < 150:
            assigned_len = 130
        elif req_mm <= 150.1:
            assigned_len = 150
        else:
            assigned_len = "Oversized"
            
        for i in range(len(hw_lines)):
            hw_line = hw_lines[i]
            line_added_to_any = False
            
            for beam in target_beams:
                try:
                    drill = Drilling.from_line_and_element(hw_line, beam, diameter=self.screw_diameter)
                    
                    if hasattr(beam, 'add_feature'): beam.add_feature(drill)
                    else: beam.features.append(drill)
                    line_added_to_any = True
                except Exception:
                    pass
            
            if line_added_to_any:
                self.drilling_count += 1
                self.screw_lines.append(hw_line)
                self.hardware_screws_by_type[joint_label] += 1
                self.screw_lengths_by_type[joint_label].append(req_screw_length)
                
                self.screw_assigned_lengths.append(assigned_len)
                self.inventory_counts[assigned_len] += 1
                
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