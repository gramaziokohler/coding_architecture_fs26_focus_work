# ========================================================================
# CHALLENGE 01: Attractors
# To complete this challenge:
# 1. Implement the methods `eccentrize_centerlines_attractor_point`
#    and `eccentrize_centerlines_attractor_curve` located below.
# 2. Once implemented, apply these methods within the `RF System` section
#    of the Grasshopper canvas.
# ========================================================================
from typing import Optional

from compas.datastructures import Mesh
from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector


class RFSystem:
    """
    Reciprocal-frame helper built on top of a COMPAS mesh.
    All computed RF data is written back as edge attributes of the mesh.

    The mesh edges become the "members" of the RF system. This class stores extra
    edge attributes needed later for timber fabrication:
    - ``centerline``: geometric line used to create a beam
    - ``normal``: orientation vector for the beam cross-section
    - ``next_edge`` / ``prev_edge``: neighboring RF edges around the local face
    """

    def __init__(self, mesh: Mesh):
        self.mesh = mesh
        self.timber_model = None

    @property
    def centerlines(self) -> list:
        """
        Get all centerlines from edges that have a centerline attribute set.
        Quad closing edges should be removed beforehand via remove_quad_closing_edges().
        """
        centerlines = []
        for edge in self.mesh.edges():
            centerline = self.mesh.edge_attribute(edge, "centerline")
            if centerline is not None:
                centerlines.append(centerline)
        print(f"Total centerlines returned: {len(centerlines)}")
        return centerlines

    def copy(self) -> "RFSystem":
        return RFSystem(mesh=self.mesh.copy())

    # --------------------------------------------------------------------------
    # RF DATASTRUCTURE SETUP
    # --------------------------------------------------------------------------

    def create_rf_datastructure(self) -> None:
        """
        Compute and store all RF edge attributes.
        """
        # Initialize centerline + normal for every edge.
        for edge in self.mesh.edges():
            self._set_centerline(edge)
            self._set_normal(edge)  # Set normal for ALL edges, not just interior

            # Boundary edges are valid members, but they have incomplete RF neighborhood data,
            # so we can skip computing those attributes for them.
            if self.mesh.is_edge_on_boundary(edge):
                continue

            self._set_edge_neighborhood(edge)

    def _set_centerline(self, edge) -> None:
        """Store the geometric line representation of a mesh edge."""
        self.mesh.edge_attribute(edge, "centerline", self.mesh.edge_line(edge))

    def _set_normal(self, edge) -> None:
        """Store an orientation normal for an edge (averaged on interior edges, single-face on boundary)."""
        self.mesh.edge_attribute(edge, "normal", self._compute_edge_normal(edge))

    def _set_edge_neighborhood(self, edge) -> None:
        next_edge = self._compute_next_rf_edge(edge)
        prev_edge = self._compute_prev_rf_edge(edge)

        # Store local RF connectivity for interior edges
        self.mesh.edge_attribute(edge, "next_edge", next_edge)
        self.mesh.edge_attribute(edge, "prev_edge", prev_edge)

    def _compute_next_rf_edge(self, edge):
        """Return the next halfedge around the face of the given halfedge."""
        face = self.mesh.halfedge_face(edge)
        halfedges = self.mesh.face_halfedges(face)
        index = halfedges.index(edge)
        return halfedges[(index + 1) % len(halfedges)]

    def _compute_prev_rf_edge(self, edge):
        """Return the previous RF edge by walking the opposite halfedge's face cycle."""
        reversed_edge = (edge[1], edge[0])
        # Reversing first, then taking "next", is a neat way to get the previous RF relation
        return self._compute_next_rf_edge(reversed_edge)

    def _compute_edge_normal(self, edge) -> Vector:
        """
        Compute an edge orientation vector for beam placement.
        
        Returns the face normal of the adjacent hexagon, ensuring beams
        align with their base hexagon's surface orientation.
        """
        # Get the adjacent faces
        face_a, face_b = self.mesh.edge_faces(edge)
        
        # Use the first available face normal (the "base hexagon")
        if face_a is not None:
            return self.mesh.face_normal(face_a).unitized()
        elif face_b is not None:
            return self.mesh.face_normal(face_b).unitized()
        else:
            # No adjacent faces - fallback to Z-up
            return Vector(0, 0, 1)

    # --------------------------------------------------------------------------
    # RF SYSTEM CENTERLINES ROTATION
    # --------------------------------------------------------------------------

    def eccentrize_centerlines(self, eccentricity: Optional[float] = None,
                               u_start: Optional[float] = None, u_end: Optional[float] = None,
                               v_start: Optional[float] = None, v_end: Optional[float] = None) -> Mesh:
        """
        Shift interior centerlines so beams overlap like a reciprocal frame.

        Positive values push line ends in the local RF directions.
        
        Parameters
        ----------
        eccentricity : float, optional
            Uniform eccentricity for all directions (legacy parameter).
            If provided, overrides u/v parameters.
        u_start : float, optional
            Eccentricity at the start of the edge (prev_edge direction).
            Defaults to eccentricity if not specified.
        u_end : float, optional
            Eccentricity at the end of the edge (next_edge direction).
            Defaults to eccentricity if not specified.
        v_start : float, optional
            Additional offset in the v direction at start (currently same as u_start).
            Defaults to u_start if not specified.
        v_end : float, optional
            Additional offset in the v direction at end (currently same as u_end).
            Defaults to u_end if not specified.
            
        Returns
        -------
        Mesh
            The modified mesh with updated centerlines.
        """
        # Handle parameter defaults
        if eccentricity is not None:
            # Legacy mode: use single eccentricity value for all
            u_start = u_start if u_start is not None else eccentricity
            u_end = u_end if u_end is not None else eccentricity
            v_start = v_start if v_start is not None else eccentricity
            v_end = v_end if v_end is not None else eccentricity
        else:
            # New mode: use individual parameters or default to 0
            u_start = u_start if u_start is not None else 0.0
            u_end = u_end if u_end is not None else 0.0
            v_start = v_start if v_start is not None else u_start
            v_end = v_end if v_end is not None else u_end
        
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue

            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            centerline = self.mesh.edge_attribute(edge, "centerline")

            next_direction = self.mesh.edge_direction(next_edge).unitized()
            prev_direction = self.mesh.edge_direction(prev_edge).unitized()

            # Apply u direction (along edge neighbors)
            start_shift = prev_direction * u_start
            end_shift = next_direction * u_end
            
            # Apply v direction (perpendicular adjustments)
            # For v direction, we use the same directions but with v parameters
            start_shift += prev_direction * (v_start - u_start)
            end_shift += next_direction * (v_end - u_end)

            centerline.start += start_shift
            centerline.end += end_shift
            self.mesh.edge_attribute(edge, "centerline", centerline)

        return self.mesh
    def eccentrize_centerlines_hexagonal(self, offset: float, rotation_angle: float = 60.0) -> Mesh:
        """
        Create hexagonal patterns by rotating and offsetting centerlines to form hexagonal openings.
        
        This method shifts centerlines perpendicular to their direction to create hexagonal voids
        in the RF system. The hexagons are formed by offsetting edges inward/outward relative to
        their face centers.
        
        Parameters
        ----------
        offset : float
            Distance to offset centerlines perpendicular to their direction.
            Positive values create outward hexagons, negative values create inward hexagons.
        rotation_angle : float, optional
            Angle in degrees to rotate the offset direction around the edge normal.
            Default is 60 degrees for regular hexagonal patterns.
            
        Returns
        -------
        Mesh
            The modified mesh with hexagonal centerline patterns.
        """
        import math
        
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            
            centerline = self.mesh.edge_attribute(edge, "centerline")
            edge_normal = self.mesh.edge_attribute(edge, "normal")
            
            # Get edge direction
            edge_direction = centerline.direction.unitized()
            
            # Calculate perpendicular offset direction in the plane of the edge normal
            # Cross product gives us a vector perpendicular to both edge and normal
            perpendicular = edge_direction.cross(edge_normal)
            perpendicular.unitize()
            
            # Rotate the perpendicular vector by the rotation angle around the edge direction
            # This creates the hexagonal pattern
            angle_rad = math.radians(rotation_angle)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            
            # Rodrigues' rotation formula for rotating perpendicular around edge_direction
            rotated_perp = (
                perpendicular * cos_a +
                edge_direction.cross(perpendicular) * sin_a +
                edge_direction * (edge_direction.dot(perpendicular)) * (1 - cos_a)
            )
            rotated_perp.unitize()
            
            # Apply offset to create hexagonal pattern
            offset_vector = rotated_perp * offset
            
            centerline.start += offset_vector
            centerline.end += offset_vector
            
            self.mesh.edge_attribute(edge, "centerline", centerline)
        
        return self.mesh
    def eccentrize_centerlines_hexagonal_uv(self, offset: float, 
                                            u_offset: Optional[float] = None,
                                            v_offset: Optional[float] = None) -> Mesh:
        """
        Create hexagonal patterns using RF topology (prev_edge/next_edge directions).
        
        This method offsets centerlines perpendicular to the prev_edge (u) and next_edge (v)
        directions to create hexagonal voids that follow the RF system's natural topology.
        
        Parameters
        ----------
        offset : float
            Base offset distance for both u and v directions.
        u_offset : float, optional
            Specific offset for the start (prev_edge direction). 
            If None, uses the base offset value.
        v_offset : float, optional
            Specific offset for the end (next_edge direction).
            If None, uses the base offset value.
            
        Returns
        -------
        Mesh
            The modified mesh with RF topology-based hexagonal patterns.
        """
        import math
        
        # Set default values
        u_offset = u_offset if u_offset is not None else offset
        v_offset = v_offset if v_offset is not None else offset
        
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            
            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            centerline = self.mesh.edge_attribute(edge, "centerline")
            edge_normal = self.mesh.edge_attribute(edge, "normal")
            
            # Get RF directions (u and v)
            next_direction = self.mesh.edge_direction(next_edge).unitized()  # v direction
            prev_direction = self.mesh.edge_direction(prev_edge).unitized()  # u direction
            
            # Calculate perpendicular directions for hexagonal offset
            # For start: perpendicular to prev_edge (u) direction
            u_perpendicular = prev_direction.cross(edge_normal)
            u_perpendicular.unitize()
            
            # For end: perpendicular to next_edge (v) direction  
            v_perpendicular = next_direction.cross(edge_normal)
            v_perpendicular.unitize()
            
            # Create hexagonal pattern by offsetting in perpendicular directions
            # Start offset based on u (prev_edge) topology
            start_offset = u_perpendicular * u_offset
            
            # End offset based on v (next_edge) topology
            end_offset = v_perpendicular * v_offset
            
            # Apply offsets to create hexagonal pattern following RF topology
            centerline.start += start_offset
            centerline.end += end_offset
            
            self.mesh.edge_attribute(edge, "centerline", centerline)
        
        return self.mesh



    def extend_centerlines(self, extensions_pos: float = 0.0, extensions_neg: float = 0.0,
                          relative: bool = False, attractor_point: Optional[Point] = None,
                          max_distance: float = 1.0, attractor_strength: float = 1.0) -> None:
        """
        Extend centerlines uniformly with special handling for closing edges.
        
        Parameters
        ----------
        extensions_pos : float, optional
            Extension distance from the end point.
            If relative=True, this is a factor of the edge length.
            Default is 0.0.
        extensions_neg : float, optional
            Extension distance from the start point.
            If relative=True, this is a factor of the edge length.
            Default is 0.0.
        relative : bool, optional
            If True, extensions are relative to edge length.
            Default is False (absolute mode).
        """
        attractor_point : Point, optional
            An attractor point that controls extension amount based on distance
            from the centerline midpoint.
        max_distance : float, optional
            Distance from the attractor point beyond which full slider extension applies.
            Default is 1.0.
        attractor_strength : float, optional
            Strength of the attractor attenuation. A value of 1.0 gives full
            reduction near the point, while lower values soften the effect.
            Default is 1.0.
        """
        def _attractor_scale(distance: float) -> float:
            if distance >= max_distance:
                return 1.0
            if max_distance <= 0.0:
                return 1.0
            normalized = distance / max_distance
            # Preserve full extension at max_distance, while reducing extension
            # smoothly as the centerline midpoint approaches the point.
            scale = 1.0 - (1.0 - normalized) * attractor_strength
            return max(0.0, min(1.0, scale))

        # Identify closing edges by checking each edge against ALL its faces
        closing_edges_to_skip = set()  # For 4-vertex faces
        closing_edges_info = {}  # For 6-vertex faces: edge -> (face, face_verts)
        
        for edge in self.mesh.edges():
            faces = self.mesh.edge_faces(edge)
            
            # Check all faces this edge belongs to
            for face in faces:
                if face is None:
                    continue
                    
                face_verts = self.mesh.face_vertices(face)
                num_verts = len(face_verts)
                
                # Check if this edge is the closing edge for this face
                is_closing = (
                    (edge[0] == face_verts[0] and edge[1] == face_verts[-1]) or
                    (edge[0] == face_verts[-1] and edge[1] == face_verts[0])
                )
                
                if is_closing:
                    if num_verts == 4:
                        closing_edges_to_skip.add(edge)
                        print(f"Edge {edge}: Closing edge for quad face {face} {face_verts} (SKIP)")
                    elif num_verts == 6:
                        closing_edges_info[edge] = (face, face_verts)
                        print(f"Edge {edge}: Closing edge for hexagon face {face} {face_verts} (RECONSTRUCT)")
                    break  # Found it for this edge, move to next edge
        
        print(f"\nTotal closing edges to skip: {len(closing_edges_to_skip)}")
        print(f"Total closing edges to reconstruct: {len(closing_edges_info)}")
        
        # Now apply extensions to all edges
        for edge in self.mesh.edges():
            centerline: Line = self.mesh.edge_attribute(edge, "centerline")
            if centerline is None:
                continue
            
            # Skip quad closing edges
            if edge in closing_edges_to_skip:
                continue
            
            # For hexagon closing edges, reconstruct the centerline in the correct direction
            if edge in closing_edges_info:
                face, face_verts = closing_edges_info[edge]
                # The closing edge should go from face_verts[-1] to face_verts[0]
                # to maintain consistent winding with other edges
                start_pt = Point(*self.mesh.vertex_coordinates(face_verts[-1]))
                end_pt = Point(*self.mesh.vertex_coordinates(face_verts[0]))
                centerline = Line(start_pt, end_pt)
                print(f"Reconstructed closing edge {edge}: {start_pt} -> {end_pt}")
            
            # Calculate extension amounts
            if relative:
                edge_length = centerline.length
                ext_pos = extensions_pos * edge_length
                ext_neg = extensions_neg * edge_length
            else:
                ext_pos = extensions_pos
                ext_neg = extensions_neg
            if attractor_point is not None:
                midpoint = Point(
                    (centerline.start.x + centerline.end.x) / 2.0,
                    (centerline.start.y + centerline.end.y) / 2.0,
                    (centerline.start.z + centerline.end.z) / 2.0,
                )
                distance = midpoint.distance_to_point(attractor_point)
                scale = _attractor_scale(distance)
                ext_pos *= scale
                ext_neg *= scale
            
            # Apply standard extensions
            edge_dir = centerline.direction.unitized()
            centerline.start += edge_dir * (-ext_neg)
            centerline.end += edge_dir * ext_pos

            # Save the modified centerline back to the mesh
            self.mesh.edge_attribute(edge, "centerline", centerline)

    def remove_quad_closing_edges(self) -> None:
        """
        Remove closing edges from 4-vertex faces (quads).
        
        For quad faces, the closing edge connects vertex 3 back to vertex 0.
        This edge is removed from the mesh to create open quad shapes.
        """
        edges_to_remove = []
        
        # Identify closing edges for 4-vertex faces
        for edge in self.mesh.edges():
            faces = self.mesh.edge_faces(edge)
            
            # Check all faces this edge belongs to
            for face in faces:
                if face is None:
                    continue
                    
                face_verts = self.mesh.face_vertices(face)
                num_verts = len(face_verts)
                
                # Only process 4-vertex faces
                if num_verts == 4:
                    # Check if this edge is the closing edge (connects last to first vertex)
                    is_closing = (
                        (edge[0] == face_verts[0] and edge[1] == face_verts[-1]) or
                        (edge[0] == face_verts[-1] and edge[1] == face_verts[0])
                    )
                    
                    if is_closing:
                        edges_to_remove.append(edge)
                        print(f"Marking edge {edge} for removal (closing edge of quad face {face})")
                        break  # Found it for this edge, move to next edge
        
        # Remove the identified edges from the mesh
        for edge in edges_to_remove:
            try:
                self.mesh.delete_edge(edge)
                print(f"Removed edge {edge}")
            except Exception as e:
                print(f"Failed to remove edge {edge}: {e}")
        
        print(f"\nTotal quad closing edges removed: {len(edges_to_remove)}")

    # ========================================================================
    # CHALLENGE 01: Attractors
    # ========================================================================

    def eccentrize_centerlines_attractor_point(self, point: Point, factor: float) -> None:
        """
        Moves the centerlines of the RF system edges towards or away from an attractor point.
        The amount of movement is determined by the distance to the point.
        
        Parameters
        ----------
        point : Point
            The attractor point that influences the eccentricity.
        factor : float
            Scaling factor for the eccentricity. Positive values increase eccentricity
            near the attractor, negative values decrease it.
        """
        # 1. Iterate over all edges in the mesh
        for edge in self.mesh.edges():
            # 2. Skip boundary edges
            if self.mesh.is_edge_on_boundary(edge):
                continue

            # 3. Get the next_edge, prev_edge, and centerline attributes for the current edge
            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            centerline = self.mesh.edge_attribute(edge, "centerline")

            # 4. Calculate the unitized direction vectors for next_edge and prev_edge
            next_direction = self.mesh.edge_direction(next_edge).unitized()
            prev_direction = self.mesh.edge_direction(prev_edge).unitized()

            # 5. Get the vertex points for the start and end of the current edge
            start_vertex = self.mesh.vertex_point(edge[0])
            end_vertex = self.mesh.vertex_point(edge[1])

            # 6. Calculate the distance from each vertex to the attractor point
            start_distance = start_vertex.distance_to_point(point)
            end_distance = end_vertex.distance_to_point(point)

            # 7. Multiply the distances by the factor to get the eccentricity values
            # Using inverse distance relationship: closer points get more eccentricity
            # Add small epsilon to avoid division by zero
            epsilon = 0.001
            start_eccentricity = factor / (start_distance + epsilon)
            end_eccentricity = factor / (end_distance + epsilon)

            # 8. Calculate the start and end displacements using the direction vectors and eccentricity values
            start_shift = prev_direction * start_eccentricity
            end_shift = (-start_shift) + next_direction * end_eccentricity

            # 9. Apply the displacements to the start and end of the centerline
            centerline.start += start_shift
            centerline.end += end_shift

            # 10. Update the centerline attribute for the current edge
            self.mesh.edge_attribute(edge, "centerline", centerline)

    def eccentrize_centerlines_attractor_curve(self, curve, factor: float) -> None:
        """
        Eccentrize centerlines based on the distance to an attractor curve.
        
        Parameters
        ----------
        curve : Curve or Polyline
            The attractor curve that influences the eccentricity.
        factor : float
            Scaling factor for the eccentricity. Positive values increase eccentricity
            near the curve, negative values decrease it.
        """
        # 1. Iterate over all edges in the mesh
        for edge in self.mesh.edges():
            # 2. Skip boundary edges
            if self.mesh.is_edge_on_boundary(edge):
                continue

            # 3. Get the next_edge, prev_edge, and centerline attributes for the current edge
            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            centerline = self.mesh.edge_attribute(edge, "centerline")

            # 4. Calculate the unitized direction vectors for next_edge and prev_edge
            next_direction = self.mesh.edge_direction(next_edge).unitized()
            prev_direction = self.mesh.edge_direction(prev_edge).unitized()

            # 5. Get the vertex points for the start and end of the current edge
            start_vertex = self.mesh.vertex_point(edge[0])
            end_vertex = self.mesh.vertex_point(edge[1])

            # 6. Find the closest points on the attractor curve from each vertex
            # Using the curve's closest_point method
            start_closest = curve.closest_point(start_vertex)
            end_closest = curve.closest_point(end_vertex)

            # 7. Calculate the distance between each vertex and its closest point on the curve
            start_distance = start_vertex.distance_to_point(start_closest)
            end_distance = end_vertex.distance_to_point(end_closest)

            # 8. Multiply the distances by the factor to get the eccentricity values
            # Using inverse distance relationship: closer points get more eccentricity
            # Add small epsilon to avoid division by zero
            epsilon = 0.001
            start_eccentricity = factor / (start_distance + epsilon)
            end_eccentricity = factor / (end_distance + epsilon)

            # 9. Calculate the start and end displacements using the direction vectors and eccentricity values
            start_shift = prev_direction * start_eccentricity
            end_shift = (-start_shift) + next_direction * end_eccentricity

            # 10. Apply the displacements to the start and end of the centerline
            centerline.start += start_shift
            centerline.end += end_shift

            # 11. Update the centerline attribute for the current edge
            self.mesh.edge_attribute(edge, "centerline", centerline)
