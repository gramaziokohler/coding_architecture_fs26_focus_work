from typing import Optional, List

from compas.datastructures import Mesh
from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector

# Version for debugging - increment to force reload
__version__ = "1.0.1"


class RFSystemHybrid:
    """
    Hybrid Reciprocal-frame system that combines centerlines from two different RF systems:
    - Inner beams from one RF system (e.g., Timo's with advanced transformations)
    - Boundary beams from another RF system (e.g., standard RF for containment)
    
    This allows you to use different processing approaches for interior vs boundary beams.
    """

    def __init__(self, inner_mesh: Mesh, boundary_mesh: Mesh):
        """
        Initialize hybrid RF system with two meshes.
        
        Parameters
        ----------
        inner_mesh : Mesh
            Mesh containing the inner beam centerlines (e.g., from RFSystemTimo).
        boundary_mesh : Mesh
            Mesh containing the boundary beam centerlines (e.g., from standard RFSystem).
        """
        self.inner_mesh = inner_mesh
        self.boundary_mesh = boundary_mesh
        self.timber_model = None
        
        # Ensure all edges have normals (boundary edges might not have them)
        self._ensure_edge_normals()
    
    def _ensure_edge_normals(self):
        """Ensure all edges in both meshes have normal vectors."""
        from compas.geometry import Vector
        
        # Check boundary mesh edges
        for edge in self.boundary_mesh.edges():
            normal = self.boundary_mesh.edge_attribute(edge, "normal")
            if normal is None:
                # Compute normal from adjacent face(s)
                if self.boundary_mesh.is_edge_on_boundary(edge):
                    # Boundary edge: use the single adjacent face normal
                    faces = self.boundary_mesh.edge_faces(edge)
                    face = faces[0] if faces[0] is not None else faces[1]
                    if face is not None:
                        normal = self.boundary_mesh.face_normal(face)
                    else:
                        normal = Vector(0, 0, 1)  # Default fallback
                else:
                    # Interior edge: average of two face normals
                    face_a, face_b = self.boundary_mesh.edge_faces(edge)
                    normal_a = self.boundary_mesh.face_normal(face_a)
                    normal_b = self.boundary_mesh.face_normal(face_b)
                    normal = normal_a + normal_b
                    normal.unitize()
                
                self.boundary_mesh.edge_attribute(edge, "normal", normal)
        
        # Check inner mesh edges
        for edge in self.inner_mesh.edges():
            normal = self.inner_mesh.edge_attribute(edge, "normal")
            if normal is None:
                # Compute normal from adjacent face(s)
                if self.inner_mesh.is_edge_on_boundary(edge):
                    faces = self.inner_mesh.edge_faces(edge)
                    face = faces[0] if faces[0] is not None else faces[1]
                    if face is not None:
                        normal = self.inner_mesh.face_normal(face)
                    else:
                        normal = Vector(0, 0, 1)
                else:
                    face_a, face_b = self.inner_mesh.edge_faces(edge)
                    normal_a = self.inner_mesh.face_normal(face_a)
                    normal_b = self.inner_mesh.face_normal(face_b)
                    normal = normal_a + normal_b
                    normal.unitize()
                
                self.inner_mesh.edge_attribute(edge, "normal", normal)

    @property
    def centerlines(self) -> List[Line]:
        """
        Get combined centerlines: boundary beams from boundary_mesh + ALL beams from inner_mesh.
        """
        centerlines = []
        
        # Add boundary beams from boundary_mesh
        boundary_from_boundary_mesh = 0
        for edge in self.boundary_mesh.edges():
            if self.boundary_mesh.is_edge_on_boundary(edge):
                centerline = self.boundary_mesh.edge_attribute(edge, "centerline")
                if centerline is not None:
                    centerlines.append(centerline)
                    boundary_from_boundary_mesh += 1
        
        # Add ALL beams from inner_mesh - count by is_boundary attribute
        boundary_from_inner_mesh = 0
        interior_from_inner_mesh = 0
        for edge in self.inner_mesh.edges():
            centerline = self.inner_mesh.edge_attribute(edge, "centerline")
            if centerline is not None:
                centerlines.append(centerline)
                # Check if edge has is_boundary attribute
                is_boundary = self.inner_mesh.edge_attribute(edge, "is_boundary")
                if is_boundary:
                    boundary_from_inner_mesh += 1
                else:
                    interior_from_inner_mesh += 1
        
        total_boundary = boundary_from_boundary_mesh + boundary_from_inner_mesh
        print(f"Hybrid centerlines: {len(centerlines)} total ({total_boundary} boundary + {interior_from_inner_mesh} interior)")
        return centerlines

    @property
    def boundary_centerlines(self) -> List[Line]:
        """Get only the boundary centerlines from boundary_mesh."""
        centerlines = []
        for edge in self.boundary_mesh.edges():
            if self.boundary_mesh.is_edge_on_boundary(edge):
                centerline = self.boundary_mesh.edge_attribute(edge, "centerline")
                if centerline is not None:
                    centerlines.append(centerline)
        return centerlines

    def copy(self) -> "RFSystemHybrid":
        """Create a copy of the hybrid RF system."""
        return RFSystemHybrid(
            inner_mesh=self.inner_mesh.copy(),
            boundary_mesh=self.boundary_mesh.copy()
        )

    @property
    def inner_centerlines(self) -> List[Line]:
        """
        Get ALL centerlines from inner_mesh - no filtering.
        """
        centerlines = []
        total_edges = 0
        skipped_no_centerline = 0
        
        for edge in self.inner_mesh.edges():
            total_edges += 1
            
            # Include ALL edges - no filtering
            centerline = self.inner_mesh.edge_attribute(edge, "centerline")
            if centerline is not None:
                centerlines.append(centerline)
            else:
                skipped_no_centerline += 1
        
        print(f"Inner mesh analysis: {total_edges} total edges, {skipped_no_centerline} without centerline, {len(centerlines)} inner centerlines")
        return centerlines

    def get_combined_mesh(self) -> Mesh:
        """
        Create combined mesh: inner mesh + boundary-only edges from boundary mesh.
        
        Returns
        -------
        Mesh
            Combined mesh with all beams.
        """
        from compas.geometry import Vector
        
        print("=" * 60)
        print(f"Creating combined mesh... (v{__version__})")
        print("=" * 60)
        
        # Start with a copy of the inner mesh (has all interior beams)
        combined = self.inner_mesh.copy()
        inner_edge_count = len(list(combined.edges()))
        
        # Debug: Check for None centerlines and deleted flags in source meshes
        inner_none_count = sum(1 for e in self.inner_mesh.edges() if self.inner_mesh.edge_attribute(e, "centerline") is None)
        inner_deleted_count = sum(1 for e in self.inner_mesh.edges() if self.inner_mesh.edge_attribute(e, "deleted"))
        print(f"Inner mesh: {inner_edge_count} edges, {inner_none_count} with None centerline, {inner_deleted_count} marked deleted")
        
        # Collect boundary-only edges (edges that are on boundary in boundary mesh)
        boundary_only_centerlines = []
        for edge in self.boundary_mesh.edges():
            if self.boundary_mesh.is_edge_on_boundary(edge):
                centerline = self.boundary_mesh.edge_attribute(edge, "centerline")
                normal = self.boundary_mesh.edge_attribute(edge, "normal")
                if centerline:
                    boundary_only_centerlines.append((centerline, normal if normal else Vector(0, 0, 1)))
        
        print(f"Found {len(boundary_only_centerlines)} boundary beams to add")
        
        # Add boundary beams as new edges to the combined mesh
        # We'll add them to existing vertices where possible
        boundary_added = 0
        for centerline, normal in boundary_only_centerlines:
            # Find or create vertices
            start_coords = (centerline.start.x, centerline.start.y, centerline.start.z)
            end_coords = (centerline.end.x, centerline.end.y, centerline.end.z)
            
            # Find matching vertices in combined mesh (within tolerance)
            u = None
            v = None
            tolerance = 0.01
            
            for vkey in combined.vertices():
                v_coords = combined.vertex_coordinates(vkey)
                if abs(v_coords[0] - start_coords[0]) < tolerance and \
                   abs(v_coords[1] - start_coords[1]) < tolerance and \
                   abs(v_coords[2] - start_coords[2]) < tolerance:
                    u = vkey
                if abs(v_coords[0] - end_coords[0]) < tolerance and \
                   abs(v_coords[1] - end_coords[1]) < tolerance and \
                   abs(v_coords[2] - end_coords[2]) < tolerance:
                    v = vkey
            
            # Create vertices if not found
            if u is None:
                u = combined.add_vertex(x=start_coords[0], y=start_coords[1], z=start_coords[2])
            if v is None:
                v = combined.add_vertex(x=end_coords[0], y=end_coords[1], z=end_coords[2])
            
            # Add edge if it doesn't exist
            if not combined.has_edge((u, v)) and u != v:
                # Find a third vertex that's close to this edge (to avoid star pattern)
                third = None
                min_dist = float('inf')
                
                # Find the closest vertex to the midpoint of this edge
                mid_x = (start_coords[0] + end_coords[0]) / 2
                mid_y = (start_coords[1] + end_coords[1]) / 2
                mid_z = (start_coords[2] + end_coords[2]) / 2
                
                for vkey in combined.vertices():
                    if vkey != u and vkey != v:
                        v_coords = combined.vertex_coordinates(vkey)
                        dist = ((v_coords[0] - mid_x)**2 +
                               (v_coords[1] - mid_y)**2 +
                               (v_coords[2] - mid_z)**2)**0.5
                        if dist < min_dist:
                            min_dist = dist
                            third = vkey
                
                if third is not None:
                    try:
                        combined.add_face([u, v, third])
                        combined.edge_attribute((u, v), "centerline", centerline)
                        combined.edge_attribute((u, v), "normal", normal)
                        boundary_added += 1
                    except:
                        pass
        
        print(f"Added {boundary_added} boundary beams")
        
        # Fix any edges without centerlines (helper edges from triangular faces)
        # BUT: Do NOT fix edges that were intentionally marked as deleted
        from compas.geometry import Line, Point
        all_edges = list(combined.edges())
        fixed = 0
        skipped_deleted = 0
        
        # Debug: check how many edges have deleted flag in source meshes
        inner_deleted_count = sum(1 for e in self.inner_mesh.edges() if self.inner_mesh.edge_attribute(e, "deleted"))
        boundary_deleted_count = sum(1 for e in self.boundary_mesh.edges() if self.boundary_mesh.edge_attribute(e, "deleted"))
        print(f"DEBUG: Inner mesh has {inner_deleted_count} deleted edges, Boundary mesh has {boundary_deleted_count} deleted edges")
        
        for edge in all_edges:
            if combined.edge_attribute(edge, "centerline") is None:
                # Check if this edge was explicitly marked as deleted
                is_deleted = combined.edge_attribute(edge, "deleted")
                
                if is_deleted:
                    # This is an intentionally deleted edge - skip it
                    skipped_deleted += 1
                    print(f"DEBUG: Skipping deleted edge {edge}")
                else:
                    # This is a helper edge from triangulation - fix it
                    u, v = edge
                    u_coords = combined.vertex_coordinates(u)
                    v_coords = combined.vertex_coordinates(v)
                    centerline = Line(Point(*u_coords), Point(*v_coords))
                    combined.edge_attribute(edge, "centerline", centerline)
                    
                    if combined.edge_attribute(edge, "normal") is None:
                        combined.edge_attribute(edge, "normal", Vector(0, 0, 1))
                    fixed += 1
        
        if fixed > 0:
            print(f"Fixed {fixed} helper edges")
        if skipped_deleted > 0:
            print(f"Preserved {skipped_deleted} intentionally deleted edges")
        
        print(f"Combined mesh: {len(list(combined.vertices()))} vertices, {len(all_edges)} edges (all with centerlines)")
        
        return combined

    @classmethod
    def from_rf_systems(cls, inner_rf_system, boundary_rf_system) -> "RFSystemHybrid":
        """
        Create a hybrid system from two RFSystem instances.
        
        Parameters
        ----------
        inner_rf_system : RFSystem or RFSystemTimo
            RF system for interior beams (e.g., with advanced transformations applied).
        boundary_rf_system : RFSystem
            RF system for boundary beams (e.g., standard RF system).
            
        Returns
        -------
        RFSystemHybrid
            A new hybrid system combining both.
            
        Example
        -------
        >>> from a03_rf_system import RFSystem
        >>> from a03_rf_system_timo import RFSystem as RFSystemTimo
        >>> 
        >>> # Create and process inner beams with Timo's system
        >>> inner_rf = RFSystemTimo(mesh.copy())
        >>> inner_rf.create_rf_datastructure()
        >>> inner_rf.eccentrize_centerlines_hexagonal(offset=0.5)
        >>> inner_rf.extend_centerlines(extensions_pos=0.2)
        >>> 
        >>> # Create boundary beams with standard system
        >>> boundary_rf = RFSystem(mesh.copy())
        >>> boundary_rf.create_rf_datastructure()
        >>> boundary_rf.eccentrize_centerlines(eccentricity=0.1)
        >>> 
        >>> # Combine them
        >>> hybrid = RFSystemHybrid.from_rf_systems(inner_rf, boundary_rf)
        >>> all_centerlines = hybrid.centerlines
        """
        return cls(inner_rf_system.mesh, boundary_rf_system.mesh)


def create_hybrid_rf_system(mesh: Mesh, 
                            inner_transformations: callable = None,
                            boundary_transformations: callable = None) -> RFSystemHybrid:
    """
    Convenience function to create a hybrid RF system with different transformations
    applied to inner and boundary beams.
    
    Parameters
    ----------
    mesh : Mesh
        The base mesh to process.
    inner_transformations : callable, optional
        Function that takes an RFSystem and applies transformations to it.
        Example: lambda rf: rf.eccentrize_centerlines_hexagonal(0.5)
    boundary_transformations : callable, optional
        Function that takes an RFSystem and applies transformations to it.
        Example: lambda rf: rf.eccentrize_centerlines(0.1)
        
    Returns
    -------
    RFSystemHybrid
        A hybrid system with separately processed inner and boundary beams.
        
    Example
    -------
    >>> from a03_rf_system import RFSystem
    >>> from a03_rf_system_timo import RFSystem as RFSystemTimo
    >>> 
    >>> def process_inner(rf):
    ...     rf.create_rf_datastructure()
    ...     rf.eccentrize_centerlines_hexagonal(offset=0.5)
    ...     rf.extend_centerlines(extensions_pos=0.2)
    ...     return rf
    >>> 
    >>> def process_boundary(rf):
    ...     rf.create_rf_datastructure()
    ...     rf.eccentrize_centerlines(eccentricity=0.1)
    ...     return rf
    >>> 
    >>> hybrid = create_hybrid_rf_system(
    ...     mesh,
    ...     inner_transformations=process_inner,
    ...     boundary_transformations=process_boundary
    ... )
    """
    # Import here to avoid circular dependencies
    from a03_rf_system import RFSystem
    from a03_rf_system_timo import RFSystem as RFSystemTimo
    
    # Process inner beams with Timo's system
    inner_rf = RFSystemTimo(mesh.copy())
    if inner_transformations:
        inner_transformations(inner_rf)
    else:
        inner_rf.create_rf_datastructure()
    
    # Process boundary beams with standard system
    boundary_rf = RFSystem(mesh.copy())
    if boundary_transformations:
        boundary_transformations(boundary_rf)
    else:
        boundary_rf.create_rf_datastructure()
    
    return RFSystemHybrid(inner_rf.mesh, boundary_rf.mesh)