import math
from compas.geometry import (
    Point,
    Vector,
    Line,
    intersection_line_line,
    intersection_line_plane,
    distance_point_point,
)
from compas_timber.fabrication import Drilling
from compas_timber.connections import (
    LMiterJoint,
    TButtJoint,
    TLapJoint,
    XLapJoint,
)


class DrillingProcessor:
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

        self.inventory_counts = {100: 0, 130: 0, 150: 0}
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

        self.inventory_counts = {100: 0, 130: 0, 150: 0}
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
                self._apply_tbutt_drilling(joint)

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
        log.append("            PROCUREMENT & DRILLING SUMMARY                     ")
        log.append("================================================================")
        log.append(
            f"Unique Joints Processed Geometry: {len(self.processed_beam_pairs)}"
        )
        log.append(f"Lap Joint : {llap_joints_count} ( 2x 130mm screws/joint)")
        log.append(f"Screw Foundation  : 20 ( 4x Separate Foundation screws/joint)")
        log.append("----------------------------------------------------------------")

        # --- NEW AGGREGATION BLOCK FOR T-BUTTS ---
        summary_counts = {}
        summary_lengths = {}

        for j_type, count in self.hardware_screws_by_type.items():
            if count == 0:
                continue

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
                log.append(
                    f"  -> Unmodeled Screws : {screws} ({count} joints estimated)\n"
                )

        log.append("----------------------------------------------------------------")
        log.append("                    INVENTORY TO PROCURE                        ")
        log.append("----------------------------------------------------------------")

        color_map = {100: "GREEN", 130: "BLUE", 150: "ORANGE"}

        for length in [100, 130, 150]:
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

    # Standard screw lengths (m), longest first.
    STANDARD_LENGTHS = (0.150, 0.130, 0.100)
    # Candidate out-of-plane tilt angles (deg); the search is capped at target_tilt.
    TILT_DEGREES = (0, 5, 10, 15, 20, 25, 30, 35, 40, 45)

    def _apply_tbutt_drilling(self, joint):
        """Two screws per T-Butt along the abutting beam, kept clear of other beams.

        Each screw is driven along the main beam axis (head on the cross beam's outer
        face, tip anchored inside the main beam, cross beam pre-drilled). If the
        straight driver path is blocked, the screw tilts out of the frame plane —
        entering near the open edge — taking the largest standoff tilt up to
        ``target_tilt`` that frees the required driver clearance while the tip stays
        inside the main beam (the minimal tilt clears but only grazes the neighbour).
        Joints that cannot be solved within budget are flagged, not faked.
        """
        abut_beam = joint.main_beam   # abutting beam: its end sits at the joint
        cont_beam = joint.cross_beam  # through beam: the one we drill
        if abut_beam is None or cont_beam is None:
            return

        # Joint location: midpoint of the closest approach of the two centerlines.
        res = intersection_line_line(abut_beam.centerline, cont_beam.centerline)
        if not res or res[0] is None:
            return
        pa, pb = Point(*res[0]), Point(*res[1])
        joint_pt = Point((pa.x + pb.x) / 2.0, (pa.y + pb.y) / 2.0, (pa.z + pb.z) / 2.0)

        # Screw axis = main beam centerline, pointing into the main beam body.
        axis = abut_beam.centerline.direction.copy()
        if axis.dot(Vector.from_start_end(joint_pt, abut_beam.centerline.midpoint)) < 0:
            axis.scale(-1)
        axis.unitize()

        # Two screws side by side along the through beam (the long axis of the face).
        offset_dir = cont_beam.centerline.direction.copy()
        offset_dir = offset_dir - axis * offset_dir.dot(axis)
        if offset_dir.length < 1e-6:
            offset_dir = abut_beam.frame.yaxis.copy()
        offset_dir.unitize()
        offset_vec = offset_dir * (self.screw_spacing / 2.0)

        # Out-of-plane direction (normal to the local frame plane): the tilt / edge axis.
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

        # Escalation: a clean parallel screw if it clears, otherwise the largest
        # standoff tilt up to the target (a minimal tilt only grazes the neighbour).
        tilt_order = [0] + sorted(
            (a for a in self.TILT_DEGREES if 0 < a <= self.target_tilt), reverse=True
        )
        chosen = None
        for deg in tilt_order:
            theta = math.radians(deg)
            for d in ((0.0,) if deg == 0 else (1.0, -1.0)):
                screw_dir = axis * math.cos(theta) + n * (d * math.sin(theta))
                screw_dir.unitize()
                # Enter near the -d*n edge so tilting toward +d*n stays inside the beam.
                slide = -d * edge_slide
                heads = [
                    self._face_entry_point(
                        joint_pt + offset_vec * sign + n * slide, screw_dir, entry_face
                    )
                    for sign in (1.0, -1.0)
                ]
                if any(h is None for h in heads):
                    continue
                # The heads must land on the actual cross beam face, not past its edge.
                if not all(self._point_in_beam(h, cont_beam, -0.003) for h in heads):
                    continue
                # Driver clearance: probe outwards from each head must miss every beam.
                tool_dir = screw_dir * -1.0
                if not all(
                    self._probe_clear(h, tool_dir, others, self.clearance) for h in heads
                ):
                    continue
                # Longest screw whose tip (both screws) stays inside the main beam.
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
            # No feasible screw within budget: flag both screws, drill nothing.
            tool_dir = axis * -1.0
            for sign in (1.0, -1.0):
                base = joint_pt + offset_vec * sign
                head = self._face_entry_point(base, axis, entry_face) or base
                probe = Line(head, head + tool_dir * self.clearance)
                self.clearance_lines.append(probe)
                self.failed_screw_info.append(
                    {"line": probe, "type": "TButt: no 170mm clearance"}
                )
            return

        screw_dir, heads, length = chosen
        tool_dir = screw_dir * -1.0
        hw_lines = [Line(h, h + screw_dir * length) for h in heads]
        for h in heads:
            self.clearance_lines.append(Line(h, h + tool_dir * self.clearance))
        self._generate_features(hw_lines, [cont_beam], "TButtJoint", length)

    def _entry_face(self, beam, axis):
        """Side face whose outward normal most opposes ``axis`` (the head-side face)."""
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
        """Distance from the beam centerline to its cross-section edge along
        ``direction`` (which must be ~perpendicular to the beam axis)."""
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

        # PHYSICAL CAP
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
        else:
            assigned_len = 150

        def store_web_feature(beam, line):
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
