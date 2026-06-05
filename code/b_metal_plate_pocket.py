from compas.geometry import Box, Frame, Vector, Plane
from compas_timber.connections import LMiterJoint
from compas_timber.fabrication import PocketProxy

_ARCH_INCLINATION_THRESHOLD = 0.15


def _is_arch_joint(beam_a, beam_b):
    """Return True when either beam is inclined (arch); used only for dimension selection."""

    def inclination(beam):
        return abs(beam.centerline.direction.unitized().z)

    return (
        inclination(beam_a) > _ARCH_INCLINATION_THRESHOLD
        or inclination(beam_b) > _ARCH_INCLINATION_THRESHOLD
    )


def create_metal_plates(
    timber_model,
    arch_beam_height=0.10,
    arch_plate=(0.040, 0.105, 0.005),
    base_beam_height=0.14,
    base_plate=(0.045, 0.185, 0.005),
):
    """
    Return a list of (Box, beam_a, beam_b) for each metal plate at every LMiterJoint.

    The plate frame is computed with one unified code path for all joint types:
    the averaged beam zaxis is projected onto the plane perpendicular to the
    bisector, which works correctly for both horizontal base beams and inclined
    arch beams without any separate branch.  Arch / base detection is used only
    to select the appropriate plate dimensions and beam height.

    Parameters
    ----------
    timber_model : TimberModel
    arch_beam_height : float
        Cross-section height of arch beams in metres.  Default 0.10 m.
    arch_plate : tuple(float, float, float)
        (width, length, thickness) of the arch metal plate in metres.
    base_beam_height : float
        Cross-section height of base/foundation beams in metres.  Default 0.14 m.
    base_plate : tuple(float, float, float)
        (width, length, thickness) of the base metal plate in metres.

    Returns
    -------
    list of tuple
        Each entry is (compas.geometry.Box, beam_a, beam_b).
    """
    results = []

    if timber_model is None:
        return results

    for joint in timber_model.joints:
        if not isinstance(joint, LMiterJoint):
            continue

        beam_a = joint.beam_a
        beam_b = joint.beam_b
        if beam_a is None or beam_b is None:
            continue

        joint_pt = joint.location

        # Build bisector from flipped beam x-axes so it always points away from the corner.
        vA = Vector(*beam_a.frame.xaxis)
        vB = Vector(*beam_b.frame.xaxis)
        tA, _ = beam_a.endpoint_closest_to_point(joint_pt)
        if tA == "end":
            vA *= -1.0
        tB, _ = beam_b.endpoint_closest_to_point(joint_pt)
        if tB == "end":
            vB *= -1.0

        bisector = vA + vB
        bisector.unitize()

        # Unified plate normal: project the averaged beam zaxis onto the plane ⊥ bisector.
        # This works for base beams (zaxis already ⊥ bisector → projection = identity)
        # and most arch joints. Falls back to yaxis when zaxis ≈ ±bisector (apex joints)
        # because the projection cancels to near-zero in that case.
        def _project_off_bisector(vec):
            dot = vec.x * bisector.x + vec.y * bisector.y + vec.z * bisector.z
            return Vector(
                vec.x - dot * bisector.x,
                vec.y - dot * bisector.y,
                vec.z - dot * bisector.z,
            )

        avg_z = Vector(*beam_a.frame.zaxis) + Vector(*beam_b.frame.zaxis)
        avg_z.unitize()
        normal = _project_off_bisector(avg_z)

        if normal.length < 0.01:
            # zaxis is nearly parallel or anti-parallel to bisector (e.g. arch apex).
            # Use yaxis instead — it is always perpendicular to the beam length.
            avg_y = Vector(*beam_a.frame.yaxis) + Vector(*beam_b.frame.yaxis)
            avg_y.unitize()
            normal = _project_off_bisector(avg_y)

        normal.unitize()

        # Select dimensions only — frame computation above is the same for all joints.
        if _is_arch_joint(beam_a, beam_b):
            beam_height = arch_beam_height
            plate_size = arch_plate
        else:
            beam_height = base_beam_height
            plate_size = base_plate

        for side in [1, -1]:
            plate_frame = Frame.from_plane(Plane(joint_pt, normal))
            plate_frame.translate(normal * side * beam_height / 2)
            plate_frame.yaxis = plate_frame.zaxis.cross(bisector)
            plate_frame.xaxis = bisector

            # Contact face points toward the beam: opposite to the offset direction.
            contact_normal = Vector(
                -normal.x * side, -normal.y * side, -normal.z * side
            )

            results.append(
                (Box(*plate_size, frame=plate_frame), beam_a, beam_b, contact_normal)
            )

    return results


def fillet_brep(brep, radius, tol=0.0001):
    """Fillet all edges of a Rhino Brep.

    Imports Rhino.Geometry at call-time so this module can be edited in VS Code
    without Rhino installed.  The radius is automatically clamped to 40 % of the
    shortest edge to avoid impossible fillets.  Returns the original Brep
    unchanged if filleting fails, with a printed warning.

    Parameters
    ----------
    brep : Rhino.Geometry.Brep
    radius : float
        Desired fillet radius in metres.
    tol : float
        Rhino tolerance used for the fillet operation.  Default 0.001 m.

    Returns
    -------
    Rhino.Geometry.Brep
    """
    import Rhino.Geometry as rg  # available at runtime inside Rhino/Grasshopper

    if radius <= 0:
        return brep

    # Clamp radius so it never exceeds the geometry.
    min_edge_len = min(e.GetLength() for e in brep.Edges)
    safe_radius = min(radius, min_edge_len * 0.4)
    if safe_radius != radius:
        print(f"  Info: fillet radius clamped {radius:.4f} → {safe_radius:.4f} m")

    edge_count = brep.Edges.Count
    radii = [safe_radius] * edge_count

    try:
        results = rg.Brep.CreateFilletEdges(
            brep,
            list(range(edge_count)),
            radii,
            radii,
            rg.BlendType.Fillet,
            rg.RailType.DistanceFromEdge,
            tol,
        )
        if results:
            joined = rg.Brep.JoinBreps(results, tol)
            if joined:
                return joined[0]
            return results[0]
        print(
            f"  Warning: fillet r={safe_radius:.4f} m produced no result — try a smaller radius"
        )
    except Exception as e:
        print(f"  Warning: fillet failed: {e}")

    return brep


def fillet_contact_edges(brep, contact_normal, radius):
    """Fillet only the edges of the plate face that touches the beam.

    Finds the Brep face whose normal is most aligned with *contact_normal*
    (the direction pointing toward the beam) and fillets its 4 edges only.

    Parameters
    ----------
    brep : Rhino.Geometry.Brep
    contact_normal : compas.geometry.Vector
        Direction pointing from the plate toward the beam (opposite to the
        offset direction used when placing the plate).
    radius : float
        Desired fillet radius in metres.  Tolerance is derived automatically
        as 1 % of the clamped radius so it is always well below the radius.

    Returns
    -------
    Rhino.Geometry.Brep
    """
    import Rhino.Geometry as rg

    if radius <= 0:
        return brep

    ref = rg.Vector3d(contact_normal.x, contact_normal.y, contact_normal.z)
    ref.Unitize()

    # Score every face by its alignment with the contact normal.
    # The contact face has the highest dot; the opposite face has the lowest (most negative).
    # Together they give the 8 perimeter edges (4 per large face), excluding the 4 thin edges.
    face_dots = []
    for i in range(brep.Faces.Count):
        face = brep.Faces[i]
        u = (face.Domain(0).Min + face.Domain(0).Max) / 2.0
        v = (face.Domain(1).Min + face.Domain(1).Max) / 2.0
        face_dots.append((face.NormalAt(u, v) * ref, i))

    face_dots.sort(key=lambda t: t[0])
    # Most aligned = contact face; most anti-aligned = opposite face.
    selected_faces = [face_dots[-1][1], face_dots[0][1]]

    edge_set = set()
    for fi in selected_faces:
        for e in brep.Faces[fi].AdjacentEdges():
            edge_set.add(e)
    edge_indices = list(edge_set)
    min_edge_len = min(brep.Edges[e].GetLength() for e in edge_indices)
    safe_radius = min(radius, min_edge_len * 0.4)
    if safe_radius != radius:
        print(f"  Info: fillet radius clamped {radius:.4f} → {safe_radius:.4f} m")

    radii = [safe_radius] * len(edge_indices)

    # Tolerance must be at least two orders of magnitude smaller than the radius.
    # When tol >= radius the operation always returns None.
    fillet_tol = safe_radius * 0.01

    try:
        results = rg.Brep.CreateFilletEdges(
            brep, edge_indices, radii, radii,
            rg.BlendType.Fillet, rg.RailType.DistanceFromEdge, fillet_tol,
        )
        if results:
            joined = rg.Brep.JoinBreps(results, fillet_tol)
            return joined[0] if joined else results[0]
        print(f"  Warning: contact fillet r={safe_radius:.4f} m produced no result")
    except Exception as e:
        print(f"  Warning: contact fillet failed: {e}")

    return brep


def apply_pockets(compas_breps, beam_pairs):
    """
    Apply Pocket features to both beams at each plate location.

    Parameters
    ----------
    compas_breps : list of compas.geometry.Brep
        One COMPAS Brep per plate, already converted from the Rhino geometry.
    beam_pairs : list of (beam_a, beam_b)
        Parallel list matching compas_breps.

    Returns
    -------
    list of (Pocket, beam)
        All pocket/beam pairs that were successfully created, for downstream
        visualisation or export.
    """
    pocket_beam_pairs = []

    for brep, (beam_a, beam_b) in zip(compas_breps, beam_pairs):
        for beam, label in [(beam_a, "a"), (beam_b, "b")]:
            try:
                pocket = PocketProxy.from_volume_and_element(brep, beam)
                beam.add_feature(pocket)
                pocket_beam_pairs.append((pocket, beam))
                print(f"  Pocket added to beam_{label}")
            except Exception as e:
                print(f"  Warning pocket_{label}: {e}")

    return pocket_beam_pairs
