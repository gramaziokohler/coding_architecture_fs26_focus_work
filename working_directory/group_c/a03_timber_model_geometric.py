from a03_rf_system import RFSystem
from compas.datastructures import Mesh
from compas.geometry import distance_point_point
from compas_timber.connections import LMiterJoint, TButtJoint, XLapJoint, JointTopology, ConnectionSolver
from compas_timber.elements import Beam
from compas_timber.model import TimberModel
from timber_design.workflow import DirectRule


class GeometricTimberModelCreator:
    """
    Creates timber model by explicitly finding beam-beam intersections
    using actual beam geometry (width/height), not just centerline proximity.
    """

    def __init__(self, rf_system: RFSystem,
                 beam_width: float = 0.08, beam_height: float = 0.10,
                 inner_beam_width: float = None, inner_beam_height: float = None,
                 boundary_beam_width: float = None, boundary_beam_height: float = None,
                 sampling_points: int = 20):
        self.rf_system = rf_system
        self.timber_model = TimberModel()
        self.inner_beam_width = inner_beam_width if inner_beam_width is not None else beam_width
        self.inner_beam_height = inner_beam_height if inner_beam_height is not None else beam_height
        self.boundary_beam_width = boundary_beam_width if boundary_beam_width is not None else beam_width
        self.boundary_beam_height = boundary_beam_height if boundary_beam_height is not None else beam_height
        self.beam_radius = max(beam_width, beam_height) / 2.0
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
            if category == "boundary":
                w, h = self.boundary_beam_width, self.boundary_beam_height
            else:
                w, h = self.inner_beam_width, self.inner_beam_height
            beam = Beam.from_centerline(centerline, width=w, height=h, z_vector=normal)
            beam.attributes["category"] = category
            beam.attributes["edge"] = edge  # Store edge reference
            self.timber_model.add_element(beam)

            mesh.edge_attribute(edge, "beam", beam)
            
            if category == "boundary":
                boundary_count += 1
            else:
                interior_count += 1
        
        if skipped_count > 0:
            print(f"Skipped {skipped_count} edges with None centerlines")
        print(f"Beam categories: {boundary_count} boundary, {interior_count} interior")

    def _edge_category(self, edge) -> str:
        """Determine if edge is boundary or interior."""
        is_boundary = self.rf_system.mesh.edge_attribute(edge, "is_boundary")
        if is_boundary is not None:
            return "boundary" if is_boundary else "interior"
        
        if self.rf_system.mesh.is_edge_on_boundary(edge):
            return "boundary"
        return "interior"

    def _find_intersections_with_topology(self) -> None:
        """
        Use ConnectionSolver to detect actual beam topology, then create appropriate DirectRules.
        """
        beams = list(self.timber_model.beams)
        solver = ConnectionSolver()
        max_distance = self.beam_radius * 2
        
        print(f"\nChecking {len(beams)} beams for intersections...")
        print(f"Using max_distance: {max_distance:.3f}")
        
        topology_counts = {
            JointTopology.TOPO_L: 0,
            JointTopology.TOPO_T: 0,
            JointTopology.TOPO_X: 0,
            JointTopology.TOPO_I: 0,
            JointTopology.TOPO_UNKNOWN: 0
        }
        
        for i, beam_a in enumerate(beams):
            for j, beam_b in enumerate(beams):
                if j <= i:
                    continue
                
                # Detect actual topology using ConnectionSolver
                result = solver.find_topology(
                    beam_a, beam_b,
                    max_distance=max_distance
                )
                
                # Extract topology and beams from result
                topology = result.topology
                main_beam = result.beam_a
                cross_beam = result.beam_b
                
                if topology == JointTopology.TOPO_UNKNOWN:
                    continue
                
                topology_counts[topology] += 1
                
                # Get categories
                cat_main = main_beam.attributes.get("category", "interior") if main_beam else None
                cat_cross = cross_beam.attributes.get("category", "interior") if cross_beam else None
                
                # Determine joint type based on topology and categories
                joint_type, beam_order = self._determine_joint_from_topology(
                    topology, main_beam, cross_beam, cat_main, cat_cross
                )
                
                if joint_type and beam_order:
                    rule = DirectRule(joint_type, beam_order, max_distance=max_distance)
                    self._rules.append(rule)
        
        print(f"Topology detection results:")
        for topo, count in topology_counts.items():
            if count > 0:
                print(f"  {JointTopology.get_name(topo)}: {count}")
        print(f"Created {len(self._rules)} direct rules")
    
    def _determine_joint_from_topology(self, topology, main_beam, cross_beam, cat_main, cat_cross):
        """
        Determine joint type based on detected topology and beam categories.
        
        IMPORTANT:
        - LMiterJoint requires TOPO_L (only for boundary-boundary)
        - TButtJoint requires TOPO_T with [main_beam, cross_beam] order
        - XLapJoint requires TOPO_X
        
        For TOPO_T: ConnectionSolver returns main_beam=continuous, cross_beam=ending
        TButtJoint expects [main_beam, cross_beam] in that order.
        """
        # TOPO_L: Both beams meet at ends
        if topology == JointTopology.TOPO_L:
            # LMiterJoint ONLY for boundary-boundary L-joints
            if cat_main == "boundary" and cat_cross == "boundary":
                return LMiterJoint, [main_beam, cross_beam]
            # For interior L-joints, use TButtJoint (they're actually T-shaped in practice)
            # Skip them to avoid errors
            return None, None
        
        # TOPO_T: One beam ends on the other
        # ConnectionSolver gives us: main_beam (continuous), cross_beam (ending)
        # TButtJoint expects: [main_beam, cross_beam] in that exact order
        elif topology == JointTopology.TOPO_T:
            # Always use the order from ConnectionSolver: [main_beam, cross_beam]
            return TButtJoint, [main_beam, cross_beam]
        
        # TOPO_X: Both beams cross -> XLapJoint
        elif topology == JointTopology.TOPO_X:
            # Put boundary beam first if there is one (maintains priority)
            if cat_main == "boundary":
                return XLapJoint, [main_beam, cross_beam]
            elif cat_cross == "boundary":
                return XLapJoint, [cross_beam, main_beam]
            return XLapJoint, [main_beam, cross_beam]
        
        # TOPO_I: Parallel end-to-end -> skip
        elif topology == JointTopology.TOPO_I:
            return None, None
        
        return None, None

    def _apply_rules(self, process_joinery: bool) -> None:
        """Apply the direct rules we created."""
        from timber_design.workflow import JointRuleSolver
        
        self.joining_errors = []
        solver = JointRuleSolver(self._rules)
        
        boundary_beams = [b for b in self.timber_model.beams if b.attributes.get("category") == "boundary"]
        interior_beams = [b for b in self.timber_model.beams if b.attributes.get("category") == "interior"]
        print(f"Before joint solving: {len(boundary_beams)} boundary beams, {len(interior_beams)} interior beams")

        self.joining_errors, unjoined_clusters = solver.apply_rules_to_model(self.timber_model)

        print(f"Found {len(self.joining_errors)} joining errors and {len(unjoined_clusters)} unjoined clusters")
        
        # Count joints by type
        joint_counts = {}
        joints = getattr(self.timber_model, 'joints', None) or getattr(self.timber_model, 'interactions', None) or []
        
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