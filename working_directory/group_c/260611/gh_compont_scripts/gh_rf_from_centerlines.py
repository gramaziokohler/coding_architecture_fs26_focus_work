# venv: ca-fs26-final-project

"""
Create a new RFSystemHybrid from centerlines, filtering out invalid lines.

Inputs:
    centerlines: List of Rhino.Geometry.Line objects (from interactive editor)
    base_surface: (Optional) Rhino surface/brep to extract normals from at beam midpoints
    boundary_tolerance: (Optional) Distance tolerance to detect boundary beams (default: 0.1)
    
Outputs:
    rf_system: A new RFSystemHybrid with only valid centerlines
    boundary_centerlines: List of centerlines classified as boundary beams (for visual inspection)
    interior_centerlines: List of centerlines classified as interior beams (for visual inspection)
    valid_count: Number of valid centerlines used
    skipped_count: Number of invalid centerlines skipped
"""

from compas_rhino.devtools import DevTools
DevTools.ensure_path()
ghenv.Component.Message = "RF from Centerlines"

import System
import Rhino
import scriptcontext as sc
from compas.datastructures import Mesh
from compas.geometry import Point, Line, Vector
from compas_rhino.conversions import line_to_compas
from a03_rf_system_hybrid import RFSystemHybrid

# Initialize outputs
rf_system = None
boundary_centerlines = []
interior_centerlines = []
valid_count = 0
skipped_count = 0

# Handle optional inputs
if 'base_surface' not in dir():
    base_surface = None
if 'boundary_tolerance' not in dir():
    boundary_tolerance = 0.1

# Handle input - centerlines might be a single item or list
if not hasattr(centerlines, '__iter__'):
    centerlines = [centerlines] if centerlines else []

if centerlines:
    try:
        print("=" * 60)
        print("Creating RF System from Centerlines")
        print("=" * 60)
        print(f"Input: {len(centerlines)} centerlines")
        
        # Convert Rhino lines to COMPAS lines and filter invalid ones
        valid_lines = []
        for i, item in enumerate(centerlines):
            # Handle Guid references - convert to geometry
            r_line = item
            if isinstance(item, System.Guid):
                rhino_obj = sc.doc.Objects.FindId(item)
                if rhino_obj:
                    r_line = rhino_obj.Geometry
                else:
                    skipped_count += 1
                    continue
            
            # Handle LineCurve - extract the Line
            if isinstance(r_line, Rhino.Geometry.LineCurve):
                r_line = r_line.Line
            
            # Check if it's a valid Rhino Line
            if isinstance(r_line, Rhino.Geometry.Line):
                if r_line.Length >= 0.001:  # Not zero-length
                    c_line = line_to_compas(r_line)
                    valid_lines.append(c_line)
                    valid_count += 1
                else:
                    skipped_count += 1
            else:
                skipped_count += 1
        
        print(f"Valid centerlines: {valid_count}")
        print(f"Skipped invalid: {skipped_count}")
        
        if valid_count == 0:
            print("ERROR: No valid centerlines found!")
        else:
            # Create new mesh from centerlines
            inner_mesh = Mesh()
            vertex_map = {}
            tolerance = 0.01
            
            def get_or_create_vertex(mesh, point, vertex_map):
                """Get existing vertex or create new one."""
                coords = (round(point.x / tolerance) * tolerance,
                         round(point.y / tolerance) * tolerance,
                         round(point.z / tolerance) * tolerance)
                
                if coords in vertex_map:
                    return vertex_map[coords]
                
                vkey = mesh.add_vertex(x=point.x, y=point.y, z=point.z)
                vertex_map[coords] = vkey
                return vkey
            
            # Two-pass approach: First create all vertices, then create edges
            # Pass 1: Create all vertices
            edge_data = []  # Store (u, v, line) tuples
            for line in valid_lines:
                u = get_or_create_vertex(inner_mesh, line.start, vertex_map)
                v = get_or_create_vertex(inner_mesh, line.end, vertex_map)
                if u != v:
                    edge_data.append((u, v, line))
            
            print(f"Created {len(list(inner_mesh.vertices()))} vertices")
            
            # Pass 2: Create faces and edges
            edges_added = 0
            for u, v, line in edge_data:
                if not inner_mesh.has_edge((u, v)):
                    # Find a third vertex to create a face
                    mid = Point(
                        (line.start.x + line.end.x) / 2,
                        (line.start.y + line.end.y) / 2,
                        (line.start.z + line.end.z) / 2
                    )
                    
                    min_dist = float('inf')
                    third = None
                    for vkey in inner_mesh.vertices():
                        if vkey != u and vkey != v:
                            v_coords = inner_mesh.vertex_coordinates(vkey)
                            dist = ((v_coords[0] - mid.x)**2 +
                                   (v_coords[1] - mid.y)**2 +
                                   (v_coords[2] - mid.z)**2)**0.5
                            if dist < min_dist:
                                min_dist = dist
                                third = vkey
                    
                    if third is not None:
                        try:
                            face_key = inner_mesh.add_face([u, v, third])
                            inner_mesh.edge_attribute((u, v), "centerline", line)
                            
                            # Determine normal based on whether we have a base surface
                            normal = None
                            if base_surface:
                                # Evaluate surface normal at beam midpoint
                                try:
                                    # Handle Guid reference - convert to geometry
                                    srf_geom = base_surface
                                    if isinstance(base_surface, System.Guid):
                                        rhino_obj = sc.doc.Objects.FindId(base_surface)
                                        if rhino_obj:
                                            srf_geom = rhino_obj.Geometry
                                    
                                    # Get the first face if it's a Brep
                                    if isinstance(srf_geom, Rhino.Geometry.Brep):
                                        if srf_geom.Faces.Count > 0:
                                            srf_geom = srf_geom.Faces[0]
                                    
                                    # Calculate beam midpoint
                                    mid_pt = Rhino.Geometry.Point3d(
                                        (line.start.x + line.end.x) / 2,
                                        (line.start.y + line.end.y) / 2,
                                        (line.start.z + line.end.z) / 2
                                    )
                                    
                                    # Find closest point on surface and get UV parameters
                                    success, u_param, v_param = srf_geom.ClosestPoint(mid_pt)
                                    if success:
                                        # Evaluate surface normal at UV parameters
                                        srf_normal = srf_geom.NormalAt(u_param, v_param)
                                        # Convert to COMPAS Vector
                                        normal = Vector(srf_normal.X, srf_normal.Y, srf_normal.Z)
                                        normal.unitize()
                                except Exception as e:
                                    print(f"Warning: Could not get surface normal: {e}")
                           
                           # Fallback to face normal or Z-up
                            if normal is None:
                                try:
                                    normal = inner_mesh.face_normal(face_key)
                                except:
                                    normal = Vector(0, 0, 1)
                            
                            inner_mesh.edge_attribute((u, v), "normal", normal)
                            edges_added += 1
                        except Exception as e:
                            print(f"Warning: Could not add edge: {e}")
           
            print(f"Created inner mesh: {len(list(inner_mesh.vertices()))} vertices, {edges_added} edges")
           
            # Add RF topology: next_edge and prev_edge for each edge based on shared vertices
            # Only consider edges that have centerlines (not helper edges from triangulation)
            print("Adding RF topology (next_edge/prev_edge)...")
            valid_edges = [e for e in inner_mesh.edges() if inner_mesh.edge_attribute(e, "centerline") is not None]
            print(f"Found {len(valid_edges)} valid edges with centerlines")
            
            for edge in valid_edges:
                u, v = edge
                # Find edges that share vertex v (next edges) - only valid edges
                next_edges = [e for e in inner_mesh.vertex_edges(v)
                             if e != edge and inner_mesh.edge_attribute(e, "centerline") is not None]
                if next_edges:
                    inner_mesh.edge_attribute(edge, "next_edge", next_edges[0])
                
                # Find edges that share vertex u (prev edges) - only valid edges
                prev_edges = [e for e in inner_mesh.vertex_edges(u)
                             if e != edge and inner_mesh.edge_attribute(e, "centerline") is not None]
                if prev_edges:
                    inner_mesh.edge_attribute(edge, "prev_edge", prev_edges[0])
            
            print("RF topology added")
           
           # Detect boundary beams based on proximity to surface edge
            if base_surface:
                print(f"Detecting boundary beams (tolerance: {boundary_tolerance})...")
               
               # Get surface geometry
                srf_geom = base_surface
                if isinstance(base_surface, System.Guid):
                    rhino_obj = sc.doc.Objects.FindId(base_surface)
                    if rhino_obj:
                        srf_geom = rhino_obj.Geometry
               
               # Get the first face if it's a Brep
                if isinstance(srf_geom, Rhino.Geometry.Brep):
                    if srf_geom.Faces.Count > 0:
                        srf_geom = srf_geom.Faces[0]
               
               # Get surface boundary curves
                boundary_curves = []
                try:
                    # For a BrepFace, get the outer loop
                   if hasattr(srf_geom, 'OuterLoop'):
                       outer_loop = srf_geom.OuterLoop
                       boundary_curves = [outer_loop.To3dCurve()]
                   # For a Surface, get the ISO curves at the edges
                   elif hasattr(srf_geom, 'IsoCurve'):
                       domain_u = srf_geom.Domain(0)
                       domain_v = srf_geom.Domain(1)
                       boundary_curves = [
                           srf_geom.IsoCurve(0, domain_u.Min),
                           srf_geom.IsoCurve(0, domain_u.Max),
                           srf_geom.IsoCurve(1, domain_v.Min),
                           srf_geom.IsoCurve(1, domain_v.Max)
                       ]
                except Exception as e:
                    print(f"Warning: Could not extract boundary curves: {e}")
               
               # Check each edge to see if it's near the boundary
                for edge in inner_mesh.edges():
                    centerline = inner_mesh.edge_attribute(edge, "centerline")
                    if centerline:
                       # Check both endpoints of the centerline
                        start_pt = Rhino.Geometry.Point3d(centerline.start.x, centerline.start.y, centerline.start.z)
                        end_pt = Rhino.Geometry.Point3d(centerline.end.x, centerline.end.y, centerline.end.z)
                       
                        is_boundary = False
                        for boundary_curve in boundary_curves:
                            if boundary_curve:
                               # Check distance from both endpoints to boundary curve
                                success_start, t_start = boundary_curve.ClosestPoint(start_pt)
                                success_end, t_end = boundary_curve.ClosestPoint(end_pt)
                               
                                if success_start and success_end:
                                    dist_start = start_pt.DistanceTo(boundary_curve.PointAt(t_start))
                                    dist_end = end_pt.DistanceTo(boundary_curve.PointAt(t_end))
                                   
                                   # If both endpoints are close to boundary, it's a boundary beam
                                    if dist_start < boundary_tolerance and dist_end < boundary_tolerance:
                                        is_boundary = True
                                        break
                       
                       # Mark edge as boundary or interior
                        inner_mesh.edge_attribute(edge, "is_boundary", is_boundary)
                       
                       # Add to appropriate output list
                        if is_boundary:
                            boundary_centerlines.append(centerline)
                        else:
                            interior_centerlines.append(centerline)
               
                print(f"Found {len(boundary_centerlines)} boundary beams and {len(interior_centerlines)} interior beams")
            else:
               # No surface provided - all beams are interior
                print("No surface provided - all beams classified as interior")
                for edge in inner_mesh.edges():
                    centerline = inner_mesh.edge_attribute(edge, "centerline")
                    if centerline:
                        inner_mesh.edge_attribute(edge, "is_boundary", False)
                        interior_centerlines.append(centerline)
           
           # Create empty boundary mesh
            boundary_mesh = Mesh()
           
           # Create the hybrid system
            rf_system = RFSystemHybrid(inner_mesh, boundary_mesh)
           
            print("=" * 60)
            print(f"RF System created successfully!")
            print(f"Total beams: {len(rf_system.centerlines)}")
            print(f"Boundary: {len(boundary_centerlines)}, Interior: {len(interior_centerlines)}")
            print("=" * 60)
    
    except Exception as e:
        print(f"ERROR creating RF system: {e}")
        import traceback
        traceback.print_exc()
        rf_system = None

else:
    print("ERROR: No centerlines provided")