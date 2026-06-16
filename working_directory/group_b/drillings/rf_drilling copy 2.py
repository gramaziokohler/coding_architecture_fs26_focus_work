import math
from compas.geometry import (
    Point,
    Vector,
    Line,
    intersection_line_line,
    distance_point_point,
    intersection_line_plane,
)
from compas_timber.fabrication import Drilling
from compas_timber.connections import (
    LMiterJoint,
    TButtJoint,
    TLapJoint,
    XLapJoint,
)


# ---------------------------------------------------------------------------
# Geometry helpers for the true contact surface & obb calculations
# ---------------------------------------------------------------------------
def _poly_centroid_2d(pts):
    n = len(pts)
    if n == 0:
        return None
    if n < 3:
        return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
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
        if abs(den) < 1e-15:
            return e
        return ((n1 * dp[0] - n2 * dc[0]) / den, (n1 * dp[1] - n2 * dc[0]) / den)

    out = subject[:]
    m = len(clip)
    for i in range(m):
        a = clip[i]
        b = clip[(i + 1) % m]
        inp = out
        out = []
        if not inp:
            break
        s = inp[-1]
        for e in inp:
            if inside(e, a, b):
                if not inside(s, a, b):
                    out.append(inter(s, e, a, b))
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
    ax = [
        beam.frame.xaxis.unitized(),
        beam.frame.yaxis.unitized(),
        beam.frame.zaxis.unitized(),
    ]
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
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
        elif (-half[i] - e) > 0 or (half[i] - e) < 0:
            return None
    if tmax < tmin:
        return None
    return tmax


def _ray_obb_intersect(origin, direction, beam):
    cl = beam.centerline
    cen = cl.midpoint
    if not hasattr(beam, "frame"):
        return None

    ax = [
        beam.frame.xaxis.unitized(),
        beam.frame.yaxis.unitized(),
        beam.frame.zaxis.unitized(),
    ]
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
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
        elif (-half[i] - e) > 0 or (half[i] - e) < 0:
            return None

    if tmax < tmin or tmax < 0:
        return None

    return tmin if tmin > 0 else 0.0


def _point_in_obb_with_margin(pt, beam, margin):
    """Return True if pt is at least *margin* metres inside every face of the beam OBB."""
    cl = beam.centerline
    cen = cl.midpoint
    ax = [
        beam.frame.xaxis.unitized(),
        beam.frame.yaxis.unitized(),
        beam.frame.zaxis.unitized(),
    ]
    half = [cl.length / 2.0, beam.width / 2.0, beam.height / 2.0]
    o = Vector.from_start_end(cen, pt)
    for i in range(3):
        if abs(o.dot(ax[i])) > half[i] - margin:
            return False
    return True


class DrillingProcessor:
    # Standard screw lengths (m), longest first.
    STANDARD_LENGTHS = (0.150, 0.130, 0.100)
    # Candidate out-of-plane tilt angles (deg); the search is capped at target_tilt.
    TILT_DEGREES = (0, 5, 10, 15, 20, 25, 30, 35, 40, 45)

    def __init__(
        self,
        timber_model,
        screw_diameter=0.006,
        screw_length=0.150,
        screw_spacing=0.030,
        max_drilling_depth=None,
        max_arch_penetration=None,
        drill_type="both",
        edge_margin=0.010,
        clearance=0.170,
        target_tilt=30.0,
    ):
        self.timber_model = timber_model
        self.screw_diameter = screw_diameter
        self.screw_length = screw_length
        self.screw_spacing = screw_spacing
        self.max_drilling_depth = max_drilling_depth
        self.max_arch_penetration = max_arch_penetration
        self.drill_type = drill_type
        self.edge_margin = edge_margin
        self.clearance = clearance
        self.target_tilt = target_tilt

        self.drilling_count = 0
        self.screw_lines = []
        self.place_first_screw_lines = []
        self.screw_assigned_lengths = []
        self.failed_screw_info = []
        self.summary_text = ""
        self.joinery_errors = []

        self.processed_beam_pairs = set()
        self.debug_points = []
        self.contact_polylines = []
        self.clearance_lines = []

        self.hardware_screws_by_type = {}
        self.screw_lengths_by_type = {}
        self.extrema_screws_by_type = {}

        self.inventory_counts = {100: 0, 130: 0, 150: 0, 190: 0}
        self.miter_inventory_counts = {"Miter Standard": 0}

    def process_drillings(self):
        print("--- Starting Drilling Generation ---")

        self.drilling_count = 0
        self.screw_lines = []
        self.place_first_screw_lines = []
        self.screw_assigned_lengths = []
        self.failed_screw_info = []
        self.summary_text = ""
        self.joinery_errors = []
        self.processed_beam_pairs = set()
        self.debug_points = []
        self.contact_polylines = []
        self.clearance_lines = []

        self.hardware_screws_by_type = {}
        self.screw_lengths_by_type = {}
        self.extrema_screws_by_type = {}

        self.inventory_counts = {100: 0, 130: 0, 150: 0, 190: 0}
        self.miter_inventory_counts = {"Miter Standard": 0}
        self.manual_foundation_inventory_counts = {"Foundation Screw Spec": 0}

        miter_joints_detected = {"Lmitter arch": 0, "Lmitter foundation": 0}
        llap_joints_count = 0

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

        for joint in joints:
            joint_classname = type(joint).__name__

            if joint_classname == "CutoffLLapJoint":
                llap_joints_count += 1
                self.inventory_counts[130] += 2
                continue

            elements = getattr(joint, "elements", None)
            if not elements and hasattr(joint, "main_beam"):
                elements = [joint.main_beam, getattr(joint, "cross_beam")]

            if not elements or len(elements) < 2 or not elements[0] or not elements[1]:
                continue

            def get_uid(beam):
                if "edge" in beam.attributes:
                    return str(beam.attributes["edge"])
                mid = beam.centerline.midpoint
                return f"{round(mid.x, 3)}_{round(mid.y, 3)}_{round(mid.z, 3)}"

            uid_a = get_uid(elements[0])
            uid_b = get_uid(elements[1])
            pair_id = frozenset([uid_a, uid_b])

            if pair_id in self.processed_beam_pairs:
                continue
            self.processed_beam_pairs.add(pair_id)

            if isinstance(joint, TButtJoint):
                # GEOMETRIC RESOLUTION: Foolproof way to determine abutting vs continuous
                line1, line2 = elements[0].centerline, elements[1].centerline
                res = intersection_line_line(line1, line2)
                if not res or res[0] is None:
                    continue
                mid_pt = Point(*res[0])

                # Check which beam's endpoint is closest to the intersection
                d1 = min(
                    distance_point_point(mid_pt, line1.start),
                    distance_point_point(mid_pt, line1.end),
                )
                d2 = min(
                    distance_point_point(mid_pt, line2.start),
                    distance_point_point(mid_pt, line2.end),
                )

                if d1 < d2:
                    abut_beam, cont_beam = elements[0], elements[1]
                else:
                    abut_beam, cont_beam = elements[1], elements[0]

                cat_c = cont_beam.attributes.get("category", "inner")
                cat_a = abut_beam.attributes.get("category", "inner")

                # Routing
                if cat_c == "base" or cat_a == "base":
                    if cat_a == "base":
                        cont_beam, abut_beam = abut_beam, cont_beam
                    self._apply_foundation_butt_drilling(joint, abut_beam, cont_beam)
                elif cat_c == "arch" or cat_a == "arch":
                    self._apply_arch_tbutt_drilling(joint, abut_beam, cont_beam)
                else:
                    self._apply_tbutt_drilling(joint, abut_beam, cont_beam)

            elif isinstance(joint, (XLapJoint, TLapJoint)):
                self._apply_lap_drilling(joint, elements[0], elements[1])

            elif isinstance(joint, LMiterJoint):
                cat1 = elements[0].attributes.get("category", "inner")
                cat2 = elements[1].attributes.get("category", "inner")
                label = (
                    "Lmitter foundation"
                    if (cat1 == "base" or cat2 == "base")
                    else "Lmitter arch"
                )
                miter_joints_detected[label] += 1

                screws_to_add = 16 if "foundation" in label.lower() else 8
                self.miter_inventory_counts["Miter Standard"] += screws_to_add

        manual_foundation_screws = 20 * 4
        self.manual_foundation_inventory_counts["Foundation Screw Spec"] += (
            manual_foundation_screws
        )

        log = []
        log.append("================================================================")
        log.append("            PROCUREMENT & DRILLING SUMMARY                    ")
        log.append("================================================================")
        log.append(
            f"Unique Joints Processed Geometry: {len(self.processed_beam_pairs)}"
        )
        log.append(f"Lap Joint : {llap_joints_count} ( 2x 130mm screws/joint)")
        log.append(f"Screw Foundation  : 20 ( 4x Separate Foundation screws/joint)")
        log.append("----------------------------------------------------------------")

        summary_counts = {}
        summary_lengths = {}

        for j_type, count in self.hardware_screws_by_type.items():
            if count == 0:
                continue

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

        for m_type, count in sorted(miter_joints_detected.items()):
            if count > 0:
                screws = (count * 16) if "foundation" in m_type.lower() else (count * 8)
                log.append(f"[{m_type}]")
                log.append(
                    f"  -> Unmodeled Screws : {screws} ({count} joints estimated)\n"
                )

        log.append("----------------------------------------------------------------")
        log.append("                    INVENTORY TO PROCURE                        ")
        log.append("----------------------------------------------------------------")

        color_map = {100: "GREEN", 130: "BLUE", 150: "ORANGE", 190: "RED"}

        for length in [100, 130, 150, 190]:
            count = self.inventory_counts[length]
            boxes = math.ceil(count / 100.0)
            color_label = color_map[length]
            log.append(
                f" Screw {length} mm [{color_label:^6}] : {count:4} pcs  ->  {boxes} boxes (100/box)"
            )

        found_total = self.manual_foundation_inventory_counts["Foundation Screw Spec"]
        found_boxes = math.ceil(found_total / 100.0)
        log.append(f" Foundation Screw : {found_total:4} pcs  ->  {found_boxes} boxes")

        miter_total = self.miter_inventory_counts["Miter Standard"]
        miter_boxes = math.ceil(miter_total / 100.0)
        log.append(f" Miter Arch : {miter_total:4} pcs  ->  {miter_boxes} boxes")
        log.append("================================================================")

        self.summary_text = "\n".join(log)

        # Expose clearance probe lines (head -> outwards) for downstream viz.
        self.timber_model.rf_clearance_lines = [
            [[ln.start.x, ln.start.y, ln.start.z], [ln.end.x, ln.end.y, ln.end.z]]
            for ln in self.clearance_lines
        ]
        return self.timber_model

    # ---------------------------------------------------------------------------
    # Foundation T-Butt Methods
    # ---------------------------------------------------------------------------
    def _surface_entry(self, pos, screw_dir, beam):
        if not hasattr(beam, "frame"):
            return None
        c = beam.centerline.midpoint
        vx, vy, vz = beam.frame.xaxis, beam.frame.yaxis, beam.frame.zaxis
        w, h = beam.width, beam.height
        planes = [
            (c + vy * (w / 2.0), vy),
            (c - vy * (w / 2.0), -vy),
            (c + vz * (h / 2.0), vz),
            (c - vz * (h / 2.0), -vz),
        ]
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
                    if (
                        abs(vec_c.dot(vy)) <= (w / 2.0) + 0.005
                        and abs(vec_c.dot(vz)) <= (h / 2.0) + 0.005
                    ):
                        candidates.append(res_pt)
        if not candidates:
            return None
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
        if vec_to_abut.dot(face_n) < 0:
            face_n.scale(-1)
        face_n.unitize()

        thick_c = cont_beam.height if face_n.dot(vz) > 0.9 else cont_beam.width
        face_pt = c_mid + face_n * (thick_c / 2.0)

        ax_u = cont_beam.centerline.direction.copy()
        ax_v = face_n.cross(ax_u)
        ax_u.unitize()
        ax_v.unitize()

        big = 1e3
        rect3d = [
            face_pt + ax_u * big + ax_v * big,
            face_pt - ax_u * big + ax_v * big,
            face_pt - ax_u * big - ax_v * big,
            face_pt + ax_u * big - ax_v * big,
        ]
        contact_plane = (face_pt, face_n)
        screw_dir = face_n * -1
        screw_dir.unitize()

        def to2d(P):
            return (
                Vector.from_start_end(face_pt, P).dot(ax_u),
                Vector.from_start_end(face_pt, P).dot(ax_v),
            )

        def to3d(uv):
            return face_pt + ax_u * uv[0] + ax_v * uv[1]

        cl = abut_beam.centerline
        d_start = abs(Vector.from_start_end(face_pt, cl.start).dot(face_n))
        d_end = abs(Vector.from_start_end(face_pt, cl.end).dot(face_n))
        end_center = cl.start if d_start < d_end else cl.end

        axis = Vector.from_start_end(cl.midpoint, end_center)
        if axis.length < 1e-9:
            axis = cl.direction.copy()
        axis.unitize()

        abut_vy, abut_vz = abut_beam.frame.yaxis, abut_beam.frame.zaxis
        corners = [
            end_center + abut_vy * (w / 2.0) + abut_vz * (h / 2.0),
            end_center - abut_vy * (w / 2.0) + abut_vz * (h / 2.0),
            end_center - abut_vy * (w / 2.0) - abut_vz * (h / 2.0),
            end_center + abut_vy * (w / 2.0) - abut_vz * (h / 2.0),
        ]

        footprint_pts = []
        for corner in corners:
            res_pt = intersection_line_plane(
                Line(corner, corner + axis * 10.0), contact_plane
            )
            if res_pt:
                footprint_pts.append(Point(*res_pt))

        if len(footprint_pts) != 4:
            center_of_area = face_pt
        else:
            rect2d, foot2d = [to2d(P) for P in rect3d], [to2d(P) for P in footprint_pts]
            if _signed_area_2d(rect2d) < 0:
                rect2d = rect2d[::-1]
            if _signed_area_2d(foot2d) < 0:
                foot2d = foot2d[::-1]

            overlap2d = _clip_convex(foot2d, rect2d)
            center_uv = (
                _poly_centroid_2d(overlap2d) if overlap2d else _poly_centroid_2d(foot2d)
            )
            center_of_area = Point(*to3d(center_uv))

        along = axis - face_n * axis.dot(face_n)
        if along.length < 1e-6:
            along = abut_beam.frame.xaxis.copy()
        along.unitize()
        across = face_n.cross(along)
        if across.length < 1e-6:
            across = abut_beam.frame.yaxis.copy()
        across.unitize()
        offset_vec = across * (self.screw_spacing / 2.0)

        best_face, max_dot = None, -2.0
        for face in abut_beam.ref_sides[:4]:
            nrm = face.normal.copy()
            nrm.unitize()
            d = nrm.dot(face_n)
            if d > max_dot:
                max_dot, best_face = d, face
        arch_top_plane = (best_face.point, best_face.normal)

        penetration_cap = self.max_arch_penetration if self.max_arch_penetration else h
        calculated = []
        for sign in (offset_vec, -offset_vec):
            contact_pt = center_of_area + sign
            target_tail = contact_pt + screw_dir * 0.080
            exit_dist = _ray_obb_exit(contact_pt, face_n, abut_beam)
            if exit_dist is None or exit_dist <= 1e-6:
                res_top = intersection_line_plane(
                    Line(contact_pt, contact_pt + face_n * 5.0), arch_top_plane
                )
                exit_dist = (
                    distance_point_point(contact_pt, Point(*res_top))
                    if res_top
                    else max(w, h)
                )

            head_dist = min(exit_dist, penetration_cap)
            head = contact_pt + face_n * head_dist
            raw_len = distance_point_point(head, target_tail)
            req_len = math.ceil(raw_len / 0.010) * 0.010
            calculated.append({"head": head, "req_len": req_len})

        final_screw_length = max(item["req_len"] for item in calculated)

        if final_screw_length > 0.150:
            final_screw_length = 0.150

        hw_lines = [
            Line(item["head"], item["head"] + screw_dir * final_screw_length)
            for item in calculated
        ]
        return self._generate_features(
            hw_lines, [abut_beam], joint_label, final_screw_length
        )

    # ---------------------------------------------------------------------------
    # Arch T-Butt Logic
    # ---------------------------------------------------------------------------
    def _apply_arch_tbutt_drilling(self, joint, abut_beam, cont_beam):
        """
        Arch T-Butt: screws travel along (or near) the abutting beam centerline,
        entering through the face of the continuous beam.

        Rules:
          - Natural drill direction = abutting-beam centerline (into the abutting beam).
          - The drilling angle is measured between the screw direction and the entry
            face surface of the continuous beam (i.e. 90° - angle_to_face_normal).
          - If that angle < 40°, clamp to exactly 40° by rotating in the plane
            spanned by (axis, face_normal).
          - Screw length fixed at 150 mm.
          - Tip must be >= 10 mm inside the abutting beam.
          - Entry point is slid along the continuous-beam face to bring the tip as
            close as possible to the abutting-beam centerline while satisfying the
            10 mm tip-margin constraint.
          - Two screws, offset +/- screw_spacing/2 along the continuous beam direction.
        """
        if abut_beam is None or cont_beam is None:
            return

        SCREW_LENGTH = 0.190
        TIP_MARGIN   = 0.010
        MIN_ANGLE    = 40.0       # degrees between screw and entry-face surface
        joint_label  = "TButtJoint - arch"

        # ------------------------------------------------------------------ #
        # 1. Joint point & natural screw axis (= abutting-beam centerline)   #
        # ------------------------------------------------------------------ #
        res = intersection_line_line(abut_beam.centerline, cont_beam.centerline)
        if not res or res[0] is None:
            return
        joint_pt = Point(*res[0])

        axis = abut_beam.centerline.direction.copy()
        # Make sure axis points INTO the abutting beam body from the joint point
        if axis.dot(Vector.from_start_end(joint_pt, abut_beam.centerline.midpoint)) < 0:
            axis.scale(-1)
        axis.unitize()

        # ------------------------------------------------------------------ #
        # 2. Entry face on the continuous beam                                #
        # The screw enters through the face whose outward normal most opposes #
        # 'axis' (i.e. the face the screw would emerge from on the cont side).#
        # ------------------------------------------------------------------ #
        entry_face = None
        best_dot = 2.0
        for face in cont_beam.ref_sides[:4]:
            d = face.normal.unitized().dot(axis)
            if d < best_dot:
                best_dot = d
                entry_face = face

        if entry_face is None:
            return

        face_normal = entry_face.normal.unitized()  # points OUTWARD from cont_beam
        face_pt     = entry_face.point              # a point on the face plane

        # ------------------------------------------------------------------ #
        # 3. Drilling angle = angle between screw direction and face surface  #
        #    sin(drilling_angle) = |dot(axis, face_normal)|                   #
        # ------------------------------------------------------------------ #
        sin_val = min(abs(axis.dot(face_normal)), 1.0)
        drilling_angle_deg = math.degrees(math.asin(sin_val))

        # ------------------------------------------------------------------ #
        # 4. If drilling angle < 40°, clamp to exactly 40°                   #
        #    Rotate in the plane of (tangent_on_face, -face_normal).          #
        # ------------------------------------------------------------------ #
        if drilling_angle_deg < MIN_ANGLE:
            tangent = axis - face_normal * axis.dot(face_normal)
            if tangent.length < 1e-9:
                screw_dir = axis.copy()
            else:
                tangent.unitize()
                theta = math.radians(MIN_ANGLE)
                # cos(theta) along face surface + sin(theta) into the face
                screw_dir = tangent * math.cos(theta) + face_normal * (-math.sin(theta))
                screw_dir.unitize()
        else:
            screw_dir = axis.copy()
            screw_dir.unitize()

        # ------------------------------------------------------------------ #
        # 5. Offset direction for the two side-by-side screws                 #
        #    Along the continuous beam, projected onto the face plane.         #
        # ------------------------------------------------------------------ #
        cont_dir = cont_beam.centerline.direction.copy()
        cont_dir = cont_dir - screw_dir * cont_dir.dot(screw_dir)
        if cont_dir.length < 1e-6:
            cont_dir = cont_beam.frame.yaxis.copy()
        cont_dir.unitize()
        offset_vec = cont_dir * (self.screw_spacing / 2.0)

        # ------------------------------------------------------------------ #
        # 6. Helper: distance from a point to the abutting-beam centerline    #
        # ------------------------------------------------------------------ #
        abut_cl_pt  = abut_beam.centerline.midpoint
        abut_cl_dir = abut_beam.centerline.direction.unitized()

        def dist_to_abut_centerline(pt):
            v = Vector.from_start_end(abut_cl_pt, pt)
            proj = v.dot(abut_cl_dir)
            closest = abut_cl_pt + abut_cl_dir * proj
            return distance_point_point(pt, closest)

        # ------------------------------------------------------------------ #
        # 7. Find best entry point for one screw position                     #
        # ------------------------------------------------------------------ #
        def find_best_entry(base_pt):
            """
            Project base_pt onto the entry face along screw_dir.
            If the 150 mm tip lands >= TIP_MARGIN inside abut_beam, done.
            Otherwise slide the entry point on the face (grid search) to find
            the position where the tip is deepest inside abut_beam and as close
            as possible to its centerline.
            Returns (head_pt, tip_pt) or (None, None) on failure.
            """
            res = intersection_line_plane(
                Line(base_pt, base_pt + screw_dir),
                (face_pt, face_normal),
            )
            if res is None:
                return None, None
            head0 = Point(*res)

            # Quick check: tip already valid at the nominal position?
            tip0 = head0 + screw_dir * SCREW_LENGTH
            if self._point_in_beam(tip0, abut_beam, TIP_MARGIN):
                return head0, tip0

            # Slide on the face using two orthogonal axes
            face_u = cont_dir                               # already lies on face
            face_v = face_normal.cross(face_u).unitized()   # second face axis

            search_range = max(cont_beam.width, cont_beam.height)
            steps = 20
            best_head = None
            best_dist = 1e18

            for iu in range(-steps, steps + 1):
                for iv in range(-steps, steps + 1):
                    du = (iu / steps) * search_range
                    dv = (iv / steps) * search_range
                    cand_head = head0 + face_u * du + face_v * dv

                    # Entry point must lie on (inside) the continuous beam face
                    if not self._point_in_beam(cand_head, cont_beam, 0.0):
                        continue

                    tip = cand_head + screw_dir * SCREW_LENGTH
                    if not self._point_in_beam(tip, abut_beam, TIP_MARGIN):
                        continue

                    # Prefer tip closest to abutting-beam centerline
                    score = dist_to_abut_centerline(tip)
                    if score < best_dist:
                        best_dist = score
                        best_head = cand_head

            if best_head is None:
                return None, None
            return best_head, best_head + screw_dir * SCREW_LENGTH

        # ------------------------------------------------------------------ #
        # 8. Build the two screw lines                                        #
        # ------------------------------------------------------------------ #
        hw_lines = []
        for sign in (1.0, -1.0):
            base = joint_pt + offset_vec * sign
            head, tip = find_best_entry(base)
            if head is None:
                continue
            hw_lines.append(Line(head, tip))

        if not hw_lines:
            self.failed_screw_info.append({
                "line": None,
                "type": f"{joint_label}: no valid entry found",
            })
            return

        self._generate_features(hw_lines, [cont_beam, abut_beam], joint_label, SCREW_LENGTH)

    # ---------------------------------------------------------------------------
    # Generalized Inner T-Butt Logic (UNTOUCHED)
    # ---------------------------------------------------------------------------
    def _apply_tbutt_drilling(self, joint, abut_beam, cont_beam):
        """Two screws per T-Butt along the abutting beam, kept clear of other beams."""
        if abut_beam is None or cont_beam is None:
            return

        joint_label = "TButtJoint - inner"

        res = intersection_line_line(abut_beam.centerline, cont_beam.centerline)
        if not res or res[0] is None:
            return
        pa, pb = Point(*res[0]), Point(*res[1])
        joint_pt = Point((pa.x + pb.x) / 2.0, (pa.y + pb.y) / 2.0, (pa.z + pb.z) / 2.0)

        axis = abut_beam.centerline.direction.copy()
        if axis.dot(Vector.from_start_end(joint_pt, abut_beam.centerline.midpoint)) < 0:
            axis.scale(-1)
        axis.unitize()

        offset_dir = cont_beam.centerline.direction.copy()
        offset_dir = offset_dir - axis * offset_dir.dot(axis)
        if offset_dir.length < 1e-6:
            offset_dir = abut_beam.frame.yaxis.copy()
        offset_dir.unitize()
        offset_vec = offset_dir * (self.screw_spacing / 2.0)

        n = axis.cross(cont_beam.centerline.direction)
        if n.length < 1e-6:
            n = abut_beam.frame.zaxis.copy()
        n.unitize()

        entry_face = self._entry_face(cont_beam, axis)
        others = [
            b
            for b in self.timber_model.beams
            if b is not abut_beam and b is not cont_beam
        ]
        edge_slide = max(self._half_extent_along(abut_beam, n) - self.edge_margin, 0.0)

        tilt_order = [0] + sorted(
            (a for a in self.TILT_DEGREES if 0 < a <= self.target_tilt), reverse=True
        )
        chosen = None
        for deg in tilt_order:
            theta = math.radians(deg)
            for d in ((0.0,) if deg == 0 else (1.0, -1.0)):
                screw_dir = axis * math.cos(theta) + n * (d * math.sin(theta))
                screw_dir.unitize()

                slide = -d * edge_slide
                heads = [
                    self._face_entry_point(
                        joint_pt + offset_vec * sign + n * slide, screw_dir, entry_face
                    )
                    for sign in (1.0, -1.0)
                ]
                if any(h is None for h in heads):
                    continue
                if not all(self._point_in_beam(h, cont_beam, -0.003) for h in heads):
                    continue

                tool_dir = screw_dir * -1.0
                if not all(
                    self._probe_clear(h, tool_dir, others, self.clearance) for h in heads
                ):
                    continue

                length = None
                for cand in self.STANDARD_LENGTHS:
                    if all(
                        self._point_in_beam(
                            h + screw_dir * cand, abut_beam, self.edge_margin
                        )
                        for h in heads
                    ):
                        length = cand
                        break
                if length is None:
                    continue
                chosen = (screw_dir, heads, length)
                break
            if chosen:
                break

        if chosen is None:
            tool_dir = axis * -1.0
            for sign in (1.0, -1.0):
                base = joint_pt + offset_vec * sign
                head = self._face_entry_point(base, axis, entry_face) or base
                probe = Line(head, head + tool_dir * self.clearance)
                self.clearance_lines.append(probe)
                self.failed_screw_info.append(
                    {"line": probe, "type": f"{joint_label}: no 170mm clearance"}
                )
            return

        screw_dir, heads, length = chosen
        tool_dir = screw_dir * -1.0
        hw_lines = [Line(h, h + screw_dir * length) for h in heads]
        for h in heads:
            self.clearance_lines.append(Line(h, h + tool_dir * self.clearance))
        self._generate_features(hw_lines, [cont_beam], joint_label, length)

    def _entry_face(self, beam, axis):
        """Side face whose outward normal most opposes ``axis``."""
        best, best_dot = None, 2.0
        for face in beam.ref_sides[:4]:
            d = face.normal.unitized().dot(axis)
            if d < best_dot:
                best_dot, best = d, face
        return best

    def _face_entry_point(self, center, axis, face):
        """Intersection of the screw centerline with a ref-side face plane."""
        if face is None:
            return None
        res = intersection_line_plane(
            Line(center, center + axis), (face.point, face.normal)
        )
        return Point(*res) if res else None

    def _half_extent_along(self, beam, direction):
        """Distance from the beam centerline to its cross-section edge along ``direction``."""
        u = direction.unitized()
        ny = abs(u.dot(beam.frame.yaxis.unitized()))
        nz = abs(u.dot(beam.frame.zaxis.unitized()))
        cands = []
        if ny > 1e-9:
            cands.append((beam.width / 2.0) / ny)
        if nz > 1e-9:
            cands.append((beam.height / 2.0) / nz)
        return min(cands) if cands else 0.0

    def _point_in_beam(self, pt, beam, margin):
        """True if ``pt`` is at least ``margin`` inside every face of the beam box."""
        ax = (
            beam.frame.xaxis.unitized(),
            beam.frame.yaxis.unitized(),
            beam.frame.zaxis.unitized(),
        )
        half = (beam.centerline.length / 2.0, beam.width / 2.0, beam.height / 2.0)
        o = Vector.from_start_end(beam.centerline.midpoint, pt)
        return all(abs(o.dot(ax[i])) <= half[i] - margin for i in range(3))

    def _probe_clear(self, origin, direction, beams, length):
        """True if a ray from ``origin`` along ``direction`` hits no beam within ``length``."""
        for b in beams:
            t = self._ray_obb_t(origin, direction, b)
            if t is not None and t < length:
                return False
        return True

    def _ray_obb_t(self, origin, direction, beam):
        """Entry distance where a ray first enters a beam's oriented box, else None."""
        cl = beam.centerline
        ax = (
            beam.frame.xaxis.unitized(),
            beam.frame.yaxis.unitized(),
            beam.frame.zaxis.unitized(),
        )
        half = (cl.length / 2.0, beam.width / 2.0, beam.height / 2.0)
        o = Vector.from_start_end(cl.midpoint, origin)
        tmin, tmax = -1e18, 1e18
        for i in range(3):
            e = o.dot(ax[i])
            f = direction.dot(ax[i])
            if abs(f) > 1e-9:
                t1 = (-half[i] - e) / f
                t2 = (half[i] - e) / f
                if t1 > t2:
                    t1, t2 = t2, t1
                tmin = max(tmin, t1)
                tmax = min(tmax, t2)
            elif (-half[i] - e) > 0 or (half[i] - e) < 0:
                return None
        if tmax < tmin or tmax < 0:
            return None
        return tmin if tmin > 0 else 0.0

    # ---------------------------------------------------------------------------
    # Common / Shared Logic
    # ---------------------------------------------------------------------------
    def _apply_lap_drilling(self, joint, beam_a, beam_b):
        joint_label = type(joint).__name__
        line_a, line_b = beam_a.centerline, beam_b.centerline
        res = intersection_line_line(line_a, line_b)
        if not res or res[0] is None:
            return False

        pt_a, pt_b = (
            Point(res[0][0], res[0][1], res[0][2]),
            Point(res[1][0], res[1][1], res[1][2]),
        )
        mid_pt = Point(
            (pt_a.x + pt_b.x) / 2.0, (pt_a.y + pt_b.y) / 2.0, (pt_a.z + pt_b.z) / 2.0
        )

        dir_a, dir_b = line_a.direction, line_b.direction
        screw_dir = dir_a.cross(dir_b)

        if screw_dir.length < 1e-5:
            screw_dir = (
                beam_a.frame.zaxis if hasattr(beam_a, "frame") else Vector(0, 0, 1)
            )
        else:
            screw_dir.unitize()

        offset_dir = dir_a + dir_b
        if offset_dir.length < 1e-5:
            offset_dir = dir_a
        offset_dir.unitize()
        offset_vec = offset_dir * (self.screw_spacing / 2.0)
        center_1, center_2 = mid_pt + offset_vec, mid_pt - offset_vec

        thickness_a = math.sqrt(beam_a.width**2 + beam_a.height**2)
        thickness_b = math.sqrt(beam_b.width**2 + beam_b.height**2)
        true_total_thickness = (
            distance_point_point(pt_a, pt_b) + (thickness_a / 2.0) + (thickness_b / 2.0)
        )

        req_screw_length = math.floor((true_total_thickness - 0.010) / 0.010) * 0.010
        if req_screw_length < 0.040:
            req_screw_length = 0.040

        if req_screw_length > 0.150:
            req_screw_length = 0.150

        hw_line_1 = Line(
            center_1 - (screw_dir * (req_screw_length / 2.0)),
            center_1 + (screw_dir * (req_screw_length / 2.0)),
        )
        hw_line_2 = Line(
            center_2 - (screw_dir * (req_screw_length / 2.0)),
            center_2 + (screw_dir * (req_screw_length / 2.0)),
        )

        beam_top, beam_bottom = (
            (beam_a, beam_b) if pt_a.z > pt_b.z else (beam_b, beam_a)
        )

        if self.drill_type == "both":
            target_beams = [beam_a, beam_b]
        elif self.drill_type == "upper":
            target_beams = [beam_top]
        elif self.drill_type == "lower":
            target_beams = [beam_bottom]
        else:
            target_beams = [
                self._evaluate_majority_faces(beam_top, beam_bottom, screw_dir)
            ]

        return self._generate_features(
            [hw_line_1, hw_line_2], target_beams, joint_label, req_screw_length
        )

    def _evaluate_majority_faces(self, beam_top, beam_bottom, screw_dir):
        def get_pierced_face_normal(beam):
            if not hasattr(beam, "frame"):
                return Vector(0, 0, 1)
            dots = {
                "xaxis": abs(screw_dir.dot(beam.frame.xaxis)),
                "yaxis": abs(screw_dir.dot(beam.frame.yaxis)),
                "zaxis": abs(screw_dir.dot(beam.frame.zaxis)),
            }
            return max(dots, key=dots.get)

        top_hit = get_pierced_face_normal(beam_top)
        bottom_hit = get_pierced_face_normal(beam_bottom)

        if top_hit == "zaxis":
            return beam_top
        elif bottom_hit == "zaxis":
            return beam_bottom
        return beam_top

    def _generate_features(
        self, hw_lines, target_beams, joint_label, req_screw_length, place_first=False
    ):
        success = False

        if joint_label not in self.hardware_screws_by_type:
            self.hardware_screws_by_type[joint_label] = 0
            self.screw_lengths_by_type[joint_label] = []

        req_mm = req_screw_length * 1000.0

        if req_mm <= 100:
            assigned_len = 100
        elif req_mm <= 130:
            assigned_len = 130
        elif req_mm <= 150:
            assigned_len = 150
        elif req_mm <= 190:
            assigned_len = 190
        else:
            assigned_len = 190

        def store_web_feature(beam, line):
            web_color_map = {
                100: "#00FF00",  # GREEN
                130: "#0000FF",  # BLUE
                150: "#FFA500",  # ORANGE
                190: "#FF0000",  # RED
            }

            attributes = getattr(beam, "attributes", None)
            if attributes is None:
                attributes = {}
                setattr(beam, "attributes", attributes)
            web_features = attributes.setdefault("web_features", [])
            web_features.append(
                {
                    "type": "Screw",
                    "joint_type": joint_label,
                    "start": [
                        float(line.start.x),
                        float(line.start.y),
                        float(line.start.z),
                    ],
                    "end": [float(line.end.x), float(line.end.y), float(line.end.z)],
                    "diameter_m": float(self.screw_diameter),
                    "length_m": float(req_screw_length),
                    "length_mm": round(float(req_screw_length) * 1000.0, 1),
                    "assigned_length_mm": assigned_len,
                    "color": web_color_map.get(assigned_len, "#FF0000"),
                    "place_first": place_first,
                }
            )

        for i in range(len(hw_lines)):
            hw_line = hw_lines[i]
            line_added_to_any = False

            for beam in target_beams:
                try:
                    drill = Drilling.from_line_and_element(
                        hw_line, beam, diameter=self.screw_diameter
                    )
                    if hasattr(beam, "add_feature"):
                        beam.add_feature(drill)
                    else:
                        beam.features.append(drill)
                    store_web_feature(beam, hw_line)
                    line_added_to_any = True
                except Exception:
                    pass

            if line_added_to_any:
                self.drilling_count += 1
                self.screw_lines.append(hw_line)
                if place_first:
                    self.place_first_screw_lines.append(hw_line)
                self.hardware_screws_by_type[joint_label] += 1
                self.screw_lengths_by_type[joint_label].append(req_screw_length)

                self.screw_assigned_lengths.append(assigned_len)
                self.inventory_counts[assigned_len] += 1

                if joint_label not in self.extrema_screws_by_type:
                    self.extrema_screws_by_type[joint_label] = {
                        "longest": {"line": hw_line, "length": req_screw_length},
                        "shortest": {"line": hw_line, "length": req_screw_length},
                    }
                else:
                    if (
                        req_screw_length
                        > self.extrema_screws_by_type[joint_label]["longest"]["length"]
                    ):
                        self.extrema_screws_by_type[joint_label]["longest"] = {
                            "line": hw_line,
                            "length": req_screw_length,
                        }
                    if (
                        req_screw_length
                        < self.extrema_screws_by_type[joint_label]["shortest"]["length"]
                    ):
                        self.extrema_screws_by_type[joint_label]["shortest"] = {
                            "line": hw_line,
                            "length": req_screw_length,
                        }

                success = True
            else:
                self.failed_screw_info.append({"line": hw_line, "type": joint_label})

        return success
