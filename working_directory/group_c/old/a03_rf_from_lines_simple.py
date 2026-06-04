"""
Simple RF System from Lines
============================
Create a reciprocal frame system directly from lines without mesh topology.
This is a simplified version that stores lines as edge attributes directly.
"""

from typing import List
from compas.datastructures import Mesh
from compas.geometry import Line, Point, Vector
from a03_rf_system import RFSystem

try:
    import Rhino.Geometry as rg
    import scriptcontext as sc
    RHINO_AVAILABLE = True
except ImportError:
    RHINO_AVAILABLE = False


def create_rf_from_lines_simple(lines: List, tolerance: float = 0.001) -> RFSystem:
    """
    Create an RF system from lines with minimal mesh structure.
    
    This creates a "fake" mesh where each line becomes an edge with a minimal
    face structure. The RF system will have all your lines but won't have
    proper face topology.
    
    Parameters
    ----------
    lines : list
        Collection of lines (COMPAS Lines or Rhino Guids).
    tolerance : float, optional
        Distance tolerance for vertex merging. Default is 0.001.
        
    Returns
    -------
    RFSystem
        RF system with all input lines as edges.
        
    Example
    -------
    ```python
    from a03_rf_from_lines_simple import create_rf_from_lines_simple
    
    # From Grasshopper
    rf_system = create_rf_from_lines_simple(rhino_line_guids)
    
    # Manually set centerlines (they're already set from input)
    # Just apply modifications
    rf_system.eccentrize_centerlines(eccentricity=0.05)
    ```
    """
    # Convert lines to COMPAS
    compas_lines = _convert_lines_to_compas(lines)
    print(f"Converted {len(compas_lines)} lines")
    
    # Create mesh with vertices and edges
    mesh = Mesh()
    vertex_map = {}
    vertex_counter = 0
    edge_lines = {}  # Store line for each edge (directed)
    
    # Add vertices and track edges
    for line in compas_lines:
        # Find or create start vertex
        v1 = None
        for coord, vkey in vertex_map.items():
            if Point(*coord).distance_to_point(line.start) < tolerance:
                v1 = vkey
                break
        if v1 is None:
            v1 = vertex_counter
            mesh.add_vertex(key=v1, x=line.start.x, y=line.start.y, z=line.start.z)
            vertex_map[(line.start.x, line.start.y, line.start.z)] = v1
            vertex_counter += 1
        
        # Find or create end vertex
        v2 = None
        for coord, vkey in vertex_map.items():
            if Point(*coord).distance_to_point(line.end) < tolerance:
                v2 = vkey
                break
        if v2 is None:
            v2 = vertex_counter
            mesh.add_vertex(key=v2, x=line.end.x, y=line.end.y, z=line.end.z)
            vertex_map[(line.end.x, line.end.y, line.end.z)] = v2
            vertex_counter += 1
        
        # Store the line for this edge (keep direction)
        if v1 != v2:
            # Store with actual direction (v1, v2) not sorted
            edge_key = (v1, v2)
            edge_lines[edge_key] = line
    
    print(f"Created {len(vertex_map)} vertices, {len(edge_lines)} unique edges")
    
    # Create minimal faces to establish edges
    # For each edge, create a tiny triangular face
    face_count = 0
    for (v1, v2), line in edge_lines.items():
        # Create a third vertex slightly offset from the edge midpoint
        mid = Point(
            (line.start.x + line.end.x) / 2,
            (line.start.y + line.end.y) / 2,
            (line.start.z + line.end.z) / 2
        )
        # Offset slightly in Z direction
        v3 = vertex_counter
        mesh.add_vertex(key=v3, x=mid.x, y=mid.y, z=mid.z + 0.001)
        vertex_counter += 1
        
        try:
            mesh.add_face([v1, v2, v3])
            face_count += 1
        except:
            try:
                mesh.add_face([v2, v1, v3])
                face_count += 1
            except:
                pass
    
    print(f"Created {face_count} minimal faces")
    print(f"Final mesh: {len(list(mesh.vertices()))} vertices, {len(list(mesh.edges()))} edges")
    
    # Create RF system
    rf_system = RFSystem(mesh)
    
    # Manually set centerlines from original lines
    for edge in mesh.edges():
        # Try both directions
        if edge in edge_lines:
            mesh.edge_attribute(edge, "centerline", edge_lines[edge])
        elif (edge[1], edge[0]) in edge_lines:
            # Reverse the line to match edge direction
            original_line = edge_lines[(edge[1], edge[0])]
            reversed_line = Line(original_line.end, original_line.start)
            mesh.edge_attribute(edge, "centerline", reversed_line)
        else:
            # Fallback: use mesh edge line
            mesh.edge_attribute(edge, "centerline", mesh.edge_line(edge))
    
    # Set normals and neighborhoods (skip boundary check since all are "boundary")
    for edge in mesh.edges():
        # Simple normal: perpendicular to edge in XY plane
        edge_line = mesh.edge_attribute(edge, "centerline")
        if edge_line:
            direction = edge_line.direction
            # Create perpendicular in XY plane
            normal = Vector(-direction.y, direction.x, 0)
            if normal.length < 1e-6:
                normal = Vector(0, 0, 1)
            else:
                normal.unitize()
            mesh.edge_attribute(edge, "normal", normal)
    
    print("RF system created successfully")
    return rf_system


def _convert_lines_to_compas(lines: List) -> List[Line]:
    """Convert Rhino lines to COMPAS lines."""
    compas_lines = []
    
    for line in lines:
        if isinstance(line, Line):
            compas_lines.append(line)
            continue
        
        if RHINO_AVAILABLE:
            rhino_line = None
            
            if hasattr(line, 'ToString') and '-' in str(line):
                rhino_obj = sc.doc.Objects.FindId(line)
                if rhino_obj:
                    rhino_line = rhino_obj.Geometry
            elif isinstance(line, (rg.Line, rg.LineCurve)):
                rhino_line = line
            
            if rhino_line:
                if isinstance(rhino_line, rg.LineCurve):
                    rhino_line = rhino_line.Line
                
                if isinstance(rhino_line, rg.Line):
                    start = Point(rhino_line.From.X, rhino_line.From.Y, rhino_line.From.Z)
                    end = Point(rhino_line.To.X, rhino_line.To.Y, rhino_line.To.Z)
                    compas_lines.append(Line(start, end))
    
    return compas_lines