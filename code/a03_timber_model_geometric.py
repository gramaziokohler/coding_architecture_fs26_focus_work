from a03_rf_system import RFSystem
from compas.datastructures import Mesh
from compas.geometry import distance_point_point, Vector, Plane, Point
from compas_timber.connections import (
    LButtJoint,
    LMiterJoint,
    TButtJoint,
    TBirdsmouthJoint,
    XLapJoint,
    TLapJoint,
    JointTopology,
    ConnectionSolver,
)
from compas_timber.elements import Beam
from a03_preferred_face_tbutt_joint import PreferredFaceTButtJoint
from compas_timber.model import TimberModel
from compas_timber.fabrication import JackRafterCut
from timber_design.workflow import DirectRule



class GeometricTimberModelCreator:
    """
    Creates timber model by explicitly finding beam-beam intersections
    using actual beam geometry (width/height), not just centerline proximity.
    """

    def __init__(
        self,
        rf_system: RFSystem,
        beam_width: float = 0.08,
        beam_height: float = 0.10,
        inner_beam_width: float = None,
        inner_beam_height: float = None,
        base_beam_width: float = None,
        base_beam_height: float = None,
        arch_beam_width: float = None,
        arch_beam_height: float = None,
        max_distance: float = None,
        max_distance_L: float = None,
        max_distance_T: float = None,
        max_distance_T_arch_base: float = None,
        max_distance_T_inner_base: float = None,
        max_distance_X: float = None,
        z_height_threshold: float = None,
        sampling_points: int = 20,
        arch_plane_A=None,
        arch_plane_B=None,
        arch_split_axis: str = "x",
        arch_align_axis: str = "z",
        tbutt_mill_depth: float = 0.0,
        base_mill_depth: float = 0.0,
        preferred_face_vector=None,
        cutting_plane_inset_distance: float = 0.0,
        arch_A_inner_cross_beam_ref_side_index: int = None,
        arch_B_inner_cross_beam_ref_side_index: int = None,
    ):
        self.rf_system = rf_system
        self.timber_model = TimberModel()
        self.inner_beam_width = inner_beam_width if inner_beam_width is not None else beam_width
        self.inner_beam_height = inner_beam_height if inner_beam_height is not None else beam_height
        self.base_beam_width = base_beam_width if base_beam_width is not None else beam_width
        self.base_beam_height = base_beam_height if base_beam_height is not None else beam_height
        self.arch_beam_width = arch_beam_width if arch_beam_width is not None else beam_width
        self.arch_beam_height = arch_beam_height if arch_beam_height is not None else beam_height
        self.beam_radius = max(beam_width, beam_height) / 2.0
        base_dist = max_distance if max_distance is not None else self.beam_radius
        self.max_distance_L = max_distance_L if max_distance_L is not None else base_dist
        self.max_distance_T = max_distance_T if max_distance_T is not None else base_dist
        self.max_distance_T_arch_base = max_distance_T_arch_base if max_distance_T_arch_base is not None else self.max_distance_T
        self.max_distance_T_inner_base = max_distance_T_inner_base if max_distance_T_inner_base is not None else self.max_distance_T
        self.max_distance_X = max_distance_X if max_distance_X is not None else base_dist
        self.z_height_threshold = z_height_threshold
        self.sampling_points = sampling_points
        self.joining_errors = []
        self._rules = []
        self.trimmed_inner_beams = []
        self.trimmed_inner_beam_geometries = []
        self._topology_records = []
        self.cutting_planes_inner_beams = []
        self.jack_rafter_cut_features_inner_beams = []

        self.arch_plane_A = arch_plane_A
        self.arch_plane_B = arch_plane_B
        self.arch_split_axis = arch_split_axis
        self.arch_align_axis = arch_align_axis

        self.arch_plane_A_normal = self._vector_from_rhino_plane_normal(arch_plane_A)
        self.arch_plane_B_normal = self._vector_from_rhino_plane_normal(arch_plane_B)
        self.tbutt_mill_depth = tbutt_mill_depth
        self.base_mill_depth = base_mill_depth
        self.preferred_face_vector = preferred_face_vector
        self.cutting_plane_inset_distance = float(cutting_plane_inset_distance or 0.0)
        self.arch_A_inner_cross_beam_ref_side_index = arch_A_inner_cross_beam_ref_side_index
        self.arch_B_inner_cross_beam_ref_side_index = arch_B_inner_cross_beam_ref_side_index


    def _arch_reference_vector_for_centerline(self, centerline):
        """Choose the closest arch reference plane and return its normal vector."""

        if self.arch_plane_A is None and self.arch_plane_B is None:
            return None

        midpoint = centerline.midpoint

        distance_A = None
        distance_B = None

        if self.arch_plane_A is not None:
            distance_A = self._distance_point_to_rhino_plane(midpoint, self.arch_plane_A)

        if self.arch_plane_B is not None:
            distance_B = self._distance_point_to_rhino_plane(midpoint, self.arch_plane_B)

        if distance_A is not None and distance_B is not None:
            if distance_A <= distance_B:
                return self.arch_plane_A_normal
            else:
                return self.arch_plane_B_normal

        if distance_A is not None:
            return self.arch_plane_A_normal

        if distance_B is not None:
            return self.arch_plane_B_normal

        return None
        
    def create_timber_model(self, process_joinery: bool = True) -> TimberModel:
        """Main recipe for generating the model with geometric intersection detection."""
        print("=" * 60)
        print("GEOMETRIC TIMBER MODEL CREATOR")
        print("=" * 60)

        # Step 1: Create beams
        self._create_beams()
        print(f"Generated {len(list(self.timber_model.beams))} beams")

        # Step 2: Find intersections and detect actual topology
        self._find_intersections_with_topology()

        # Step 2b: Mark inner beams that will later be trimmed
        self._mark_trimmed_inner_beam_candidates()

        # Step 2c: Create preview cutting planes for those beams
        self._create_cutting_planes_for_trimmed_inner_beams()

        # Step 2d: Add JackRafterCut features to trimmed inner beams
        self._add_jack_rafter_cuts_to_trimmed_inner_beams()

        # Step 3: Apply rules
        self._apply_rules(process_joinery)

        # Step 4: Apply trimmed geometry — only needed when process_joinery=False.
        # When process_joinery=True, beam.geometry is already cut by process_joinery()
        # and re-applying the JackRafterCut would produce a double cut.
        if not process_joinery:
            self._apply_jack_rafter_cuts_to_trimmed_inner_beam_geometry()
        print("=" * 60)
        print("Model generation complete")
        print("=" * 60)

        return self.timber_model
    
    @staticmethod
    def _distance_point_to_rhino_plane(point, plane):
        """Absolute distance from a COMPAS point to a Rhino plane."""

        plane_origin = plane.Origin
        plane_normal = plane.Normal

        vx = point.x - plane_origin.X
        vy = point.y - plane_origin.Y
        vz = point.z - plane_origin.Z

        nx = plane_normal.X
        ny = plane_normal.Y
        nz = plane_normal.Z

        normal_length = (nx**2 + ny**2 + nz**2) ** 0.5

        if normal_length < 0.001:
            return None

        signed_distance = (vx * nx + vy * ny + vz * nz) / normal_length

        return abs(signed_distance)
    
    @staticmethod
    def _upright_normal(centerline):
        """Project global Z onto the plane perpendicular to the beam — gives a vertical cross-section."""
        from compas.geometry import Vector
        dx = centerline.end.x - centerline.start.x
        dy = centerline.end.y - centerline.start.y
        dz = centerline.end.z - centerline.start.z
        length = (dx**2 + dy**2 + dz**2) ** 0.5
        if length < 0.001:
            return Vector(0, 0, 1)
        dx /= length; dy /= length; dz /= length
        px = -dx * dz
        py = -dy * dz
        pz = 1.0 - dz * dz
        proj_len = (px**2 + py**2 + pz**2) ** 0.5
        if proj_len > 0.001:
            return Vector(px / proj_len, py / proj_len, pz / proj_len)
        return Vector(1, 0, 0)
    
    @staticmethod
    def _vector_from_rhino_plane_normal(plane):
        """Convert a Rhino.Geometry.Plane normal to a COMPAS Vector."""
        if plane is None:
            return None

        n = plane.Normal
        v = Vector(n.X, n.Y, n.Z)

        if v.length < 0.001:
            return None

        v.unitize()
        return v

    @staticmethod
    def _project_vector_perpendicular_to_centerline(centerline, reference_vector):
        """Project a reference vector onto the plane perpendicular to the beam axis.

        This gives a valid z_vector for Beam.from_centerline while keeping
        all beams aligned to one shared reference direction.
        """

        if reference_vector is None:
            return None

        xaxis = Vector.from_start_end(centerline.start, centerline.end)

        if xaxis.length < 0.001:
            return reference_vector

        xaxis.unitize()

        projected = reference_vector - xaxis * reference_vector.dot(xaxis)

        if projected.length < 0.001:
            # Fallback if reference vector is almost parallel to the beam.
            world_z = Vector(0, 0, 1)
            projected = world_z - xaxis * world_z.dot(xaxis)

        if projected.length < 0.001:
            projected = Vector(1, 0, 0)

        projected.unitize()
        return projected
    
    @staticmethod
    def _is_tbutt_like_joint(joint_type):
        """Return True for normal and preferred-face T-butt joints."""
        return joint_type in (TButtJoint, PreferredFaceTButtJoint)
    
    def _create_beams(self) -> None:
        """Convert every RF edge into a Beam."""
        mesh: Mesh = self.rf_system.mesh
        skipped_count = 0
        boundary_count = 0
        interior_count = 0

        for edge in mesh.edges():
            centerline = mesh.edge_attribute(edge, "centerline")
            normal = mesh.edge_attribute(edge, "normal")

            if centerline is None:
                skipped_count += 1
                continue

            if normal is None:
                normal = Vector(0, 0, 1)

            category = self._edge_category(edge)
            if category == "base":
                w, h = self.base_beam_width, self.base_beam_height
                normal = self._upright_normal(centerline)
                boundary_count += 1
            elif self._is_arch(category):
                w, h = self.arch_beam_width, self.arch_beam_height

                reference_vector = self._arch_reference_vector_for_centerline(centerline)

                if reference_vector is not None:
                    normal = self._project_vector_perpendicular_to_centerline(
                        centerline,
                        reference_vector
                    )

                # Rotate normal 90° around beam axis — cross product gives the perpendicular
                # in the cross-section plane, effectively swapping width and height faces.
                beam_axis = Vector.from_start_end(centerline.start, centerline.end)
                beam_axis.unitize()
                rotated = beam_axis.cross(normal)
                if rotated.length > 0.001:
                    rotated.unitize()
                    normal = rotated

                dA = self._distance_point_to_rhino_plane(centerline.midpoint, self.arch_plane_A) if self.arch_plane_A else None
                dB = self._distance_point_to_rhino_plane(centerline.midpoint, self.arch_plane_B) if self.arch_plane_B else None
                print(f"ARCH edge {edge}: distance to plane A={dA}, distance to plane B={dB}")                

                boundary_count += 1
            else:
                w, h = self.inner_beam_width, self.inner_beam_height
                interior_count += 1
            beam = Beam.from_centerline(centerline, width=w, height=h, z_vector=normal)
            beam.attributes["category"] = category
            beam.attributes["edge"] = edge
            self.timber_model.add_element(beam)

            mesh.edge_attribute(edge, "beam", beam)

        if skipped_count > 0:
            print(f"Skipped {skipped_count} edges with None centerlines")
        print(f"Beam categories: {interior_count} inner, {boundary_count} base/arch")

    @staticmethod
    def _is_arch(cat: str) -> bool:
        """Return True for any arch sub-category (arch, arch_A, arch_B)."""
        return cat in {"arch", "arch_A", "arch_B"}

    @staticmethod
    def _normalize_category(cat: str) -> str:
        """Collapse arch_A / arch_B → arch for category-filter set matching."""
        if cat in {"arch_A", "arch_B"}:
            return "arch"
        return cat

    def _arch_subcategory(self, centerline) -> str:
        """Return arch_A, arch_B, or arch based on which arch plane is closer."""
        if self.arch_plane_A is None and self.arch_plane_B is None:
            return "arch"

        midpoint = centerline.midpoint
        dA = self._distance_point_to_rhino_plane(midpoint, self.arch_plane_A) if self.arch_plane_A else None
        dB = self._distance_point_to_rhino_plane(midpoint, self.arch_plane_B) if self.arch_plane_B else None

        if dA is not None and dB is not None:
            return "arch_A" if dA <= dB else "arch_B"
        if dA is not None:
            return "arch_A"
        if dB is not None:
            return "arch_B"
        return "arch"

    def _edge_category(self, edge) -> str:
        """Determine beam category: inner, base, arch_A, or arch_B."""
        category = self.rf_system.mesh.edge_attribute(edge, "beam_category")
        if category is not None:
            return category

        # Fallback for meshes using old is_boundary True/False
        is_boundary = self.rf_system.mesh.edge_attribute(edge, "is_boundary")
        if is_boundary is not None:
            if not is_boundary:
                return "inner"
            # Boundary edge — distinguish base vs arch using Z height if available
            if self.z_height_threshold is not None:
                centerline = self.rf_system.mesh.edge_attribute(edge, "centerline")
                if centerline is not None:
                    midpoint_z = (centerline.start.z + centerline.end.z) / 2.0
                    if midpoint_z < self.z_height_threshold:
                        return "base"
                    return self._arch_subcategory(centerline)
            return "base"

        if self.rf_system.mesh.is_edge_on_boundary(edge):
            return "base"
        return "inner"

    def _find_intersections_with_topology(self) -> None:
        """
        Four-pass topology detection — each pass uses its own max_distance.
        Pass order: L → T(arch+base) → T → X.  A beam pair is only processed in
        the first pass that finds a non-UNKNOWN topology for it, preventing duplicates.
        """
        beams = list(self.timber_model.beams)
        solver = ConnectionSolver()
        self._topology_records = []

        print(f"\nChecking {len(beams)} beams for intersections...")
        print(f"max_distance  L={self.max_distance_L:.3f}  T={self.max_distance_T:.3f}  T(arch+base)={self.max_distance_T_arch_base:.3f}  T(inner+base)={self.max_distance_T_inner_base:.3f}  X={self.max_distance_X:.3f}")

        topology_counts = {
            JointTopology.TOPO_L: 0,
            JointTopology.TOPO_T: 0,
            JointTopology.TOPO_X: 0,
        }

        passes = [
            (JointTopology.TOPO_L,  self.max_distance_L,            None),
            (JointTopology.TOPO_T,  self.max_distance_T_arch_base,  {"arch", "base"}),
            (JointTopology.TOPO_T,  self.max_distance_T_inner_base, {"inner", "base"}),
            (JointTopology.TOPO_T,  self.max_distance_T,            None),
            (JointTopology.TOPO_X,  self.max_distance_X,            None),
        ]

        processed_pairs = set()

        for target_topo, max_dist, category_filter in passes:
            for i, beam_a in enumerate(beams):
                for j, beam_b in enumerate(beams):
                    if j <= i:
                        continue
                    pair = (i, j)
                    if pair in processed_pairs:
                        continue

                    if category_filter is not None:
                        cat_a = beam_a.attributes.get("category", "inner")
                        cat_b = beam_b.attributes.get("category", "inner")
                        norm_a = self._normalize_category(cat_a)
                        norm_b = self._normalize_category(cat_b)
                        if {norm_a, norm_b} != category_filter:
                            continue
                        processed_pairs.add(pair)
                        result = solver.find_topology(beam_a, beam_b, max_distance=max_dist)
                        if result.topology != JointTopology.TOPO_UNKNOWN:
                            topo_name = JointTopology.get_name(result.topology)
                            filter_label = "+".join(sorted(category_filter))
                            print(f"  [{filter_label}] pair({i},{j}) cat=({cat_a},{cat_b}) -> {topo_name}  (max_dist={max_dist:.3f})")
                    else:
                        result = solver.find_topology(beam_a, beam_b, max_distance=max_dist)

                    topology = result.topology
                    main_beam = result.beam_a
                    cross_beam = result.beam_b

                    if topology == JointTopology.TOPO_UNKNOWN:
                        continue

                    # Only claim this pair in the pass that matches its topology
                    if topology != target_topo:
                        continue

                    processed_pairs.add(pair)
                    topology_counts[topology] += 1

                    cat_main  = main_beam.attributes.get("category", "inner")  if main_beam  else None
                    cat_cross = cross_beam.attributes.get("category", "inner") if cross_beam else None

                    joint_type, beam_order = self._determine_joint_from_topology(
                        topology, main_beam, cross_beam, cat_main, cat_cross
                    )

                    # Store topology/joint information for later beam classification.
                    self._topology_records.append({
                        "topology": topology,
                        "joint_type": joint_type,
                        "main_beam": main_beam,
                        "cross_beam": cross_beam,
                        "beam_order": beam_order,
                        "max_distance": max_dist,
                    })

                    if joint_type and beam_order:
                        kwargs = {}
                        if joint_type in (TButtJoint, PreferredFaceTButtJoint):
                            is_base_joint = cat_main == "base" or cat_cross == "base"
                            is_arch_inner_joint = (
                                joint_type is PreferredFaceTButtJoint
                                and not is_base_joint
                                and (cat_main == "inner" or cat_cross == "inner")
                                and (self._is_arch(cat_main) or self._is_arch(cat_cross))
                            )
                            if is_base_joint and self.base_mill_depth:
                                kwargs["mill_depth"] = self.base_mill_depth
                            elif not is_base_joint and self.tbutt_mill_depth:
                                kwargs["mill_depth"] = self.tbutt_mill_depth
                            if is_arch_inner_joint:
                                arch_cat = cat_main if self._is_arch(cat_main) else cat_cross
                                if arch_cat == "arch_A" and self.arch_A_inner_cross_beam_ref_side_index is not None:
                                    kwargs["cross_beam_ref_side_index"] = self.arch_A_inner_cross_beam_ref_side_index
                                elif arch_cat == "arch_B" and self.arch_B_inner_cross_beam_ref_side_index is not None:
                                    kwargs["cross_beam_ref_side_index"] = self.arch_B_inner_cross_beam_ref_side_index
                            elif joint_type is PreferredFaceTButtJoint:
                                if self.preferred_face_vector is not None:
                                    kwargs["preferred_face_vector"] = self.preferred_face_vector
                        rule = DirectRule(joint_type, beam_order, max_distance=max_dist, **kwargs)
                        self._rules.append(rule)

        print("Topology detection results:")
        for topo, count in topology_counts.items():
            if count > 0:
                print(f"  {JointTopology.get_name(topo)}: {count}")
        print(f"Created {len(self._rules)} direct rules")

    def _determine_joint_from_topology(
        self, topology, main_beam, cross_beam, cat_main, cat_cross
    ):
        is_arch_main  = self._is_arch(cat_main)
        is_arch_cross = self._is_arch(cat_cross)

        if topology == JointTopology.TOPO_L:
            if (cat_main == "base" or is_arch_main) and (cat_cross == "base" or is_arch_cross):
                if (is_arch_main and cat_cross == "base") or (is_arch_cross and cat_main == "base"):
                    base_b = main_beam if cat_main == "base" else cross_beam
                    arch_b = cross_beam if cat_main == "base" else main_beam
                    return PreferredFaceTButtJoint, [arch_b, base_b]
                return LMiterJoint, [main_beam, cross_beam]
            return None, None

        elif topology == JointTopology.TOPO_T:
            has_base  = cat_main == "base"  or cat_cross == "base"
            has_inner = cat_main == "inner" or cat_cross == "inner"
            has_arch  = is_arch_main or is_arch_cross

            if has_base and has_inner:
                base_b  = main_beam  if cat_main == "base"  else cross_beam
                inner_b = cross_beam if cat_main == "base"  else main_beam
                return PreferredFaceTButtJoint, [inner_b, base_b]
            if has_base and has_arch:
                base_b = main_beam if cat_main == "base" else cross_beam
                arch_b = cross_beam if cat_main == "base" else main_beam
                return PreferredFaceTButtJoint, [arch_b, base_b]
            if has_inner and has_arch:
                inner_b = main_beam  if cat_main == "inner" else cross_beam
                arch_b  = cross_beam if cat_main == "inner" else main_beam
                return PreferredFaceTButtJoint, [inner_b, arch_b]
            return TButtJoint, [main_beam, cross_beam]

        elif topology == JointTopology.TOPO_X:
            if cat_main == "base" or is_arch_main:
                return XLapJoint, [main_beam, cross_beam]
            elif cat_cross == "base" or is_arch_cross:
                return XLapJoint, [cross_beam, main_beam]
            return XLapJoint, [main_beam, cross_beam]

        elif topology == JointTopology.TOPO_I:
            return None, None

        return None, None

    @staticmethod
    def _beam_axis_point_at_end(beam, end_name):
        """Return beam centerline start or end point."""
        line = getattr(beam, "centerline", None)

        if line is None:
            edge = beam.attributes.get("edge")
            return None

        if end_name == "start":
            return line.start
        return line.end

    @staticmethod
    def _closest_points_between_segments(line_a, line_b):
        """Return closest points and parameters on two finite line segments."""

        from compas.geometry import Point

        p1 = line_a.start
        q1 = line_a.end
        p2 = line_b.start
        q2 = line_b.end

        d1 = Vector.from_start_end(p1, q1)
        d2 = Vector.from_start_end(p2, q2)
        r = Vector.from_start_end(p2, p1)

        a = d1.dot(d1)
        e = d2.dot(d2)
        f = d2.dot(r)

        eps = 1e-9

        if a <= eps and e <= eps:
            return p1, p2, 0.0, 0.0

        if a <= eps:
            s = 0.0
            t = max(0.0, min(1.0, f / e))
        else:
            c = d1.dot(r)

            if e <= eps:
                t = 0.0
                s = max(0.0, min(1.0, -c / a))
            else:
                b = d1.dot(d2)
                denom = a * e - b * b

                if abs(denom) > eps:
                    s = max(0.0, min(1.0, (b * f - c * e) / denom))
                else:
                    s = 0.0

                tnom = b * s + f

                if tnom < 0.0:
                    t = 0.0
                    s = max(0.0, min(1.0, -c / a))
                elif tnom > e:
                    t = 1.0
                    s = max(0.0, min(1.0, (b - c) / a))
                else:
                    t = tnom / e

        cp1 = Point(
            p1.x + (q1.x - p1.x) * s,
            p1.y + (q1.y - p1.y) * s,
            p1.z + (q1.z - p1.z) * s,
        )

        cp2 = Point(
            p2.x + (q2.x - p2.x) * t,
            p2.y + (q2.y - p2.y) * t,
            p2.z + (q2.z - p2.z) * t,
        )

        return cp1, cp2, s, t

    @staticmethod
    def _beam_centerline(beam):
        """Safely get beam centerline."""
        line = getattr(beam, "centerline", None)
        if line is not None:
            return line
        return None

    def _mark_trimmed_inner_beam_candidates(self):
        """Tag inner beams that have a TButt-like joint at one end and an open other end.

        XLap joints are ignored for this classification.
        """

        self.trimmed_inner_beams = []

        end_tol = max(
            float(self.max_distance_L),
            float(self.max_distance_T),
            float(self.max_distance_T_arch_base),
            float(self.max_distance_T_inner_base),
            float(self.max_distance_X),
            float(self.beam_radius),
        )

        # Track only end joints.
        # Structure:
        # beam_id -> {"start": {"tbutt": 0, "other": 0}, "end": {"tbutt": 0, "other": 0}}
        end_status = {}

        for beam in self.timber_model.beams:
            if beam.attributes.get("category") != "inner":
                continue

            end_status[id(beam)] = {
                "start": {"tbutt": 0, "other": 0},
                "end": {"tbutt": 0, "other": 0},
            }

        for record in self._topology_records:
            joint_type = record.get("joint_type")
            topology = record.get("topology")

            # Ignore XLap completely for this step.
            if topology == JointTopology.TOPO_X or joint_type is XLapJoint:
                continue

            if joint_type is None:
                continue

            beam_a = record.get("main_beam")
            beam_b = record.get("cross_beam")

            if beam_a is None or beam_b is None:
                continue

            line_a = getattr(beam_a, "centerline", None)
            line_b = getattr(beam_b, "centerline", None)

            if line_a is None or line_b is None:
                continue

            joint_a, joint_b, _, _ = self._closest_points_between_segments(line_a, line_b)

            for beam, line, joint_point in (
                (beam_a, line_a, joint_a),
                (beam_b, line_b, joint_b),
            ):
                if id(beam) not in end_status:
                    continue

                d_start = distance_point_point(joint_point, line.start)
                d_end = distance_point_point(joint_point, line.end)

                end_name = None

                if d_start <= end_tol and d_start <= d_end:
                    end_name = "start"
                elif d_end <= end_tol:
                    end_name = "end"

                if end_name is None:
                    continue

                if self._is_tbutt_like_joint(joint_type):
                    end_status[id(beam)][end_name]["tbutt"] += 1
                else:
                    end_status[id(beam)][end_name]["other"] += 1

        for beam in self.timber_model.beams:
            if beam.attributes.get("category") != "inner":
                beam.attributes["trimmed_inner_candidate"] = False
                continue

            status = end_status.get(id(beam))
            if not status:
                beam.attributes["trimmed_inner_candidate"] = False
                continue

            start_has_tbutt = status["start"]["tbutt"] > 0
            start_has_any = status["start"]["tbutt"] > 0 or status["start"]["other"] > 0

            end_has_tbutt = status["end"]["tbutt"] > 0
            end_has_any = status["end"]["tbutt"] > 0 or status["end"]["other"] > 0

            candidate = (
                (start_has_tbutt and not end_has_any) or
                (end_has_tbutt and not start_has_any)
            )

            beam.attributes["trimmed_inner_candidate"] = candidate

            if candidate:
                self.trimmed_inner_beams.append(beam)

                print(
                    "TRIM CANDIDATE | edge={} | start_tbutt={} | start_any={} | end_tbutt={} | end_any={}".format(
                        beam.attributes.get("edge"),
                        start_has_tbutt,
                        start_has_any,
                        end_has_tbutt,
                        end_has_any,
                    )
                )

        print(
            "Detected {} trimmed inner beam candidates.".format(
                len(self.trimmed_inner_beams)
            )
        )

    @staticmethod
    def _beam_z_vector(beam):
        """Get a usable z-axis vector from a beam."""

        # Try common beam frame properties first.
        frame = getattr(beam, "frame", None)
        if frame is not None:
            zaxis = getattr(frame, "zaxis", None)
            if zaxis is not None and zaxis.length > 0.001:
                zaxis.unitize()
                return zaxis

        # Try common local frame / coordinate system names.
        for attr_name in ("local_frame", "base_frame", "reference_frame"):
            frame = getattr(beam, attr_name, None)
            if frame is not None:
                zaxis = getattr(frame, "zaxis", None)
                if zaxis is not None and zaxis.length > 0.001:
                    zaxis.unitize()
                    return zaxis

        # Fallback: use world Z.
        return Vector(0, 0, 1)        
    
    @staticmethod
    def _compas_plane_to_rhino_plane(plane):
        """Convert COMPAS Plane to Rhino.Geometry.Plane for Grasshopper preview."""
        try:
            import Rhino.Geometry as rg

            origin = rg.Point3d(
                plane.point.x,
                plane.point.y,
                plane.point.z,
            )

            normal = rg.Vector3d(
                plane.normal.x,
                plane.normal.y,
                plane.normal.z,
            )

            if normal.Length < 0.001:
                return None

            normal.Unitize()
            return rg.Plane(origin, normal)

        except Exception:
            return plane    
        
    def _open_end_name_for_trimmed_inner_beam(self, beam):
        """Return 'start' or 'end' for the open end of a trimmed inner beam candidate."""

        if not beam.attributes.get("trimmed_inner_candidate"):
            return None

        line = self._beam_centerline(beam)
        if line is None:
            return None

        end_tol = max(
            float(self.max_distance_L),
            float(self.max_distance_T),
            float(self.max_distance_T_arch_base),
            float(self.max_distance_X),
            float(self.beam_radius),
        )

        start_has_any = False
        end_has_any = False

        for record in self._topology_records:
            joint_type = record.get("joint_type")
            topology = record.get("topology")

            # Ignore XLap for open-end classification.
            if topology == JointTopology.TOPO_X or joint_type is XLapJoint:
                continue

            if joint_type is None:
                continue

            beam_a = record.get("main_beam")
            beam_b = record.get("cross_beam")

            if beam not in (beam_a, beam_b):
                continue

            other = beam_b if beam is beam_a else beam_a
            other_line = self._beam_centerline(other)

            if other_line is None:
                continue

            joint_self, _, _, _ = self._closest_points_between_segments(line, other_line)

            d_start = distance_point_point(joint_self, line.start)
            d_end = distance_point_point(joint_self, line.end)

            if d_start <= end_tol and d_start <= d_end:
                start_has_any = True
            elif d_end <= end_tol:
                end_has_any = True

        if not start_has_any:
            return "start"

        if not end_has_any:
            return "end"

        return None        
    
    def _create_cutting_planes_for_trimmed_inner_beams(self):
        """Create one cutting plane for each trimmed inner beam candidate.

        Rule:
        - For each trimmed inner beam, find all XLap joints involving it.
        - Use the XLap nearest to the open end.
        - The other inner beam in that XLap is the reference beam.
        - Cutting plane contains reference beam centerline and reference beam z-axis.
        """

        self.cutting_planes_inner_beams = []

        for beam in self.trimmed_inner_beams:
            beam_line = self._beam_centerline(beam)
            if beam_line is None:
                continue

            open_end_name = self._open_end_name_for_trimmed_inner_beam(beam)
            if open_end_name is None:
                print("Could not find open end for trimmed inner beam.")
                continue

            open_point = beam_line.start if open_end_name == "start" else beam_line.end

            nearest = None

            for record in self._topology_records:
                topology = record.get("topology")
                joint_type = record.get("joint_type")

                if topology != JointTopology.TOPO_X and joint_type is not XLapJoint:
                    continue

                beam_a = record.get("main_beam")
                beam_b = record.get("cross_beam")

                if beam not in (beam_a, beam_b):
                    continue

                reference_beam = beam_b if beam is beam_a else beam_a

                if reference_beam is None:
                    continue

                if reference_beam.attributes.get("category") != "inner":
                    continue

                reference_line = self._beam_centerline(reference_beam)
                if reference_line is None:
                    continue

                joint_on_beam, joint_on_reference, _, _ = self._closest_points_between_segments(
                    beam_line,
                    reference_line
                )

                distance_to_open = distance_point_point(joint_on_beam, open_point)

                if nearest is None or distance_to_open < nearest["distance"]:
                    nearest = {
                        "distance": distance_to_open,
                        "reference_beam": reference_beam,
                        "reference_line": reference_line,
                        "joint_on_reference": joint_on_reference,
                        "joint_on_beam": joint_on_beam,
                    }

            if nearest is None:
                print("No XLap reference beam found for trimmed inner beam.")
                beam.attributes["inner_cutting_plane"] = None
                continue

            beam_length = distance_point_point(beam_line.start, beam_line.end)
            joint_to_open_end = nearest["distance"]
            connected_point = beam_line.end if open_end_name == "start" else beam_line.start
            joint_to_connected_end = distance_point_point(nearest["joint_on_beam"], connected_point)

            n_xlaps = sum(
                1 for r in self._topology_records
                if r.get("topology") == JointTopology.TOPO_X
                and beam in (r.get("main_beam"), r.get("cross_beam"))
                and (r.get("main_beam") if beam is r.get("cross_beam") else r.get("cross_beam")) is not None
                and (r.get("main_beam") if beam is r.get("cross_beam") else r.get("cross_beam")).attributes.get("category") == "inner"
            )

            end_tol = max(
                float(self.max_distance_L),
                float(self.max_distance_T),
                float(self.max_distance_T_arch_base),
                float(self.max_distance_T_inner_base),
                float(self.max_distance_X),
                float(self.beam_radius),
            )

            beam_edge = beam.attributes.get("edge", "?")
            ref_edge = nearest["reference_beam"].attributes.get("edge", "?")
            print(
                "TRIM | edge={} | ref_edge={} | open_end={} | beam_len={:.3f} | xlap_dist_to_open={:.3f} | xlap_dist_to_connected={:.3f} | n_xlaps={} | skip={}".format(
                    beam_edge,
                    ref_edge,
                    open_end_name,
                    beam_length,
                    joint_to_open_end,
                    joint_to_connected_end,
                    n_xlaps,
                    joint_to_open_end < end_tol,
                )
            )

            if joint_to_open_end < end_tol:
                print("  -> Skipping JackRafterCut: XLap too close to open end, would conflict with TButtJoint.")
                beam.attributes["inner_cutting_plane"] = None
                continue

            reference_beam = nearest["reference_beam"]
            reference_line = nearest["reference_line"]
            reference_z = self._beam_z_vector(reference_beam)

            reference_axis = Vector.from_start_end(reference_line.start, reference_line.end)

            if reference_axis.length < 0.001:
                continue

            reference_axis.unitize()

            if reference_z.length < 0.001:
                reference_z = Vector(0, 0, 1)

            reference_z.unitize()

            # Plane contains:
            # 1. reference beam centerline
            # 2. reference beam z-axis
            # Therefore plane normal = centerline direction x z-axis
            plane_normal = reference_axis.cross(reference_z)

            if plane_normal.length < 0.001:
                # Fallback if z-axis is accidentally parallel to centerline.
                plane_normal = reference_axis.cross(Vector(0, 0, 1))

            if plane_normal.length < 0.001:
                plane_normal = reference_axis.cross(Vector(1, 0, 0))

            if plane_normal.length < 0.001:
                print("Could not create cutting plane normal.")
                continue

            plane_normal.unitize()

            # Use the XLap point on the trimmed beam as the plane origin.
            # Using joint_on_reference (reference beam centerline) causes a
            # 5-10cm offset because the two centerlines are not co-planar.
            plane_origin = nearest["joint_on_beam"]

            # Orient the plane normal so positive inset moves toward the open end
            # of the trimmed inner beam.
            direction_to_open = Vector.from_start_end(plane_origin, open_point)

            dot = 0.0
            if direction_to_open.length > 0.001:
                direction_to_open.unitize()
                dot = plane_normal.dot(direction_to_open)
                if dot < 0:
                    plane_normal *= -1
                    dot = -dot

            print("  -> dot(normal, to_open)={:.3f} | inset={:.3f}".format(dot, float(self.cutting_plane_inset_distance or 0.0)))

            # Move plane along its oriented normal.
            # Positive distance = toward open end.
            # Negative distance = opposite direction.
            inset = float(self.cutting_plane_inset_distance or 0.0)

            inset_origin = Point(
                plane_origin.x + plane_normal.x * inset,
                plane_origin.y + plane_normal.y * inset,
                plane_origin.z + plane_normal.z * inset,
            )

            compas_plane = Plane(inset_origin, plane_normal)
            rhino_plane = self._compas_plane_to_rhino_plane(compas_plane)

            # Rhino plane for GH preview
            beam.attributes["inner_cutting_plane"] = rhino_plane

            # COMPAS plane for JackRafterCut
            beam.attributes["inner_cutting_compas_plane"] = compas_plane

            beam.attributes["inner_cutting_plane_base_point"] = plane_origin
            beam.attributes["inner_cutting_plane_inset_point"] = inset_origin
            beam.attributes["inner_cutting_plane_normal"] = plane_normal
            beam.attributes["inner_cutting_reference_beam"] = reference_beam
            beam.attributes["inner_cutting_open_end"] = open_end_name
            beam.attributes["inner_cutting_inset_distance"] = inset
            print(
                "Cutting plane for trimmed inner beam: open_end={}, inset={:.3f}".format(
                    open_end_name,
                    inset,
                )
            )

            self.cutting_planes_inner_beams.append(rhino_plane)

        print(
            "Created {} cutting planes for trimmed inner beams.".format(
                len(self.cutting_planes_inner_beams)
            )
        )    

    def _add_jack_rafter_cuts_to_trimmed_inner_beams(self):
        """Add JackRafterCut features to trimmed inner beams.

        The cutting plane is the finalized inset COMPAS plane.
        The feature is added to the beam so the timber model processes it.
        """

        self.jack_rafter_cut_features_inner_beams = []

        success = 0
        failed = 0

        for beam in self.trimmed_inner_beams:
            compas_plane = beam.attributes.get("inner_cutting_compas_plane")

            if compas_plane is None:
                failed += 1
                print("No COMPAS cutting plane found for trimmed inner beam.")
                continue

            feature = None
            last_error = None

            # Try different reference sides. Depending on beam orientation,
            # one ref_side_index may be invalid while another works.
            for ref_side_index in range(4):
                try:
                    feature = JackRafterCut.from_plane_and_beam(
                        compas_plane,
                        beam,
                        ref_side_index=ref_side_index
                    )
                    break
                except Exception as e:
                    last_error = e
                    feature = None

            if feature is None:
                failed += 1
                print(
                    "Could not create JackRafterCut for trimmed inner beam: {}".format(
                        last_error
                    )
                )
                continue

            # Add the feature to the beam. Different compas_timber versions
            # expose this differently, so try the common options.
            added = False

            for method_name in ("add_features", "add_feature"):
                method = getattr(beam, method_name, None)
                if method is None:
                    continue

                try:
                    if method_name == "add_features":
                        method([feature])
                    else:
                        method(feature)
                    added = True
                    break
                except Exception as e:
                    print("Could not use beam.{}: {}".format(method_name, e))

            if not added:
                # Fallback: append to features list if it exists.
                try:
                    features = getattr(beam, "features", None)
                    if features is not None:
                        features.append(feature)
                        added = True
                except Exception as e:
                    print("Could not append feature to beam.features: {}".format(e))

            if not added:
                failed += 1
                print("Could not add JackRafterCut feature to beam.")
                continue

            beam.attributes["inner_jack_rafter_cut"] = feature
            self.jack_rafter_cut_features_inner_beams.append(feature)
            success += 1

        print(
            "JackRafterCut features for trimmed inner beams: success={}, failed={}".format(
                success,
                failed
            )
        )

    def _apply_jack_rafter_cuts_to_trimmed_inner_beam_geometry(self):
        """Directly apply JackRafterCut features to beam geometry for GH preview."""

        self.trimmed_inner_beam_geometries = []

        success = 0
        failed = 0

        for beam in self.trimmed_inner_beams:
            feature = beam.attributes.get("inner_jack_rafter_cut")

            if feature is None:
                failed += 1
                print("No JackRafterCut feature stored on trimmed inner beam.")
                continue

            try:
                geometry = beam.geometry
                trimmed_geometry = feature.apply(geometry, beam)
            except Exception as e:
                failed += 1
                print("Could not apply JackRafterCut to beam geometry: {}".format(e))
                continue

            beam.attributes["trimmed_geometry"] = trimmed_geometry
            beam.attributes["is_trimmed_inner_geometry"] = True
            self.trimmed_inner_beam_geometries.append(trimmed_geometry)
            success += 1

        print(
            "Direct JackRafterCut geometry application: success={}, failed={}".format(
                success,
                failed
            )
        )        

    def _apply_rules(self, process_joinery: bool) -> None:
        """Apply the direct rules we created."""
        from timber_design.workflow import JointRuleSolver

        self.joining_errors = []
        solver = JointRuleSolver(self._rules)

        inner_beams = [b for b in self.timber_model.beams if b.attributes.get("category") == "inner"]
        base_beams  = [b for b in self.timber_model.beams if b.attributes.get("category") == "base"]
        arch_beams  = [b for b in self.timber_model.beams if self._is_arch(b.attributes.get("category", ""))]
        arch_A_beams = [b for b in arch_beams if b.attributes.get("category") == "arch_A"]
        arch_B_beams = [b for b in arch_beams if b.attributes.get("category") == "arch_B"]
        print(f"Before joint solving: {len(inner_beams)} inner, {len(base_beams)} base, {len(arch_beams)} arch ({len(arch_A_beams)} arch_A, {len(arch_B_beams)} arch_B)")

        self.joining_errors, unjoined_clusters = solver.apply_rules_to_model(
            self.timber_model
        )

        print(
            f"Found {len(self.joining_errors)} joining errors and {len(unjoined_clusters)} unjoined clusters"
        )

        # Count joints by type
        joint_counts = {}
        joints = (
            getattr(self.timber_model, "joints", None)
            or getattr(self.timber_model, "interactions", None)
            or []
        )

        for joint in joints:
            joint_type = type(joint).__name__
            joint_counts[joint_type] = joint_counts.get(joint_type, 0) + 1

        if joint_counts:
            print("Joints created:")
            for joint_type, count in joint_counts.items():
                print(f"  {joint_type}: {count}")
        else:
            print("WARNING: No joints were created!")

        if self.joining_errors:
            print("Joining errors:")
            for error in self.joining_errors[:10]:  # Show first 10
                print(f"  - {error}")

        if process_joinery:
            print("Processing geometry (cutting joints)...")
            self.timber_model.process_joinery()
