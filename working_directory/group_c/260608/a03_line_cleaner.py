import Rhino.Geometry as rg
from compas_rhino.conversions import line_to_rhino


def _is_inside_boundary(point, boundary_lines):
    """Ray casting in 2D (XY projection): returns True if point is inside the boundary.
    Shoots a ray from point in +X direction and counts boundary crossings.
    Odd = inside, Even = outside.
    """
    mx, my = point.X, point.Y
    crossings = 0
    for seg in boundary_lines:
        ax, ay = seg.From.X, seg.From.Y
        bx, by = seg.To.X, seg.To.Y
        if (ay > my) != (by > my):
            t = (my - ay) / (by - ay)
            x_intersect = ax + t * (bx - ax)
            if x_intersect > mx:
                crossings += 1
    return crossings % 2 == 1


def extract_lines_from_hybrid(boundary_rf_system, inner_rf_system, intersection_tolerance=0.01, parallel_tolerance=0.1, extension_length=0.5, min_line_length=0.1):
    """
    Extract lines from a hybrid RF system setup.
    """
    lines = []

    boundary_count = 0
    for edge in boundary_rf_system.mesh.edges():
        if boundary_rf_system.mesh.is_edge_on_boundary(edge):
            centerline = boundary_rf_system.mesh.edge_line(edge)
            if centerline is not None:
                lines.append(centerline)
                boundary_count += 1

    inner_centerlines = inner_rf_system.centerlines
    lines.extend(inner_centerlines)
    inner_count = len(inner_centerlines)

    print(f"Line cleaner: extracted {boundary_count} boundary lines + {inner_count} inner lines = {len(lines)} total")

    rhino_lines = [line_to_rhino(line) for line in lines]
    print(f"Converted {len(rhino_lines)} lines to Rhino geometry")

    rhino_boundary_lines = rhino_lines[:boundary_count]
    rhino_inner_lines = rhino_lines[boundary_count:]

    inner_line_intersections = {}

    for i, inner_line in enumerate(rhino_inner_lines):
        inner_line_intersections[i] = []
        for boundary_line in rhino_boundary_lines:
            success, param_a, param_b = rg.Intersect.Intersection.LineLine(
                inner_line,
                boundary_line,
                intersection_tolerance,
                False
            )
            if success:
                point_a = inner_line.PointAt(param_a)
                point_b = boundary_line.PointAt(param_b)
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
    trimmed_inner_lines = []
    trimmed_count = 0

    for i, inner_line in enumerate(rhino_inner_lines):
        if inner_line not in cleaned_inner_lines:
            continue

        intersections = inner_line_intersections[i]

        if len(intersections) == 0:
            trimmed_inner_lines.append(inner_line)
        elif len(intersections) == 1:
            point = intersections[0]
            m1 = rg.Point3d(
                (inner_line.From.X + point.X) / 2,
                (inner_line.From.Y + point.Y) / 2,
                (inner_line.From.Z + point.Z) / 2
            )
            m2 = rg.Point3d(
                (point.X + inner_line.To.X) / 2,
                (point.Y + inner_line.To.Y) / 2,
                (point.Z + inner_line.To.Z) / 2
            )
            if _is_inside_boundary(m1, rhino_boundary_lines):
                new_line = rg.Line(inner_line.From, point)
            elif _is_inside_boundary(m2, rhino_boundary_lines):
                new_line = rg.Line(point, inner_line.To)
            else:
                dist1 = inner_line.From.DistanceTo(point)
                dist2 = inner_line.To.DistanceTo(point)
                new_line = rg.Line(inner_line.From, point) if dist1 > dist2 else rg.Line(point, inner_line.To)
            # If the trimmed segment is too short the intersection is near the endpoint
            # and the line only barely clips the boundary — keep the full line instead.
            if new_line.Length < float(min_line_length):
                print(f"Step2 line {i}: 1 intersection too close to endpoint (kept={new_line.Length:.4f}) — keeping full line")
                trimmed_inner_lines.append(inner_line)
            else:
                trimmed_inner_lines.append(new_line)
            trimmed_count += 1

        elif len(intersections) == 2:
            point_a = intersections[0]
            point_b = intersections[1]
            if point_a.DistanceTo(point_b) < float(min_line_length):
                removed_count += 1
                print(f"Removed inner line {i}: trimmed segment too short ({point_a.DistanceTo(point_b):.4f})")
                continue
            # Check if the midpoint of the trimmed segment is inside the boundary.
            # If outside, the two intersections are spurious — fall back to 1-intersection logic.
            mid = rg.Point3d(
                (point_a.X + point_b.X) / 2,
                (point_a.Y + point_b.Y) / 2,
                (point_a.Z + point_b.Z) / 2,
            )
            segment_length = point_a.DistanceTo(point_b)
            if _is_inside_boundary(mid, rhino_boundary_lines) and segment_length >= float(min_line_length):
                new_line = rg.Line(point_a, point_b)
                trimmed_inner_lines.append(new_line)
                trimmed_count += 1
            else:
                # Segment is outside — use the intersection closest to the line midpoint
                # and apply 1-intersection logic
                line_mid = inner_line.PointAt(0.5)
                point = point_a if point_a.DistanceTo(line_mid) < point_b.DistanceTo(line_mid) else point_b
                m1 = rg.Point3d(
                    (inner_line.From.X + point.X) / 2,
                    (inner_line.From.Y + point.Y) / 2,
                    (inner_line.From.Z + point.Z) / 2,
                )
                m2 = rg.Point3d(
                    (point.X + inner_line.To.X) / 2,
                    (point.Y + inner_line.To.Y) / 2,
                    (point.Z + inner_line.To.Z) / 2,
                )
                if _is_inside_boundary(m1, rhino_boundary_lines):
                    new_line = rg.Line(inner_line.From, point)
                elif _is_inside_boundary(m2, rhino_boundary_lines):
                    new_line = rg.Line(point, inner_line.To)
                else:
                    dist1 = inner_line.From.DistanceTo(point)
                    dist2 = inner_line.To.DistanceTo(point)
                    new_line = rg.Line(inner_line.From, point) if dist1 > dist2 else rg.Line(point, inner_line.To)
                print(f"Line {i}: 2 intersections outside boundary — fell back to 1-intersection logic")
                trimmed_inner_lines.append(new_line)
                trimmed_count += 1

    print(f"Cleaning step 2: Trimmed {trimmed_count} inner lines to boundary intersections")

    # Step 3: Remove inner lines parallel and close to boundary lines
    final_inner_lines = []
    parallel_removed_count = 0

    for inner_line in trimmed_inner_lines:
        is_parallel_to_boundary = False
        inner_vec = rg.Vector3d(inner_line.To - inner_line.From)
        if inner_vec.Length == 0:
            continue
        inner_vec.Unitize()

        for boundary_line in rhino_boundary_lines:
            boundary_vec = rg.Vector3d(boundary_line.To - boundary_line.From)
            if boundary_vec.Length == 0:
                continue
            boundary_vec.Unitize()
            dot_product = abs(inner_vec * boundary_vec)
            if dot_product >= 0.9:
                inner_mid = inner_line.PointAt(0.5)
                t = boundary_line.ClosestParameter(inner_mid)
                closest_point = boundary_line.PointAt(t)
                distance = inner_mid.DistanceTo(closest_point)
                if distance <= parallel_tolerance:
                    is_parallel_to_boundary = True
                    parallel_removed_count += 1
                    print(f"Removed inner line parallel to boundary (distance: {distance:.3f}, alignment: {dot_product:.2f})")
                    break

        if not is_parallel_to_boundary:
            final_inner_lines.append(inner_line)

    print(f"Cleaning step 3: Removed {parallel_removed_count} inner lines parallel to boundaries (tolerance: {parallel_tolerance})")

    # Step 4: Extend inner lines that are close to boundaries
    if extension_length is None or extension_length <= 0:
        extended_inner_lines = list(final_inner_lines)
        extended_count = 0
        print(f"Cleaning step 4: Skipped (extension disabled)")
    else:
        extended_inner_lines = []
        extended_count = 0

        for inner_line in final_inner_lines:
            new_from = inner_line.From
            new_to = inner_line.To

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

            if closest_boundary_from and min_distance_from > intersection_tolerance:
                closest_point = closest_boundary_from.PointAt(closest_param_from)
                if inner_line.From.DistanceTo(closest_point) <= extension_length:
                    new_from = closest_point
                    extended_count += 1

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

            if closest_boundary_to and min_distance_to > intersection_tolerance:
                closest_point = closest_boundary_to.PointAt(closest_param_to)
                if inner_line.To.DistanceTo(closest_point) <= extension_length:
                    new_to = closest_point
                    extended_count += 1

            extended_inner_lines.append(rg.Line(new_from, new_to))

        print(f"Cleaning step 4: Extended {extended_count} endpoints to reach boundaries (max extension: {extension_length})")

    # Final filter: remove inner lines shorter than min_line_length
    if min_line_length and float(min_line_length) > 0:
        kept = []
        for l in extended_inner_lines:
            if l.Length >= float(min_line_length):
                kept.append(l)
            else:
                print(f"Final filter: removed line length={l.Length:.4f} from=({l.From.X:.2f},{l.From.Y:.2f}) to=({l.To.X:.2f},{l.To.Y:.2f})")
        removed = len(extended_inner_lines) - len(kept)
        extended_inner_lines = kept
        if removed > 0:
            print(f"Final filter: removed {removed} inner lines shorter than {min_line_length}m")

    rhino_points = []
    for points in inner_line_intersections.values():
        rhino_points.extend(points)

    print(f"Total intersections found: {len(rhino_points)} (tolerance: {intersection_tolerance})")
    print(f"Final output: {len(rhino_boundary_lines) + len(extended_inner_lines)} lines ({len(rhino_boundary_lines)} boundary + {len(extended_inner_lines)} inner)")

    return rhino_boundary_lines, extended_inner_lines, rhino_points
