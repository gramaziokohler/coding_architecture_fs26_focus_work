from a03_rf_system import RFSystem
from compas.datastructures import Mesh
from compas_timber.connections import JointTopology
from compas_timber.connections import LMiterJoint
from compas_timber.connections import TBirdsmouthJoint
from compas_timber.connections import TButtJoint
from compas_timber.connections import TLapJoint
from compas_timber.connections import TStepJoint
from compas_timber.connections import XLapJoint
from compas_timber.elements import Beam
from compas_timber.model import TimberModel
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule
from timber_design.workflow import JointRuleSolver
from timber_design.workflow import TopologyRule


class TimberModelCreator:
    """
    A helper class to create a Timber Model from an instance of `RFSystem` class.

    This class demonstrates the three main steps of computational timber design:
    1. INPUT: Converting abstract centerlines (geometric lines extracted from an RFSystem's mesh) into physical objects (Beams).
    2. RULES: Defining how these objects should connect where they intersect (Joints).
    3. SOLVING: Calculating the geometry of those connections (Processing).
    """

    def __init__(self, rf_system: RFSystem,
                 beam_width: float = 0.08, beam_height: float = 0.10,
                 inner_beam_width: float = None, inner_beam_height: float = None,
                 boundary_beam_width: float = None, boundary_beam_height: float = None,
                 tolerance: float = 0.02):
        self.rf_system = rf_system
        self.timber_model = TimberModel()
        # Per-category dimensions — fall back to the shared beam_width/height if not specified
        self.inner_beam_width = inner_beam_width if inner_beam_width is not None else beam_width
        self.inner_beam_height = inner_beam_height if inner_beam_height is not None else beam_height
        self.boundary_beam_width = boundary_beam_width if boundary_beam_width is not None else beam_width
        self.boundary_beam_height = boundary_beam_height if boundary_beam_height is not None else beam_height
        self.joining_errors = []

        # Rule solver settings.
        self.tolerance = tolerance  # The maximum distance between lines to consider them as "touching"
        self._rules = []

    def create_timber_model(self, process_joinery: bool = True) -> TimberModel:
        """
        The main recipe for generating the model.
        """
        print(f"--- Starting Timber Model Generation ---")

        # Step 1: Geometry
        self._create_beams()
        print(f"Generated {len(list(self.timber_model.beams))} beams.")

        # Step 2: Definitions
        self._rules = []  # Reset rules
        
        # Check if mesh has next_edge/prev_edge attributes (RF system topology)
        has_rf_topology = False
        for edge in list(self.rf_system.mesh.edges())[:1]:  # Check first edge
            if self.rf_system.mesh.edge_attribute(edge, "next_edge") is not None:
                has_rf_topology = True
                break
        
        # ALWAYS use category-based rules - they work better with multiple tolerances
        print("Using category-based rules with multiple tolerance passes")
        self._add_rules()
        
        # Optionally add direct rules if RF topology exists (currently disabled)
        # if has_rf_topology:
        #     print("Also adding direct rules from RF topology")
        #     self._add_rules_direct()

        # Step 3: Calculation
        self._apply_rules(process_joinery)
        print("Model generation complete.")

        return self.timber_model

    # --------------------------------------------------------------------------
    # Beam creation
    # --------------------------------------------------------------------------

    def _create_beams(self) -> None:
        """
        Convert every RF edge into a `Beam` and store the beam back on the edge.
        Skips edges with None centerlines (deleted/invalid edges).
        """
        mesh: Mesh = self.rf_system.mesh
        skipped_count = 0
        boundary_count = 0
        interior_count = 0
        none_normal_count = 0

        for edge in mesh.edges():
            centerline = mesh.edge_attribute(edge, "centerline")
            normal = mesh.edge_attribute(edge, "normal")

            # Skip edges with None centerlines (marked as deleted/invalid)
            if centerline is None:
                skipped_count += 1
                continue
            
            # Check for None normals
            if normal is None:
                none_normal_count += 1
                from compas.geometry import Vector
                normal = Vector(0, 0, 1)  # Default fallback
                print(f"WARNING: Edge {edge} has None normal, using default Z-up")

            category = self._edge_category(edge)
            if category == "boundary":
                w, h = self.boundary_beam_width, self.boundary_beam_height
            else:
                w, h = self.inner_beam_width, self.inner_beam_height
            beam = Beam.from_centerline(centerline, width=w, height=h, z_vector=normal)
            beam.attributes["category"] = category
            self.timber_model.add_element(beam)

            # Keep track of edge-to-beam relationship
            mesh.edge_attribute(edge, "beam", beam)
            
            # Count categories
            if category == "boundary":
                boundary_count += 1
            else:
                interior_count += 1
        
        if skipped_count > 0:
            print(f"Skipped {skipped_count} edges with None centerlines (deleted/invalid)")
        if none_normal_count > 0:
            print(f"WARNING: {none_normal_count} beams had None normals!")
        
        print(f"Beam categories: {boundary_count} boundary, {interior_count} interior")

    def _edge_category(self, edge) -> str:
        # First check if edge has explicit is_boundary attribute (set by gh_rf_from_centerlines)
        is_boundary = self.rf_system.mesh.edge_attribute(edge, "is_boundary")
        if is_boundary is not None:
            return "boundary" if is_boundary else "interior"
        
        # Fallback to mesh boundary detection
        if self.rf_system.mesh.is_edge_on_boundary(edge):
            return "boundary"

        return "interior"

    
    # --------------------------------------------------------------------------
    # Rule definition
    # --------------------------------------------------------------------------

    def _add_rules(self) -> None:
        """
        Defines the 'logic' of connections with 3 tolerance passes.
        """
        print(f"Adding joint rules with base tolerance: {self.tolerance}")
        
        # Use 3 tolerance values: base, +50%, +100%
        # This catches beams at slightly different distances without going crazy
        tolerances = [
            self.tolerance,           # e.g., 0.10
            self.tolerance * 1.5,     # e.g., 0.15
            self.tolerance * 2.0      # e.g., 0.20
        ]
        
        for tol in tolerances:
            # Case 1: TWO INTERIOR BEAMS - XLapJoint
            self._rules.append(CategoryRule(XLapJoint, "interior", "interior", max_distance=tol))
            
            # Case 2: INTERIOR meets Outer Arch - TLapJoint
            # self._rules.append(CategoryRule(TButtJoint, "interior", "boundary", max_distance=tol))
            self._rules.append(CategoryRule(TLapJoint, "interior", "boundary", max_distance=tol))

            # Case 3: INTERIOR meets Foundation - TBirdsmouthJoint
            # self._rules.append(CategoryRule(TButtJoint, "interior", "boundary", max_distance=tol))
            self._rules.append(CategoryRule(TBirdsmouthJoint, "interior", "boundary", max_distance=tol))
            
            # Case 4: TWO Outer Arch BEAMS - LMiterJoint
            self._rules.append(CategoryRule(LMiterJoint, "boundary", "boundary", max_distance=tol))

            # Case 5: TWO Foundation BEAMS - LMiterJoint
            self._rules.append(CategoryRule(LMiterJoint, "boundary", "boundary", max_distance=tol))

            # Case 6: Outer Arch meets Foundation - TBirdsmouthJoint
            self._rules.append(CategoryRule(TBirdsmouthJoint, "boundary", "boundary", max_distance=tol))
            
            # Case 7: Topology X joints
            self._rules.append(TopologyRule(topology_type=JointTopology.TOPO_X, joint_type=XLapJoint, max_distance=tol))
        
        print(f"Added {len(self._rules)} joint rules (3 tolerance passes: {tolerances})")


    def _apply_rules(self, process_joinery: bool) -> None:
        """
        Runs the solver to find intersections and apply the rules we defined above.
        """
        self.joining_errors = []
        solver = JointRuleSolver(self._rules)
        
        # Debug: Check beam categories before applying rules
        boundary_beams = [b for b in self.timber_model.beams if b.attributes.get("category") == "boundary"]
        interior_beams = [b for b in self.timber_model.beams if b.attributes.get("category") == "interior"]
        print(f"Before joint solving: {len(boundary_beams)} boundary beams, {len(interior_beams)} interior beams")

        # Find pairs of beams that match our rules
        self.joining_errors, unjoined_clusters = solver.apply_rules_to_model(self.timber_model)

        print(f"Found {len(self.joining_errors)} joining errors and {len(unjoined_clusters)} unjoined clusters, using {len(self._rules)} rules.")
        
        # Debug: Count joints by type
        joint_counts = {}
        # Try different attribute names for joints
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
            print(f"Total unjoined clusters: {len(unjoined_clusters)} out of {len(list(self.timber_model.beams))} beams")
        
        if self.joining_errors:
            print("Joining errors:")
            for error in self.joining_errors:
                print(f" - {error}")

        # Actually cut the geometry (this can be slow for large models)
        if process_joinery:
            print("Processing geometry (cutting joints)...")
            self.timber_model.process_joinery()

    # --------------------------------------------------------------------------
    # Optional: direct joint strategies (more explicit, less scalable)
    # --------------------------------------------------------------------------

    def _add_rules_direct(self) -> None:
        """
        Alternative workflow: create rules directly from the RF edge graph instead of
        relying on categories/topology inference.
        """
        self._add_direct_joint_rules()
        self._add_direct_boundary_joint_rules()

    def _add_direct_joint_rules(self) -> None:
        mesh: Mesh = self.rf_system.mesh
        
        # Only process edges that have centerlines (actual beams, not helper edges)
        valid_edges = [e for e in mesh.edges() if mesh.edge_attribute(e, "centerline") is not None]
        print(f"Creating direct rules for {len(valid_edges)} valid edges (out of {len(list(mesh.edges()))} total)...")

        for edge in valid_edges:
            # Use custom is_boundary attribute instead of mesh boundary detection
            is_boundary = mesh.edge_attribute(edge, "is_boundary")
            if is_boundary is True:
                continue  # Skip boundary edges, handle them separately

            beam = mesh.edge_attribute(edge, "beam")
            next_edge = mesh.edge_attribute(edge, "next_edge")
            prev_edge = mesh.edge_attribute(edge, "prev_edge")

            next_beam = mesh.edge_attribute(next_edge, "beam") if next_edge else None
            prev_beam = mesh.edge_attribute(prev_edge, "beam") if prev_edge else None

            if beam is None:
                continue
            
            # Check if next/prev edges are boundary edges
            next_is_boundary = mesh.edge_attribute(next_edge, "is_boundary") if next_edge else False
            prev_is_boundary = mesh.edge_attribute(prev_edge, "is_boundary") if prev_edge else False

            # Transition from interior to boundary: combine butt + lap logic.
            if next_edge and next_is_boundary:
                if next_beam:
                    self._rules.append(DirectRule(TButtJoint, [beam, next_beam], self.tolerance))
                if prev_beam:
                    self._rules.append(DirectRule(XLapJoint, [prev_beam, beam], self.tolerance))
                continue

            if prev_edge and prev_is_boundary:
                if prev_beam:
                    self._rules.append(DirectRule(TButtJoint, [beam, prev_beam], self.tolerance))
                if next_beam:
                    self._rules.append(DirectRule(XLapJoint, [next_beam, beam], self.tolerance))
                continue

            # Interior-interior transitions: use lap joints on both sides.
            if next_beam:
                self._rules.append(DirectRule(XLapJoint, [next_beam, beam], self.tolerance))
            if prev_beam:
                self._rules.append(DirectRule(XLapJoint, [prev_beam, beam], self.tolerance))
        
        print(f"Created {len(self._rules)} direct joint rules from interior edges")

    def _add_direct_boundary_joint_rules(self) -> None:
        mesh: Mesh = self.rf_system.mesh
        
        print("Creating direct rules for boundary edges...")
        
        # Find all boundary edges
        boundary_edges = [e for e in mesh.edges() if mesh.edge_attribute(e, "is_boundary")]
        print(f"Found {len(boundary_edges)} boundary edges")
        
        # Group boundary edges by shared vertices
        vertex_to_edges = {}
        for edge in boundary_edges:
            u, v = edge
            if u not in vertex_to_edges:
                vertex_to_edges[u] = []
            if v not in vertex_to_edges:
                vertex_to_edges[v] = []
            vertex_to_edges[u].append(edge)
            vertex_to_edges[v].append(edge)
        
        # Create miter joints where two boundary edges meet
        for vertex, edges in vertex_to_edges.items():
            if len(edges) == 2:
                beam_a = mesh.edge_attribute(edges[0], "beam")
                beam_b = mesh.edge_attribute(edges[1], "beam")
                if beam_a and beam_b:
                    self._rules.append(DirectRule(LMiterJoint, [beam_a, beam_b], self.tolerance))
        
        print(f"Total rules after boundary joints: {len(self._rules)}")