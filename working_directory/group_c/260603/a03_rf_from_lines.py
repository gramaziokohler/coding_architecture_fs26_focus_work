"""
RF System from Lines
====================
Create a reciprocal frame system directly from Grasshopper/Rhino lines,
bypassing the mesher step. This is useful when you want to manually define
the RF topology or import it from a parametric model.
"""

from typing import List, Tuple, Optional, Union
from compas.datastructures import Mesh
from compas.geometry import Line, Point, Vector
from a03_rf_system import RFSystem

try:
    import Rhino.Geometry as rg
    import scriptcontext as sc
    RHINO_AVAILABLE = True
except ImportError:
    RHINO_AVAILABLE = False


class RFFromLines:
    """
    Create an RF system directly from a collection of lines.
    
    This class constructs a COMPAS mesh from lines where each line becomes
    an edge in the mesh. The mesh topology is inferred from line connectivity
    (shared endpoints). Once the mesh is created, it can be used with the
    standard RFSystem class.
    
    Usage Example
    -------------
    ```python
    from compas.geometry import Line, Point
    from a03_rf_from_lines import RFFromLines
    
    # Define lines from Grasshopper/Rhino
    lines = [
        Line(Point(0, 0, 0), Point(1, 0, 0)),
        Line(Point(1, 0, 0), Point(1, 1, 0)),
        Line(Point(1, 1, 0), Point(0, 1, 0)),
        Line(Point(0, 1, 0), Point(0, 0, 0)),
    ]
    
    # Create RF system from lines
    rf_builder = RFFromLines(lines, tolerance=0.01)
    rf_system = rf_builder.create_rf_system()
    
    # Now use standard RF methods
    rf_system.create_rf_datastructure()
    rf_system.eccentrize_centerlines(eccentricity=0.05)
    ```
    """
    
    def __init__(self, lines: List, tolerance: float = 0.001):
        """
        Initialize the RF builder from lines.
        
        Parameters
        ----------
        lines : list
            Collection of lines that define the RF system edges.
            Can be COMPAS Lines, Rhino Guids (references), or Rhino geometry objects.
            Lines with shared endpoints (within tolerance) will be connected.
        tolerance : float, optional
            Distance tolerance for considering two points as the same vertex.
            Default is 0.001.
        """
        self.lines = self._convert_lines_to_compas(lines)
        self.tolerance = tolerance
        self.mesh = None
        
    def _convert_lines_to_compas(self, lines: List) -> List[Line]:
        """
        Convert input lines to COMPAS Line objects.
        
        Handles:
        - COMPAS Line objects (pass through)
        - Rhino Guid objects (fetch geometry from document)
        - Rhino Line/LineCurve objects (convert to COMPAS)
        
        Parameters
        ----------
        lines : list
            Input lines in various formats.
            
        Returns
        -------
        list of Line
            COMPAS Line objects.
        """
        compas_lines = []
        skipped_count = 0
        
        for i, line in enumerate(lines):
            # Already a COMPAS Line
            if isinstance(line, Line):
                compas_lines.append(line)
                continue
            
            # Handle Rhino geometry
            if RHINO_AVAILABLE:
                rhino_line = None
                
                # If it's a Guid, get the geometry from the document
                if hasattr(line, 'ToString') and '-' in str(line):  # Likely a Guid
                    rhino_obj = sc.doc.Objects.FindId(line)
                    if rhino_obj:
                        rhino_line = rhino_obj.Geometry
                # Direct Rhino geometry
                elif isinstance(line, (rg.Line, rg.LineCurve)):
                    rhino_line = line
                
                # Convert Rhino geometry to COMPAS
                if rhino_line:
                    if isinstance(rhino_line, rg.LineCurve):
                        rhino_line = rhino_line.Line
                    
                    if isinstance(rhino_line, rg.Line):
                        start = Point(rhino_line.From.X, rhino_line.From.Y, rhino_line.From.Z)
                        end = Point(rhino_line.To.X, rhino_line.To.Y, rhino_line.To.Z)
                        compas_lines.append(Line(start, end))
                        continue
            
            # If we get here, we couldn't convert the line
            skipped_count += 1
            print(f"Warning: Could not convert line {i} of type {type(line)}")
        
        print(f"Converted {len(compas_lines)} lines, skipped {skipped_count}")
        return compas_lines
    
    def create_rf_system(self) -> RFSystem:
        """
        Create an RF system from the input lines.
        
        Returns
        -------
        RFSystem
            A new RF system with the mesh topology derived from the lines.
        """
        self.mesh = self._build_mesh_from_lines()
        rf_system = RFSystem(self.mesh)
        rf_system.create_rf_datastructure()
        return rf_system
    
    def _build_mesh_from_lines(self) -> Mesh:
        """
        Build a COMPAS mesh from the input lines.
        
        For RF systems, we need to preserve ALL edges, not just those forming closed faces.
        The strategy is:
        1. Collect all unique vertices
        2. Build connectivity graph
        3. Find all faces (closed loops)
        4. For edges not in faces, create degenerate triangular faces to preserve them
        
        Returns
        -------
        Mesh
            A COMPAS mesh representing the line network.
        """
        # Step 1: Add all unique vertices and build connectivity
        vertex_map = {}  # Maps (x, y, z) tuples to vertex keys
        vertex_coords = {}  # Maps vertex keys to coordinates
        edges = []  # List of (v1, v2) tuples
        vertex_counter = 0
        
        for line in self.lines:
            # Get or create vertices
            v1_key = None
            v2_key = None
            
            for coord_tuple, vkey in vertex_map.items():
                existing_point = Point(*coord_tuple)
                if line.start.distance_to_point(existing_point) < self.tolerance:
                    v1_key = vkey
                if line.end.distance_to_point(existing_point) < self.tolerance:
                    v2_key = vkey
            
            if v1_key is None:
                v1_key = vertex_counter
                vertex_map[(line.start.x, line.start.y, line.start.z)] = v1_key
                vertex_coords[v1_key] = (line.start.x, line.start.y, line.start.z)
                vertex_counter += 1
            
            if v2_key is None:
                v2_key = vertex_counter
                vertex_map[(line.end.x, line.end.y, line.end.z)] = v2_key
                vertex_coords[v2_key] = (line.end.x, line.end.y, line.end.z)
                vertex_counter += 1
            
            if v1_key != v2_key:
                edges.append((v1_key, v2_key))
        
        # Step 2: Build adjacency for face detection
        adjacency = {}
        for v1, v2 in edges:
            if v1 not in adjacency:
                adjacency[v1] = []
            if v2 not in adjacency:
                adjacency[v2] = []
            adjacency[v1].append(v2)
            adjacency[v2].append(v1)
        
        # Step 3: Find faces (closed loops)
        faces = self._find_all_faces_from_edges(edges, adjacency)
        
        # Step 4: Create mesh
        mesh = Mesh()
        
        # Add vertices
        for vkey, coords in vertex_coords.items():
            mesh.add_vertex(key=vkey, x=coords[0], y=coords[1], z=coords[2])
        
        print(f"Created mesh with {len(vertex_coords)} vertices")
        print(f"Found {len(faces)} faces from {len(edges)} edges")
        
        # Add faces - this creates the edges
        faces_added = 0
        for face in faces:
            if len(face) >= 3:
                try:
                    mesh.add_face(face)
                    faces_added += 1
                except Exception as e:
                    print(f"Failed to add face {face}: {e}")
        
        print(f"Added {faces_added} faces to mesh")
        print(f"Mesh now has {len(list(mesh.edges()))} edges")
        
        # Step 5: For any edges not yet in the mesh, create proper triangular faces
        # We need to find a third vertex to create a valid triangle
        edges_in_mesh = set()
        for edge in mesh.edges():
            edges_in_mesh.add(tuple(sorted(edge)))
        
        missing_edges = 0
        added_edges = 0
        
        for v1, v2 in edges:
            edge_key = tuple(sorted([v1, v2]))
            if edge_key not in edges_in_mesh:
                missing_edges += 1
                
                # Find a third vertex to create a proper triangle
                # Try neighbors of v1 or v2, or any other vertex
                third_vertex = None
                
                # First try: find a common neighbor
                if v1 in adjacency and v2 in adjacency:
                    v1_neighbors = set(adjacency[v1])
                    v2_neighbors = set(adjacency[v2])
                    common = v1_neighbors & v2_neighbors
                    if common:
                        third_vertex = list(common)[0]
                
                # Second try: use any neighbor of v1
                if third_vertex is None and v1 in adjacency:
                    for neighbor in adjacency[v1]:
                        if neighbor != v2:
                            third_vertex = neighbor
                            break
                
                # Third try: use any neighbor of v2
                if third_vertex is None and v2 in adjacency:
                    for neighbor in adjacency[v2]:
                        if neighbor != v1:
                            third_vertex = neighbor
                            break
                
                # Last resort: use any other vertex
                if third_vertex is None:
                    for vkey in vertex_coords.keys():
                        if vkey != v1 and vkey != v2:
                            third_vertex = vkey
                            break
                
                # Create the triangle
                if third_vertex is not None:
                    try:
                        mesh.add_face([v1, v2, third_vertex])
                        edges_in_mesh.add(edge_key)
                        added_edges += 1
                    except Exception as e:
                        # Try reverse order
                        try:
                            mesh.add_face([v2, v1, third_vertex])
                            edges_in_mesh.add(edge_key)
                            added_edges += 1
                        except:
                            print(f"Failed to add face for edge ({v1}, {v2}) with third vertex {third_vertex}: {e}")
        
        print(f"Found {missing_edges} missing edges, successfully added {added_edges} via triangular faces")
        print(f"Final mesh has {len(list(mesh.edges()))} edges")
        
        return mesh
    
    def _find_all_faces_from_edges(self, edges: List[Tuple[int, int]],
                                   adjacency: dict) -> List[List[int]]:
        """
        Find faces (closed loops) from edges using a simple cycle detection algorithm.
        
        Parameters
        ----------
        edges : list of tuple
            List of (v1, v2) edge tuples.
        adjacency : dict
            Adjacency dictionary mapping vertices to their neighbors.
            
        Returns
        -------
        list of list of int
            List of faces, where each face is a list of vertex keys.
        """
        faces = []
        visited_edges = set()
        
        # Try to find cycles starting from each edge
        for v1, v2 in edges:
            edge_key = tuple(sorted([v1, v2]))
            if edge_key in visited_edges:
                continue
            
            # Try to find a cycle starting with this edge
            cycle = self._find_minimal_cycle(v1, v2, adjacency, visited_edges)
            
            if cycle and len(cycle) >= 3:
                faces.append(cycle)
                # Mark all edges in this cycle as visited
                for i in range(len(cycle)):
                    e1, e2 = cycle[i], cycle[(i + 1) % len(cycle)]
                    visited_edges.add(tuple(sorted([e1, e2])))
        
        return faces
    
    def _find_minimal_cycle(self, start: int, second: int, adjacency: dict,
                           visited_edges: set) -> Optional[List[int]]:
        """
        Find the minimal cycle starting with edge (start, second).
        
        Parameters
        ----------
        start : int
            Starting vertex.
        second : int
            Second vertex in the path.
        adjacency : dict
            Adjacency dictionary.
        visited_edges : set
            Set of already visited edges.
            
        Returns
        -------
        list of int or None
            The cycle if found, None otherwise.
        """
        # Use BFS to find shortest path back to start
        path = [start, second]
        current = second
        max_depth = 20
        
        for _ in range(max_depth):
            if current not in adjacency:
                return None
            
            neighbors = adjacency[current]
            
            # Look for a neighbor that closes the loop
            for neighbor in neighbors:
                if neighbor == start and len(path) >= 3:
                    # Found a cycle!
                    return path
                
                # Avoid going backwards or revisiting
                if neighbor in path:
                    continue
                
                edge_key = tuple(sorted([current, neighbor]))
                if edge_key in visited_edges:
                    continue
                
                # Continue the path with the first valid neighbor
                path.append(neighbor)
                current = neighbor
                break
            else:
                # No valid neighbor found
                return None
        
        return None


def create_rf_from_lines(lines: List, tolerance: float = 0.001) -> RFSystem:
    """
    Convenience function to create an RF system from lines in one step.
    
    Parameters
    ----------
    lines : list
        Collection of lines that define the RF system edges.
        Can be COMPAS Lines, Rhino Guids (references), or Rhino geometry objects.
    tolerance : float, optional
        Distance tolerance for considering two points as the same vertex.
        Default is 0.001.
        
    Returns
    -------
    RFSystem
        A new RF system with initialized datastructure.
        
    Example
    -------
    ```python
    # From COMPAS Lines
    from compas.geometry import Line, Point
    from a03_rf_from_lines import create_rf_from_lines
    
    lines = [
        Line(Point(0, 0, 0), Point(1, 0, 0)),
        Line(Point(1, 0, 0), Point(1, 1, 0)),
        Line(Point(1, 1, 0), Point(0, 1, 0)),
        Line(Point(0, 1, 0), Point(0, 0, 0)),
    ]
    
    rf_system = create_rf_from_lines(lines)
    rf_system.eccentrize_centerlines(eccentricity=0.05)
    
    # From Rhino/Grasshopper (pass Guid list directly)
    rf_system = create_rf_from_lines(rhino_line_guids)
    ```
    """
    builder = RFFromLines(lines, tolerance)
    return builder.create_rf_system()