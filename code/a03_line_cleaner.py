import Rhino.Geometry as rg
from compas_rhino.conversions import line_to_rhino


def extract_lines_from_hybrid(boundary_rf_system, inner_rf_system, intersection_tolerance=0.01, parallel_tolerance=0.1, extension_length=0.5):
    """
    Extract lines from a hybrid RF system setup.
    
    Extracts lines and finds intersections between inner and boundary lines.
    
    Parameters
    ----------
    boundary_rf_system : RFSystem
        RF system containing boundary beams. Only boundary edges will be extracted.
    inner_rf_system : RFSystem
        RF system containing inner beams. Uses .centerlines property.
    intersection_tolerance : float, optional
        Distance tolerance for detecting intersections. Default is 0.01.
    parallel_tolerance : float, optional
        Distance tolerance for detecting parallel lines close to boundaries. Default is 0.1.
    extension_length : float, optional
        Maximum length to extend lines to reach boundaries. Default is 0.5.
        
    Returns
    -------
    tuple
        - lines: List[Rhino.Geometry.Line] - Combined list of Rhino lines
        - points: List[Rhino.Geometry.Point3d] - Intersection points between inner and boundary lines
    """
    lines = []
    
    # Extract boundary lines from boundary_rf_system (original mesh edges)
    boundary_count = 0
    for edge in boundary_rf_system.mesh.edges():
        if boundary_rf_system.mesh.is_edge_on_boundary(edge):
            centerline = boundary_rf_system.mesh.edge_line(edge)
            if centerline is not None:
                lines.append(centerline)
                boundary_count += 1
    
    # Extract all lines from inner_rf_system using its centerlines property
    # This automatically handles filtering (e.g., quad closing edges) and returns processed lines
    inner_centerlines = inner_rf_system.centerlines
    lines.extend(inner_centerlines)
    inner_count = len(inner_centerlines)
    
    print(f"Line cleaner: extracted {boundary_count} boundary lines + {inner_count} inner lines = {len(lines)} total")
    
    # Convert COMPAS lines to Rhino geometry
    rhino_lines = [line_to_rhino(line) for line in lines]
    
    print(f"Converted {len(rhino_lines)} lines to Rhino geometry")
    
    # Find intersections between inner and boundary Rhino lines
    rhino_boundary_lines = rhino_lines[:boundary_count]  # First boundary_count lines are boundary
    rhino_inner_lines = rhino_lines[boundary_count:]     # Rest are inner lines
    
    # Count intersections per inner line
    inner_line_intersections = {}  # {line_index: [intersection_points]}
    
    for i, inner_line in enumerate(rhino_inner_lines):
        inner_line_intersections[i] = []
        
        for boundary_line in rhino_boundary_lines:
            # Use Rhino's line-line intersection
            success, param_a, param_b = rg.Intersect.Intersection.LineLine(
                inner_line,
                boundary_line,
                intersection_tolerance,
                False  # Don't require overlap
            )
            
            if success:
                # Get points on both lines at the intersection parameters
                point_a = inner_line.PointAt(param_a)
                point_b = boundary_line.PointAt(param_b)
                
                # Check that both parameters are within line bounds (0 to 1)
                # AND that the distance between points is within tolerance
                if (0 <= param_a <= 1 and 0 <= param_b <= 1 and
                    point_a.DistanceTo(point_b) <= intersection_tolerance):
                    inner_line_intersections[i].append(point_a)
    
    # Step 1: Remove inner lines with more than 2 intersections
    cleaned_inner_lines = []
    removed_count = 0
    
    for i, inner_line in enumerate(rhino_inner_lines):
        intersection_count = len(inner_line_intersections[i])
        if intersection_count <= 2:
            cleaned_inner_lines.append(inner_line)
        else:
            removed_count += 1
            print(f"Removed inner line {i} with {intersection_count} boundary intersections")
    
    print(f"Cleaning step 1: Removed {removed_count} inner lines with >2 boundary intersections")
    print(f"Remaining inner lines: {len(cleaned_inner_lines)}")
    
    # Step 2: Trim inner lines to boundary intersections
    # For each inner line, find all intersection points and trim to the innermost points
    trimmed_inner_lines = []
    trimmed_count = 0
    
    for i, inner_line in enumerate(rhino_inner_lines):
        # Skip if this line was removed in step 1
        if inner_line not in cleaned_inner_lines:
            continue
        
        intersections = inner_line_intersections[i]
        
        if len(intersections) == 0:
            # No intersections - keep original line (assumed to be fully inside)
            trimmed_inner_lines.append(inner_line)
        elif len(intersections) == 1:
            # One intersection - determine which endpoint is INSIDE using 2D projection
            point = intersections[0]
            
            # Project to XY plane (Z=0)
            point_2d = rg.Point3d(point.X, point.Y, 0)
            from_2d = rg.Point3d(inner_line.From.X, inner_line.From.Y, 0)
            to_2d = rg.Point3d(inner_line.To.X, inner_line.To.Y, 0)
            
            # Create 2D boundary polyline for containment test
            boundary_points_2d = []
            for boundary_line in rhino_boundary_lines:
                pt = rg.Point3d(boundary_line.From.X, boundary_line.From.Y, 0)
                if len(boundary_points_2d) == 0 or boundary_points_2d[-1].DistanceTo(pt) > 0.001:
                    boundary_points_2d.append(pt)
            
            # Close the boundary if needed
            if len(boundary_points_2d) > 0:
                first_pt = boundary_points_2d[0]
                last_pt = rg.Point3d(rhino_boundary_lines[-1].To.X, rhino_boundary_lines[-1].To.Y, 0)
                if first_pt.DistanceTo(last_pt) > 0.001:
                    boundary_points_2d.append(last_pt)
                # Ensure closed
                if boundary_points_2d[0].DistanceTo(boundary_points_2d[-1]) > 0.001:
                    boundary_points_2d.append(boundary_points_2d[0])
            
            # Create 2D polyline curve
            boundary_curve_2d = None
            if len(boundary_points_2d) > 2:
                try:
                    boundary_curve_2d = rg.Polyline(boundary_points_2d).ToNurbsCurve()
                except:
                    pass
            
            # Test which endpoint is inside using 2D containment
            from_inside = False
            to_inside = False
            
            if boundary_curve_2d:
                # Use Rhino's point-in-curve test
                from_relation = boundary_curve_2d.Contains(from_2d, rg.Plane.WorldXY, intersection_tolerance)
                to_relation = boundary_curve_2d.Contains(to_2d, rg.Plane.WorldXY, intersection_tolerance)
                
                from_inside = (from_relation == rg.PointContainment.Inside or
                              from_relation == rg.PointContainment.Coincident)
                to_inside = (to_relation == rg.PointContainment.Inside or
                            to_relation == rg.PointContainment.Coincident)
            
            # Apply 2D test result to 3D line
            if from_inside and not to_inside:
                # From is inside - keep From to intersection
                new_line = rg.Line(inner_line.From, point)
            elif to_inside and not from_inside:
                # To is inside - keep intersection to To
                new_line = rg.Line(point, inner_line.To)
            elif from_inside and to_inside:
                # Both inside - keep original (shouldn't happen with 1 intersection)
                new_line = inner_line
            else:
                # Neither inside - fallback: keep longer segment
                dist_from = inner_line.From.DistanceTo(point)
                dist_to = inner_line.To.DistanceTo(point)
                if dist_from > dist_to:
                    new_line = rg.Line(inner_line.From, point)
                else:
                    new_line = rg.Line(point, inner_line.To)
            
            trimmed_inner_lines.append(new_line)
            trimmed_count += 1
            
        elif len(intersections) == 2:
            # Two intersections - trim to segment between them
            point_a = intersections[0]
            point_b = intersections[1]
            
            # Create line between the two intersection points
            new_line = rg.Line(point_a, point_b)
            trimmed_inner_lines.append(new_line)
            trimmed_count += 1
    
    print(f"Cleaning step 2: Trimmed {trimmed_count} inner lines to boundary intersections")
    
    # Step 3: Remove inner lines that are parallel and close to boundary lines
    final_inner_lines = []
    parallel_removed_count = 0
    
    for inner_line in trimmed_inner_lines:
        is_parallel_to_boundary = False
        
        # Get inner line direction vector
        inner_vec = rg.Vector3d(inner_line.To - inner_line.From)
        if inner_vec.Length == 0:
            continue
        inner_vec.Unitize()
        
        for boundary_line in rhino_boundary_lines:
            # Get boundary line direction vector
            boundary_vec = rg.Vector3d(boundary_line.To - boundary_line.From)
            if boundary_vec.Length == 0:
                continue
            boundary_vec.Unitize()
            
            # Check if vectors are parallel (dot product close to 1 or -1)
            dot_product = abs(inner_vec * boundary_vec)  # Absolute value to handle both directions
            
            if dot_product >= 0.9:  # 80% alignment threshold
                # Vectors are parallel - now check distance
                # Get closest point on boundary line to inner line's midpoint
                inner_mid = inner_line.PointAt(0.5)
                t = boundary_line.ClosestParameter(inner_mid)
                closest_point = boundary_line.PointAt(t)
                distance = inner_mid.DistanceTo(closest_point)
                
                if distance <= parallel_tolerance:
                    # Inner line is parallel and close to this boundary line
                    is_parallel_to_boundary = True
                    parallel_removed_count += 1
                    print(f"Removed inner line parallel to boundary (distance: {distance:.3f}, alignment: {dot_product:.2f})")
                    break
        
        if not is_parallel_to_boundary:
            final_inner_lines.append(inner_line)
    
    print(f"Cleaning step 3: Removed {parallel_removed_count} inner lines parallel to boundaries (tolerance: {parallel_tolerance})")
    
    # Step 4: Extend inner lines that are close to boundaries but don't quite reach them
    # Skip if extension_length is None or 0
    if extension_length is None or extension_length <= 0:
        extended_inner_lines = final_inner_lines
        extended_count = 0
        print(f"Cleaning step 4: Skipped (extension disabled)")
    else:
        extended_inner_lines = []
        extended_count = 0
    
    for inner_line in final_inner_lines:
        new_from = inner_line.From
        new_to = inner_line.To
        from_extended = False
        to_extended = False
        
        # Check From endpoint
        min_distance_from = float('inf')
        closest_boundary_from = None
        closest_param_from = 0
        
        for boundary_line in rhino_boundary_lines:
            t = boundary_line.ClosestParameter(inner_line.From)
            closest_point = boundary_line.PointAt(t)
            distance = inner_line.From.DistanceTo(closest_point)
            
            if distance < min_distance_from and distance <= parallel_tolerance:
                min_distance_from = distance
                closest_boundary_from = boundary_line
                closest_param_from = t
        
        # Extend From endpoint if close to boundary
        if closest_boundary_from and min_distance_from > intersection_tolerance:
            closest_point = closest_boundary_from.PointAt(closest_param_from)
            extension_dist = inner_line.From.DistanceTo(closest_point)
            if extension_dist <= extension_length:
                new_from = closest_point
                from_extended = True
                extended_count += 1
                print(f"Extended inner line From by {extension_dist:.3f} to reach boundary")
        
        # Check To endpoint
        min_distance_to = float('inf')
        closest_boundary_to = None
        closest_param_to = 0
        
        for boundary_line in rhino_boundary_lines:
            t = boundary_line.ClosestParameter(inner_line.To)
            closest_point = boundary_line.PointAt(t)
            distance = inner_line.To.DistanceTo(closest_point)
            
            if distance < min_distance_to and distance <= parallel_tolerance:
                min_distance_to = distance
                closest_boundary_to = boundary_line
                closest_param_to = t
        
        # Extend To endpoint if close to boundary
        if closest_boundary_to and min_distance_to > intersection_tolerance:
            closest_point = closest_boundary_to.PointAt(closest_param_to)
            extension_dist = inner_line.To.DistanceTo(closest_point)
            if extension_dist <= extension_length:
                new_to = closest_point
                to_extended = True
                extended_count += 1
                print(f"Extended inner line To by {extension_dist:.3f} to reach boundary")
        
        # Create new line with extended endpoints
        new_line = rg.Line(new_from, new_to)
        extended_inner_lines.append(new_line)
        
        print(f"Cleaning step 4: Extended {extended_count} inner lines to reach boundaries (max extension: {extension_length})")
    
    # Combine boundary lines with extended inner lines
    cleaned_lines = rhino_boundary_lines + extended_inner_lines
    
    # Collect all intersection points for visualization
    rhino_points = []
    for points in inner_line_intersections.values():
        rhino_points.extend(points)
    
    print(f"Total intersections found: {len(rhino_points)} (tolerance: {intersection_tolerance})")
    print(f"Final output: {len(cleaned_lines)} lines ({len(rhino_boundary_lines)} boundary + {len(extended_inner_lines)} inner)")
    
    return cleaned_lines, rhino_points
