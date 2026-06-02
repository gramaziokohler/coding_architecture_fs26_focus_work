from a03_rf_system import RFSystem
from compas.datastructures import Mesh
from compas.geometry import distance_point_point
from compas_timber.connections import (
    LMiterJoint,
    TButtJoint,
    TBirdsmouthJoint,
    XLapJoint,
    TLapJoint,
    JointTopology,
    ConnectionSolver,
)
from compas_timber.elements import Beam
from compas_timber.model import TimberModel
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
        max_distance_X: float = None,
        z_height_threshold: float = None,
        sampling_points: int = 20,
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
        self.max_distance_X = max_distance_X if max_distance_X is not None else base_dist
        self.z_height_threshold = z_height_threshold
        self.sampling_points = sampling_points
        self.joining_errors = []
        self._rules = []

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

        # Step 3: Apply rules
        self._apply_rules(process_joinery)
        print("=" * 60)
        print("Model generation complete")
        print("=" * 60)

        return self.timber_model

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
                from compas.geometry import Vector
                normal = Vector(0, 0, 1)

            category = self._edge_category(edge)
            if category == "base":
                w, h = self.base_beam_width, self.base_beam_height
                normal = self._upright_normal(centerline)
                boundary_count += 1
            elif category == "arch":
                w, h = self.arch_beam_width, self.arch_beam_height
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

    def _edge_category(self, edge) -> str:
        """Determine beam category: inner, base, or arch."""
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
                    return "base" if midpoint_z < self.z_height_threshold else "arch"
            return "base"

        if self.rf_system.mesh.is_edge_on_boundary(edge):
            return "base"
        return "inner"

    def _find_intersections_with_topology(self) -> None:
        """
        Three-pass topology detection — each pass uses its own max_distance.
        Pass order: L → T → X.  A beam pair is only processed in the first pass
        that finds a non-UNKNOWN topology for it, preventing duplicates.
        """
        beams = list(self.timber_model.beams)
        solver = ConnectionSolver()

        print(f"\nChecking {len(beams)} beams for intersections...")
        print(f"max_distance  L={self.max_distance_L:.3f}  T={self.max_distance_T:.3f}  X={self.max_distance_X:.3f}")

        topology_counts = {
            JointTopology.TOPO_L: 0,
            JointTopology.TOPO_T: 0,
            JointTopology.TOPO_X: 0,
        }

        passes = [
            (JointTopology.TOPO_L, self.max_distance_L),
            (JointTopology.TOPO_T, self.max_distance_T),
            (JointTopology.TOPO_X, self.max_distance_X),
        ]

        processed_pairs = set()

        for target_topo, max_dist in passes:
            for i, beam_a in enumerate(beams):
                for j, beam_b in enumerate(beams):
                    if j <= i:
                        continue
                    pair = (i, j)
                    if pair in processed_pairs:
                        continue

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

                    if joint_type and beam_order:
                        rule = DirectRule(joint_type, beam_order, max_distance=max_dist)
                        self._rules.append(rule)

        print("Topology detection results:")
        for topo, count in topology_counts.items():
            if count > 0:
                print(f"  {JointTopology.get_name(topo)}: {count}")
        print(f"Created {len(self._rules)} direct rules")

    def _determine_joint_from_topology(
        self, topology, main_beam, cross_beam, cat_main, cat_cross
    ):
        outer = {"base", "arch"}

        if topology == JointTopology.TOPO_L:
            if cat_main in outer and cat_cross in outer:
                return LMiterJoint, [main_beam, cross_beam]
            return None, None

        elif topology == JointTopology.TOPO_T:
            if "base" in (cat_main, cat_cross) and "inner" in (cat_main, cat_cross):
                base_b  = main_beam  if cat_main == "base" else cross_beam
                inner_b = cross_beam if cat_main == "base" else main_beam
                return TBirdsmouthJoint, [inner_b, base_b]
            return TButtJoint, [main_beam, cross_beam]

        elif topology == JointTopology.TOPO_X:
            if cat_main in outer:
                return XLapJoint, [main_beam, cross_beam]
            elif cat_cross in outer:
                return XLapJoint, [cross_beam, main_beam]
            return XLapJoint, [main_beam, cross_beam]

        elif topology == JointTopology.TOPO_I:
            return None, None

        return None, None

    def _apply_rules(self, process_joinery: bool) -> None:
        """Apply the direct rules we created."""
        from timber_design.workflow import JointRuleSolver

        self.joining_errors = []
        solver = JointRuleSolver(self._rules)

        inner_beams = [b for b in self.timber_model.beams if b.attributes.get("category") == "inner"]
        base_beams = [b for b in self.timber_model.beams if b.attributes.get("category") == "base"]
        arch_beams = [b for b in self.timber_model.beams if b.attributes.get("category") == "arch"]
        print(f"Before joint solving: {len(inner_beams)} inner, {len(base_beams)} base, {len(arch_beams)} arch beams")

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
