def classify_arch_and_foundation(boundary_lines, tolerance=0.1):
    """Filters boundary centerlines into Arch and Foundation curves based on Z-height."""
    if not boundary_lines:
        return [], []

    # 1. Find the lowest Z-coordinate
    min_z = float('inf')
    for line in boundary_lines:
        # Assuming COMPAS lines are passed in
        min_z = min(min_z, line.start.z, line.end.z) 

    arches = []
    foundations = []

    # 2. Classify based on distance from the global minimum Z
    for line in boundary_lines:
        start_is_ground = abs(line.start.z - min_z) <= tolerance
        end_is_ground = abs(line.end.z - min_z) <= tolerance
        
        # If both ends are on the ground, it acts as a foundation
        if start_is_ground and end_is_ground:
            foundations.append(line)
        else:
            arches.append(line)

    return arches, foundations