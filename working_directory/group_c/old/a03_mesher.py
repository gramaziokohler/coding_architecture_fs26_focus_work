import Rhino.Geometry as rg  # type: ignore
from compas.datastructures import Mesh
from compas.geometry import NurbsSurface
from compas.itertools import linspace


class BaseMesher:
    """Small shared base class for Brep-based meshers."""

    def __init__(self, u_count: int, v_count: int, brep: rg.Brep):
        self.u_count = u_count
        self.v_count = v_count
        self.brep = brep
        self.mesh = Mesh()

    @property
    def face(self) -> rg.BrepFace:
        return self.brep.Faces[0]

    @property
    def surface(self) -> NurbsSurface:
        return NurbsSurface.from_native(self.face.UnderlyingSurface())

    def is_vertex_on_face(self, vertex_key) -> bool:
        point = self.mesh.vertex_point(vertex_key)
        _, face_u, face_v = self.face.ClosestPoint(rg.Point3d(point.x, point.y, point.z))
        relation = self.face.IsPointOnFace(face_u, face_v)

        if relation == rg.PointFaceRelation.Interior:
            return True
        if relation == rg.PointFaceRelation.Boundary:
            return True

        return False

    def _vertex_key(self, u_index: int, v_index: int) -> int:
        return next(self.mesh.vertices_where({"u": u_index, "v": v_index}))

    def _filtered_face_vertices(self, vertex_keys: list[int]) -> list[int]:
        filtered_vertices = []

        for vertex_key in vertex_keys:
            if self.is_vertex_on_face(vertex_key):
                filtered_vertices.append(vertex_key)

        return filtered_vertices


class QuadMesher(BaseMesher):
    """Generate a quad mesh from a single-face Brep.

    Parameters
    ----------
    u_count : int
        Number of cells in the U direction.
    v_count : int
        Number of cells in the V direction.
    brep : rg.Brep
        Input Brep. Only the first face is used.
    full_quads : bool, optional
        If ``True``, keep only complete quads.
        If ``False``, allow clipped boundary polygons.

    Attributes
    ----------
    mesh : compas.datastructures.Mesh
        Output mesh.
    """

    def __init__(self, u_count: int, v_count: int, brep: rg.Brep, full_quads: bool = False):
        super().__init__(u_count=u_count, v_count=v_count, brep=brep)
        self.full_quads = full_quads

    def generate_vertices(self) -> None:
        """Sample the surface on a regular UV grid and store mesh vertices."""
        u_values = list(linspace(self.surface.domain_u[0], self.surface.domain_u[1], self.u_count + 1))
        v_values = list(linspace(self.surface.domain_v[0], self.surface.domain_v[1], self.v_count + 1))

        for ui, u in enumerate(u_values):
            for vi, v in enumerate(v_values):
                point = self.surface.point_at(u, v)
                self.mesh.add_vertex(x=point.x, y=point.y, z=point.z, u=ui, v=vi)
        return None

    def generate_mesh(self) -> Mesh:
        self.generate_vertices()

        for u in range(self.u_count):
            for v in range(self.v_count):
                v1 = self._vertex_key(u, v)
                v2 = self._vertex_key(u, v + 1)
                v3 = self._vertex_key(u + 1, v + 1)
                v4 = self._vertex_key(u + 1, v)
                face_vertices = self._filtered_face_vertices([v1, v2, v3, v4])
                if len(face_vertices) < 3:
                    continue

                if self.full_quads and len(face_vertices) != 4:
                    continue

                self.mesh.add_face(face_vertices)

        self.mesh.remove_unused_vertices()
        return self.mesh


class SimplestTriMesher(QuadMesher):
    def generate_mesh(self) -> Mesh:
        super().generate_mesh()
        self.mesh.quads_to_triangles()
        return self.mesh


class SimplestHexaMesher(SimplestTriMesher):
    def __init__(self, u_count: int, v_count: int, brep: rg.Brep, full_hexas: bool = False):
        super().__init__(u_count=u_count, v_count=v_count, brep=brep)
        self.full_hexas = full_hexas

    def generate_mesh(self) -> Mesh:
        super().generate_mesh()
        self.mesh = self.mesh.dual(include_boundary=True)
        return self.mesh


class TriMesher(BaseMesher):
    def generate_vertices(self) -> None:
        u_line_count = self.u_count + 1
        v_line_count = self.v_count + 2

        u_values = list(linspace(self.surface.domain_u[0], self.surface.domain_u[1], u_line_count))
        v_values = list(linspace(self.surface.domain_v[0], self.surface.domain_v[1], v_line_count))

        for ui, u in enumerate(u_values):
            for vi, v in enumerate(v_values):
                point = self.surface.point_at(u, v)
                self.mesh.add_vertex(x=point.x, y=point.y, z=point.z, u=ui, v=vi)
        return None

    def generate_mesh(self) -> Mesh:
        self.generate_vertices()
        for ui in range(self.u_count):
            for vi in range(self.v_count):
                if (ui + vi) % 2 == 0:  # is even
                    v1 = self._vertex_key(ui, vi + 1)
                    v2 = self._vertex_key(ui + 1, vi + 2)
                    v3 = self._vertex_key(ui + 1, vi)
                else:
                    v1 = self._vertex_key(ui, vi)
                    v2 = self._vertex_key(ui, vi + 2)
                    v3 = self._vertex_key(ui + 1, vi + 1)

                face_vertices = self._filtered_face_vertices([v1, v2, v3])

                if len(face_vertices) < 3:
                    continue

                self.mesh.add_face(face_vertices)
        self.mesh.remove_unused_vertices()
        return self.mesh


class HexaMesher(BaseMesher):
    def __init__(self, u_count: int, v_count: int, brep: rg.Brep, full_hexas: bool = False):
        super().__init__(u_count=u_count, v_count=v_count, brep=brep)
        self.full_hexas = full_hexas

    def generate_vertices(self) -> None:
        u_lines = self.u_count * 2 + 2
        v_lines = self.v_count * 2 + 2

        u_values = list(linspace(self.surface.domain_u[0], self.surface.domain_u[1], u_lines))
        v_values = list(linspace(self.surface.domain_v[0], self.surface.domain_v[1], v_lines))

        for ui, u in enumerate(u_values):
            for vi, v in enumerate(v_values):
                point = self.surface.point_at(u, v)
                self.mesh.add_vertex(x=point.x, y=point.y, z=point.z, u=ui, v=vi)
        return None

    def generate_mesh(self) -> Mesh:
        self.generate_vertices()
        for ui in range(self.u_count):
            for vi in range(self.v_count):
                if vi % 2 == 0:  # is even
                    v1 = self._vertex_key(ui * 2, vi * 2 + 1)
                    v2 = self._vertex_key(ui * 2, vi * 2 + 2)
                    v3 = self._vertex_key(ui * 2 + 1, vi * 2 + 3)
                    v4 = self._vertex_key(ui * 2 + 2, vi * 2 + 2)
                    v5 = self._vertex_key(ui * 2 + 2, vi * 2 + 1)
                    v6 = self._vertex_key(ui * 2 + 1, vi * 2 + 0)
                else:  # is odd
                    v1 = self._vertex_key(ui * 2 + 1, vi * 2 + 1)
                    v2 = self._vertex_key(ui * 2 + 1, vi * 2 + 2)
                    v3 = self._vertex_key(ui * 2 + 2, vi * 2 + 3)
                    v4 = self._vertex_key(ui * 2 + 3, vi * 2 + 2)
                    v5 = self._vertex_key(ui * 2 + 3, vi * 2 + 1)
                    v6 = self._vertex_key(ui * 2 + 2, vi * 2 + 0)

                if self.full_hexas and all([self.is_vertex_on_face(v) for v in [v1, v2, v3, v4, v5, v6]]):
                    self.mesh.add_face([v1, v2, v3, v4, v5, v6])

                elif not self.full_hexas:
                    face_vertices = self._filtered_face_vertices([v1, v2, v3, v4, v5, v6])

                    if len(face_vertices) < 3:
                        continue

                    self.mesh.add_face(face_vertices)

        self.mesh.remove_unused_vertices()
        return self.mesh


class HexagonalMesher2D(BaseMesher):
    """Generate a 2D hexagonal mesh with pointy-topped hexagons projected onto a Brep surface.
    
    The mesh starts with a 'half-hexagon' at the X=0 plane, with the first
    hexagon's centroid anchored at the origin [0,0,0] in the UV parameter space.
    The hexagonal pattern is then projected onto the Brep surface.
    
    Parameters
    ----------
    u_count : int
        Number of columns (in X direction).
    v_count : int
        Number of rows (in Y direction).
    radius : float
        Distance from the center to a vertex (R) in UV parameter space.
    brep : rg.Brep
        Input Brep. Only the first face is used.
    full_hexas : bool, optional
        If ``True``, keep only complete hexagons.
        If ``False``, allow clipped boundary polygons.
    
    Attributes
    ----------
    mesh : compas.datastructures.Mesh
        Output mesh with hexagonal topology.
    
    Examples
    --------
    >>> mesher = HexagonalMesher2D(u_count=5, v_count=4, radius=1.0, brep=my_brep)
    >>> mesh = mesher.generate_mesh()
    """
    
    def __init__(self, u_count: int, v_count: int, radius: float, brep, full_hexas: bool = False, inset: float = 0.0):
        super().__init__(u_count=u_count, v_count=v_count, brep=brep)
        self.radius = radius
        self.full_hexas = full_hexas
        self.inset = inset
        
        # Geometric constants for pointy-topped hexagons
        import math
        self.sqrt3 = math.sqrt(3)
        self.col_spacing = self.sqrt3 * radius  # Horizontal spacing between column centers
        self.row_spacing = 1.5 * radius  # Vertical spacing between rows
    
    def _get_hexagon_corners_uv(self, center_u: float, center_v: float, is_first_column: bool = False,
                                 is_last_column: bool = False, is_last_row: bool = False, max_v: float = None) -> list[tuple[float, float]]:
        """Calculate corner positions of a pointy-topped hexagon in UV space.
        
        Corners are numbered 0-5 starting from 30° going counter-clockwise:
        0: 30° (right-top), 1: 90° (top), 2: 150° (left-top),
        3: 210° (left-bottom), 4: 270° (bottom), 5: 330° (right-bottom)
        
        Half-hexagons are created by selecting specific corners:
        - Left edge: corners 0,1,4,5 (right half)
        - Right edge: corners 1,2,3,4 (left half)
        
        Parameters
        ----------
        center_u, center_v : float
            Hexagon center coordinates in UV space.
        is_first_column : bool
            If True, return right half (left edge hexagon).
        is_last_column : bool
            If True, return left half (right edge hexagon).
        is_last_row : bool
            If True, clip corners above max_v (top edge hexagon).
        max_v : float, optional
            Maximum V coordinate for top edge clipping.
        
        Returns
        -------
        list[tuple[float, float]]
            Corner coordinates in UV space.
        """
        import math
        corners = []
        
        # Calculate effective radius with inset
        # inset of 0.0 = full radius, inset of 1.0 = zero radius (point at center)
        effective_radius = self.radius * (1.0 - self.inset)
        
        # Determine which corners to include based on edge position
        if is_first_column:
            # Right half: corners 0,1,4,5 (skip 2,3 which are on the left)
            corner_indices = [0, 1, 4, 5]
        elif is_last_column:
            # Left half: corners 1,2,3,4 (skip 0,5 which are on the right)
            corner_indices = [1, 2, 3, 4]
        else:
            # Full hexagon: all 6 corners
            corner_indices = [0, 1, 2, 3, 4, 5]
        
        for i in corner_indices:
            angle = math.radians(30 + 60 * i)
            u = center_u + effective_radius * math.cos(angle)
            v = center_v + effective_radius * math.sin(angle)
            
            # For last row, only include corners at or below max_v
            if is_last_row and max_v is not None and v > max_v + 1e-10:
                continue
            
            # Clamp to exactly 0 if very close to avoid floating point issues (left edge)
            if is_first_column and abs(u) < 1e-10:
                u = 0.0
            
            # Clamp to max_v if very close
            if is_last_row and max_v is not None and abs(v - max_v) < 1e-10:
                v = max_v
                
            corners.append((u, v))
        
        return corners
    
    def generate_vertices(self) -> None:
        """Generate vertices for the hexagonal mesh in UV parameter space.
        
        Creates shared vertices at hexagon corners, mapping UV coordinates to 3D points
        on the Brep surface. Vertices are shared between adjacent hexagons.
        """
        import math
        
        # Dictionary to store unique vertices by their UV coordinates
        # Key: (rounded_u, rounded_v), Value: vertex_key
        self.uv_to_vertex = {}
        
        # Store mapping from (col, row, corner_idx) to vertex key for face creation
        self.vertex_uv_map = {}
        
        # Calculate the total extent needed
        # Add extra rows for V direction, and extra columns for U direction
        effective_v_count = self.v_count + 2  # Add 2 rows for coverage (one will be removed)
        effective_u_count = self.u_count + 1  # Add 1 column for half-hexagon on right edge
        
        # Calculate the actual extent in UV space
        # Keep extent based on original counts - extra hexagons will extend beyond
        max_v_extent = self.v_count * self.row_spacing + self.radius / 2
        max_u_extent = self.u_count * self.col_spacing
        
        for col in range(effective_u_count):
            # Start from row=1 to skip the first row that gets shifted down
            for row in range(1, effective_v_count):
                # Skip the last column for odd rows (they don't need it)
                if col == self.u_count and row % 2 == 1:
                    continue
                
                # Calculate hexagon center position in UV space
                center_u = col * self.col_spacing
                center_v = row * self.row_spacing
                
                # Apply horizontal offset for odd rows (staggering)
                if row % 2 == 1:
                    center_u += self.col_spacing / 2
                
                # Shift entire mesh down so the middle-left corner of first hexagon is at V=0
                # For pointy-topped hexagon, the left-middle corner (at 150°) is at (−√3R/2, R/2)
                # So we shift down by R/2 to align that corner with baseline
                center_v -= self.radius / 2
                
                # Get hexagon corners in UV space
                # Only treat as first column if center is actually at U=0 (even rows in col=0)
                is_first_column = (col == 0 and row % 2 == 0)
                # Check if this is the last column (needs right edge truncation)
                # Only even rows: half-hexagon at u_count (odd rows are full hexagons)
                is_last_column = (col == self.u_count and row % 2 == 0)
                # Check if this is the last row (needs top edge truncation)
                is_last_row = (row == effective_v_count - 1)
                corners_uv = self._get_hexagon_corners_uv(center_u, center_v, is_first_column, is_last_column, is_last_row, max_v_extent)
                
                # Add vertices for each corner (with sharing)
                for corner_idx, (u, v) in enumerate(corners_uv):
                    # Round UV coordinates to avoid floating point duplicates
                    uv_key = (round(u, 8), round(v, 8))
                    
                    # Check if vertex already exists at this UV location
                    if uv_key not in self.uv_to_vertex:
                        # Map UV to surface domain using the actual extent
                        u_param = self.surface.domain_u[0] + u * (self.surface.domain_u[1] - self.surface.domain_u[0]) / max_u_extent
                        v_param = self.surface.domain_v[0] + v * (self.surface.domain_v[1] - self.surface.domain_v[0]) / max_v_extent
                        
                        # Get 3D point on surface
                        point = self.surface.point_at(u_param, v_param)
                        
                        # Add new vertex
                        vertex_key = self.mesh.add_vertex(
                            x=point.x,
                            y=point.y,
                            z=point.z,
                            u_param=u,
                            v_param=v
                        )
                        self.uv_to_vertex[uv_key] = vertex_key
                    else:
                        # Reuse existing vertex
                        vertex_key = self.uv_to_vertex[uv_key]
                    
                    # Store mapping for face creation
                    self.vertex_uv_map[(col, row, corner_idx)] = vertex_key
        
        return None
    
    def generate_mesh(self) -> Mesh:
        """Generate the hexagonal mesh projected onto the Brep surface.
        
        Returns
        -------
        Mesh
            The generated hexagonal mesh.
        """
        self.generate_vertices()
        
        # Create faces by connecting vertices of each hexagon
        effective_v_count = self.v_count + 2
        effective_u_count = self.u_count + 1  # Match the vertex generation count
        
        for col in range(effective_u_count):
            # Start from row=1 to skip the first row
            for row in range(1, effective_v_count):
                # Skip the last column for odd rows (they don't need it)
                if col == self.u_count and row % 2 == 1:
                    continue
                
                # Collect vertex keys for this hexagon
                vertex_keys = []
                # Only treat as first column if center is actually at U=0 (even rows in col=0)
                is_first_column = (col == 0 and row % 2 == 0)
                # Only even rows: half-hexagon at u_count
                is_last_column = (col == self.u_count and row % 2 == 0)
                is_last_row = (row == effective_v_count - 1)
                
                # Determine how many corners this hexagon should have
                # Half-hexagons on edges have 4 corners, full hexagons have 6
                # Corner hexagons might have fewer corners
                edge_count = sum([is_first_column, is_last_column, is_last_row])
                if edge_count >= 2:
                    expected_corners = 3  # Corner hexagon (2-4 corners depending on geometry)
                elif edge_count == 1:
                    expected_corners = 4  # Half-hexagon on one edge
                else:
                    expected_corners = 6  # Full hexagon
                
                for corner_idx in range(expected_corners):
                    key = (col, row, corner_idx)
                    if key in self.vertex_uv_map:
                        vertex_key = self.vertex_uv_map[key]
                        vertex_keys.append(vertex_key)
                
                # Filter vertices that are on the face
                # Skip filtering for extra columns beyond original u_count (they extend beyond Brep)
                if col >= self.u_count:
                    # Extra columns: add face without filtering
                    if len(vertex_keys) >= 3:
                        self.mesh.add_face(vertex_keys)
                elif self.full_hexas:
                    # Only add face if all vertices are on the face
                    if len(vertex_keys) == expected_corners and all([self.is_vertex_on_face(v) for v in vertex_keys]):
                        self.mesh.add_face(vertex_keys)
                else:
                    # Add face with filtered vertices
                    face_vertices = self._filtered_face_vertices(vertex_keys)
                    if len(face_vertices) >= 3:
                        self.mesh.add_face(face_vertices)
        
        self.mesh.remove_unused_vertices()
    
    def remove_faces_overlapping_surface(self, cutout_brep, tolerance=0.01) -> None:
        """
        Remove mesh faces that DON'T overlap with a second (smaller) Brep surface.
        
        This keeps only faces whose centroids lie on the cutout surface,
        effectively creating a mesh that matches the cutout region.
        
        Parameters
        ----------
        cutout_brep : rg.Brep
            The smaller Brep surface defining the region to keep.
        tolerance : float, optional
            Maximum distance from cutout surface for a face to be kept.
            Default is 0.01 units.
        """
        import Rhino.Geometry as rg
        
        faces_to_remove = []
        cutout_face = cutout_brep.Faces[0]
        
        print(f"Checking {len(list(self.mesh.faces()))} faces for overlap with cutout surface (tolerance: {tolerance})...")
        
        for face_key in self.mesh.faces():
            # Get face vertices
            face_vertices = self.mesh.face_vertices(face_key)
            
            # Calculate face centroid
            centroid_x = 0.0
            centroid_y = 0.0
            centroid_z = 0.0
            
            for vertex_key in face_vertices:
                coords = self.mesh.vertex_coordinates(vertex_key)
                centroid_x += coords[0]
                centroid_y += coords[1]
                centroid_z += coords[2]
            
            num_verts = len(face_vertices)
            centroid_x /= num_verts
            centroid_y /= num_verts
            centroid_z /= num_verts
            
            # Check if centroid is on the cutout surface
            centroid_point = rg.Point3d(centroid_x, centroid_y, centroid_z)
            
            # ClosestPoint returns (success, u, v)
            success, u, v = cutout_face.ClosestPoint(centroid_point)
            
            if not success:
                # Failed to find closest point - remove this face
                faces_to_remove.append(face_key)
                continue
            
            # Check if the closest point is actually on the face (not just the extended surface)
            relation = cutout_face.IsPointOnFace(u, v)
            
            # INVERTED LOGIC: Remove faces that are NOT on the cutout surface
            if relation != rg.PointFaceRelation.Interior and relation != rg.PointFaceRelation.Boundary:
                # Centroid is NOT on the cutout surface - mark face for removal
                faces_to_remove.append(face_key)
                print(f"  Face {face_key} NOT on cutout - removing")
            else:
                # Get the actual 3D point on the surface
                closest_point = cutout_face.PointAt(u, v)
                distance = centroid_point.DistanceTo(closest_point)
                
                if distance >= tolerance:  # Too far from surface - remove
                    faces_to_remove.append(face_key)
                    print(f"  Face {face_key} too far from cutout (distance: {distance:.6f}) - removing")
                else:
                    print(f"  Face {face_key} ON cutout (distance: {distance:.6f}) - keeping")
        
        # Remove the identified faces
        for face_key in faces_to_remove:
            self.mesh.delete_face(face_key)
        
        print(f"Removed {len(faces_to_remove)} faces NOT overlapping with cutout surface")
        print(f"Kept {len(list(self.mesh.faces()))} faces ON cutout surface")
        
        # Clean up unused vertices
        self.mesh.remove_unused_vertices()
        return self.mesh
