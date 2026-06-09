"""
Custom COMPAS Timber L-lap joint with centerline-based cutoff planes.

Copy this file into a project folder that is on the Python path and import
``CutoffLLapJoint`` wherever joint rules are defined.
"""

from compas.geometry import Brep
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyhedron
from compas.geometry import Vector
from compas.geometry import intersection_plane_plane_plane
from compas.geometry import intersection_line_line
from compas.tolerance import TOL
from compas_timber.connections import LLapJoint
from compas_timber.errors import BeamJoiningError
from compas_timber.fabrication import JackRafterCutProxy
from compas_timber.fabrication import LapProxy


class CutoffLLapJoint(LLapJoint):
    """L-lap joint that does not extend beam blanks beyond their centerlines.

    The standard COMPAS Timber ``LLapJoint`` extends both beams to the opposing
    beam side face before creating the lap and cutoff features. At very shallow
    L-angles this can produce long artificial extensions. This class keeps the
    standard lap features, but limits blank extensions to planes placed at the
    centerline intersection plus an offset.

    Parameters
    ----------
    beam_a : :class:`compas_timber.elements.Beam`
        The first beam to be joined.
    beam_b : :class:`compas_timber.elements.Beam`
        The second beam to be joined.
    cutoff_offset : float, optional
        Distance from the centerline intersection toward the joint-side end of
        each beam. A value of ``0.0`` cuts at the centerline intersection.
    cutoff_offset_a : float, optional
        Override ``cutoff_offset`` for beam_a.
    cutoff_offset_b : float, optional
        Override ``cutoff_offset`` for beam_b.
    limit_lap_removal : bool, optional
        If True, the lap negative volumes are clipped at the same cutoff planes.
    invert_lap_removal_plane : bool, optional
        If True, invert the clipping plane normal for the lap removal volumes.
    extend_lap_removal_to_inner_edge : bool, optional
        If True, extend the lap negative volume sideways to the closest inner
        edge of the receiving beam face to mill away thin slivers.
    flip_lap_side : bool, optional
        Passed through to ``LLapJoint``.
    cut_plane_bias : float, optional
        Passed through to ``LLapJoint``.
    """

    def __init__(
        self,
        beam_a=None,
        beam_b=None,
        flip_lap_side=False,
        cut_plane_bias=0.5,
        cutoff_offset=0.04,
        cutoff_offset_a=None,
        cutoff_offset_b=None,
        limit_lap_removal=True,
        invert_lap_removal_plane=False,
        extend_lap_removal_to_inner_edge=True,
        **kwargs
    ):
        super(CutoffLLapJoint, self).__init__(
            beam_a=beam_a,
            beam_b=beam_b,
            flip_lap_side=flip_lap_side,
            cut_plane_bias=cut_plane_bias,
            **kwargs
        )
        self.cutoff_offset = cutoff_offset
        self.cutoff_offset_a = cutoff_offset_a
        self.cutoff_offset_b = cutoff_offset_b
        self.limit_lap_removal = limit_lap_removal
        self.invert_lap_removal_plane = invert_lap_removal_plane
        self.extend_lap_removal_to_inner_edge = extend_lap_removal_to_inner_edge
        self._extension_plane_a = None
        self._extension_plane_b = None
        self.debug_negative_volume_a = None
        self.debug_negative_volume_b = None
        self.debug_clip_status = []

    @property
    def __data__(self):
        data = super(CutoffLLapJoint, self).__data__
        data["cutoff_offset"] = self.cutoff_offset
        data["cutoff_offset_a"] = self.cutoff_offset_a
        data["cutoff_offset_b"] = self.cutoff_offset_b
        data["limit_lap_removal"] = self.limit_lap_removal
        data["invert_lap_removal_plane"] = self.invert_lap_removal_plane
        data["extend_lap_removal_to_inner_edge"] = self.extend_lap_removal_to_inner_edge
        return data

    def add_extensions(self):
        """Extend the blanks only up to the custom cutoff planes."""

        assert self.beam_a and self.beam_b

        start_a, start_b = None, None
        try:
            start_a, end_a = self.beam_a.extension_to_plane(self.extension_plane_a)
            start_b, end_b = self.beam_b.extension_to_plane(self.extension_plane_b)
        except AttributeError as error:
            geometries = [self.extension_plane_b] if start_a is not None else [self.extension_plane_a]
            raise BeamJoiningError(self.elements, self, debug_info=str(error), debug_geometries=geometries)
        except Exception as error:
            raise BeamJoiningError(self.elements, self, debug_info=str(error))

        tol = TOL.absolute
        self.beam_a.add_blank_extension(start_a + tol, end_a + tol, self.guid)
        self.beam_b.add_blank_extension(start_b + tol, end_b + tol, self.guid)

    def add_features(self):
        """Add cutoff and bounded lap features to both beams."""

        assert self.beam_a and self.beam_b

        if self.features:
            self.beam_a.remove_features(self.features)
            self.beam_b.remove_features(self.features)

        negative_volume_a, negative_volume_b = self._create_negative_volumes(self.cut_plane_bias)

        if self.limit_lap_removal:
            clipping_plane_a = self.extension_plane_b
            clipping_plane_b = self.extension_plane_a
            if self.invert_lap_removal_plane:
                clipping_plane_a = self._inverted_plane(clipping_plane_a)
                clipping_plane_b = self._inverted_plane(clipping_plane_b)
            negative_volume_a = self._clip_polyhedron_to_plane(negative_volume_a, clipping_plane_a, self.debug_clip_status)
            negative_volume_b = self._clip_polyhedron_to_plane(negative_volume_b, clipping_plane_b, self.debug_clip_status)

        if self.extend_lap_removal_to_inner_edge:
            negative_volume_a = self._extend_polyhedron_to_beam_edge(
                negative_volume_a,
                self.beam_a,
                self.beam_b,
                self.ref_side_index_a,
                self.centerline_intersection,
                clipping_plane_a if self.limit_lap_removal else self.extension_plane_b,
                self.debug_clip_status,
            )
            negative_volume_b = self._extend_polyhedron_to_beam_edge(
                negative_volume_b,
                self.beam_b,
                self.beam_a,
                self.ref_side_index_b,
                self.centerline_intersection,
                clipping_plane_b if self.limit_lap_removal else self.extension_plane_a,
                self.debug_clip_status,
            )

        self.debug_negative_volume_a = negative_volume_a
        self.debug_negative_volume_b = negative_volume_b

        lap_feature_a = LapProxy.from_volume_and_beam(negative_volume_a, self.beam_a, ref_side_index=self.ref_side_index_a)
        lap_feature_b = LapProxy.from_volume_and_beam(negative_volume_b, self.beam_b, ref_side_index=self.ref_side_index_b)

        cut_feature_a = JackRafterCutProxy.from_plane_and_beam(self.cutting_plane_a, self.beam_a)
        cut_feature_b = JackRafterCutProxy.from_plane_and_beam(self.cutting_plane_b, self.beam_b)

        features_a = [cut_feature_a, lap_feature_a]
        features_b = [cut_feature_b, lap_feature_b]

        self.beam_a.add_features(features_a)
        self.beam_b.add_features(features_b)
        self.features.extend(features_a + features_b)

    @property
    def extension_plane_a(self):
        if self._extension_plane_a is None:
            offset = self.cutoff_offset if self.cutoff_offset_a is None else self.cutoff_offset_a
            self._extension_plane_a = self._centerline_cutoff_plane(self.beam_a, offset)
        return self._extension_plane_a

    @property
    def extension_plane_b(self):
        if self._extension_plane_b is None:
            offset = self.cutoff_offset if self.cutoff_offset_b is None else self.cutoff_offset_b
            self._extension_plane_b = self._centerline_cutoff_plane(self.beam_b, offset)
        return self._extension_plane_b

    @property
    def centerline_intersection(self):
        point_a, point_b = intersection_line_line(self.beam_a.centerline, self.beam_b.centerline)
        point_a = self._coerce_point(point_a)
        point_b = self._coerce_point(point_b)
        return Point(
            (point_a.x + point_b.x) * 0.5,
            (point_a.y + point_b.y) * 0.5,
            (point_a.z + point_b.z) * 0.5,
        )

    @staticmethod
    def _coerce_point(point):
        if isinstance(point, Point):
            return point
        return Point(point[0], point[1], point[2])

    def _centerline_cutoff_plane(self, beam, offset):
        side, _ = beam.endpoint_closest_to_point(self.centerline_intersection)

        normal = Vector.from_start_end(beam.centerline.start, beam.centerline.end)
        normal.unitize()
        if side == "start":
            normal = -normal

        point = self.centerline_intersection + normal * offset
        return Plane(point, normal)

    @staticmethod
    def _inverted_plane(plane):
        return Plane(plane.point, -plane.normal)

    @staticmethod
    def _clip_polyhedron_to_plane(polyhedron, plane, debug_status=None):
        """Clamp polyhedron vertices on the outward side of a cutoff plane.

        This keeps the original hexahedron topology required by
        ``Lap.from_volume_and_beam`` while shortening the volume.
        """

        normal = plane.normal.copy()
        normal.unitize()
        distances = [Vector.from_start_end(plane.point, point).dot(normal) for point in polyhedron.points]

        if max(distances) <= TOL.absolute or min(distances) >= -TOL.absolute:
            if debug_status is not None:
                debug_status.append("plane does not split volume")
            return polyhedron

        points = CutoffLLapJoint._polyhedron_with_replaced_face(polyhedron, plane, distances, debug_status)
        if points is None:
            return polyhedron

        clipped = Polyhedron(points, polyhedron.faces)
        if not CutoffLLapJoint._has_brep_volume(clipped):
            if debug_status is not None:
                debug_status.append("clipped volume invalid; using original")
            return polyhedron
        if debug_status is not None:
            debug_status.append("clipped")
        return clipped

    @staticmethod
    def _has_brep_volume(polyhedron):
        return CutoffLLapJoint._brep_volume(polyhedron) is not None

    @staticmethod
    def _brep_volume(polyhedron):
        try:
            brep = Brep.from_mesh(polyhedron.to_mesh())
            if brep.volume is None:
                return None
            return abs(brep.volume)
        except Exception:
            return None

    @staticmethod
    def _polyhedron_with_replaced_face(polyhedron, clipping_plane, point_distances, debug_status=None):
        mesh = polyhedron.to_mesh()
        planes = [mesh.face_plane(index) for index in range(mesh.number_of_faces())]

        face_distances = []
        for face in polyhedron.faces:
            face_distances.append(sum(point_distances[index] for index in face) / len(face))

        face_index = max(range(len(face_distances)), key=lambda index: face_distances[index])
        if face_distances[face_index] <= TOL.absolute:
            if debug_status is not None:
                debug_status.append("no positive face to replace; using original")
            return None

        planes[face_index] = clipping_plane

        points = []
        for vertex_index in range(len(polyhedron.points)):
            incident_faces = []
            for face_index, face in enumerate(polyhedron.faces):
                if vertex_index in face:
                    incident_faces.append(face_index)

            if len(incident_faces) != 3:
                if debug_status is not None:
                    debug_status.append("unexpected vertex topology; using original")
                return None

            point = intersection_plane_plane_plane(
                planes[incident_faces[0]],
                planes[incident_faces[1]],
                planes[incident_faces[2]],
                tol=TOL.absolute,
            )
            if point is None:
                if debug_status is not None:
                    debug_status.append("replacement planes do not intersect; using original")
                return None
            points.append(Point(*point))

        return points

    @staticmethod
    def _extend_polyhedron_to_beam_edge(polyhedron, beam, other_beam, ref_side_index, joint_point, cutoff_plane, debug_status=None):
        original_volume = CutoffLLapJoint._brep_volume(polyhedron)
        if original_volume is None:
            if debug_status is not None:
                debug_status.append("sliver cleanup skipped; original volume invalid")
            return polyhedron

        extended = CutoffLLapJoint._extend_cutoff_face_edge_to_beam_side(
            polyhedron,
            beam,
            other_beam,
            ref_side_index,
            joint_point,
            cutoff_plane,
            debug_status,
        )

        if extended is None:
            if debug_status is not None:
                debug_status.append("sliver cleanup found no larger valid lap volume")
            return polyhedron

        extended_volume = CutoffLLapJoint._brep_volume(extended)
        if extended_volume is None or extended_volume <= original_volume + TOL.absolute:
            if debug_status is not None:
                debug_status.append("sliver cleanup edge move did not enlarge lap volume")
            return polyhedron

        if debug_status is not None:
            debug_status.append("sliver cleanup extended cutoff face edge")
        return extended

    @staticmethod
    def _adjacent_ref_side_planes(beam, ref_side_index):
        index_a = (ref_side_index + 1) % 4
        index_b = (ref_side_index - 1) % 4
        return [
            Plane.from_frame(beam.ref_sides[index_a]),
            Plane.from_frame(beam.ref_sides[index_b]),
        ]

    @staticmethod
    def _beam_direction_from_joint(beam, joint_point):
        line = beam.centerline
        midpoint = line.midpoint
        direction = Vector.from_start_end(joint_point, midpoint)

        if direction.length < TOL.absolute:
            direction = Vector.from_start_end(line.start, line.end)

        if direction.length < TOL.absolute:
            return None

        direction.unitize()
        return direction

    @staticmethod
    def _acute_angle_side_vector(beam, other_beam, joint_point):
        beam_direction = CutoffLLapJoint._beam_direction_from_joint(beam, joint_point)
        other_direction = CutoffLLapJoint._beam_direction_from_joint(other_beam, joint_point)

        if beam_direction is None or other_direction is None:
            return None

        if beam_direction.dot(other_direction) < 0.0:
            other_direction = -other_direction

        side_vector = other_direction - beam_direction * other_direction.dot(beam_direction)
        if side_vector.length < TOL.absolute:
            return None

        side_vector.unitize()
        return side_vector

    @staticmethod
    def _polyhedron_centroid(polyhedron):
        x = sum(point.x for point in polyhedron.points) / len(polyhedron.points)
        y = sum(point.y for point in polyhedron.points) / len(polyhedron.points)
        z = sum(point.z for point in polyhedron.points) / len(polyhedron.points)
        return Point(x, y, z)

    @staticmethod
    def _acute_angle_side_planes(polyhedron, beam, other_beam, ref_side_index, joint_point):
        side_vector = CutoffLLapJoint._acute_angle_side_vector(beam, other_beam, joint_point)
        candidates = [
            Plane.from_frame(ref_side)
            for ref_side in beam.ref_sides
        ]

        if side_vector is None:
            return CutoffLLapJoint._adjacent_ref_side_planes(beam, ref_side_index)

        scored = []
        centroid = CutoffLLapJoint._polyhedron_centroid(polyhedron)

        for plane in candidates:
            normal = plane.normal.copy()
            normal.unitize()

            # Orient the plane normal from the current lap volume toward this
            # beam side. ref_side frame normals are not guaranteed outward.
            distance = Vector.from_start_end(centroid, plane.point).dot(normal)
            if distance < 0.0:
                normal = -normal

            score = normal.dot(side_vector)

            if score <= TOL.absolute:
                continue

            # Push slightly beyond the side face so the cutter fully removes
            # the thin acute-angle sliver instead of stopping exactly on it.
            overcut = max(TOL.absolute * 10.0, 1e-4)
            plane = Plane(plane.point + normal * overcut, normal)
            scored.append((score, plane))

        if not scored:
            return CutoffLLapJoint._adjacent_ref_side_planes(beam, ref_side_index)

        scored.sort(key=lambda item: item[0], reverse=True)
        return [plane for _, plane in scored]

    @staticmethod
    def _find_cutoff_face_index(polyhedron, cutoff_plane):
        mesh = polyhedron.to_mesh()
        cutoff_normal = cutoff_plane.normal.copy()
        cutoff_normal.unitize()

        best_index = None
        best_score = -1.0

        for index in range(mesh.number_of_faces()):
            plane = mesh.face_plane(index)
            normal = plane.normal.copy()
            normal.unitize()

            parallel_score = abs(normal.dot(cutoff_normal))
            distance_score = abs(Vector.from_start_end(cutoff_plane.point, plane.point).dot(cutoff_normal))
            score = parallel_score - distance_score

            if score > best_score:
                best_index = index
                best_score = score

        return best_index

    @staticmethod
    def _face_edges(face):
        return [
            (face[index], face[(index + 1) % len(face)])
            for index in range(len(face))
        ]

    @staticmethod
    def _target_side_plane(polyhedron, beam, other_beam, ref_side_index, joint_point):
        planes = CutoffLLapJoint._acute_angle_side_planes(
            polyhedron,
            beam,
            other_beam,
            ref_side_index,
            joint_point,
        )
        if not planes:
            return None
        return planes[0]

    @staticmethod
    def _side_planes_for_direction(polyhedron, beam, ref_side_index, direction):
        candidates = [
            Plane.from_frame(ref_side)
            for ref_side in beam.ref_sides
        ]
        centroid = CutoffLLapJoint._polyhedron_centroid(polyhedron)
        scored = []

        for plane in candidates:
            normal = plane.normal.copy()
            normal.unitize()

            distance = Vector.from_start_end(centroid, plane.point).dot(normal)
            if distance < 0.0:
                normal = -normal

            score = normal.dot(direction)
            if score <= TOL.absolute:
                continue

            overcut = max(TOL.absolute * 10.0, 1e-4)
            scored.append((score, Plane(plane.point + normal * overcut, normal)))

        if not scored:
            return CutoffLLapJoint._adjacent_ref_side_planes(beam, ref_side_index)

        scored.sort(key=lambda item: item[0], reverse=True)
        return [plane for _, plane in scored]

    @staticmethod
    def _extend_cutoff_face_edge_to_beam_side(polyhedron, beam, other_beam, ref_side_index, joint_point, cutoff_plane, debug_status=None):
        side_vector = CutoffLLapJoint._acute_angle_side_vector(beam, other_beam, joint_point)
        if side_vector is None:
            if debug_status is not None:
                debug_status.append("sliver cleanup found no acute side direction")
            return None

        cutoff_face_index = CutoffLLapJoint._find_cutoff_face_index(polyhedron, cutoff_plane)
        if cutoff_face_index is None:
            if debug_status is not None:
                debug_status.append("sliver cleanup found no cutoff face")
            return None

        cutoff_face = polyhedron.faces[cutoff_face_index]
        centroid = CutoffLLapJoint._polyhedron_centroid(polyhedron)
        original_volume = CutoffLLapJoint._brep_volume(polyhedron)

        best_replacement = None
        best_volume_increase = None

        if original_volume is None:
            return None

        for direction in (side_vector, -side_vector):
            target_planes = CutoffLLapJoint._side_planes_for_direction(
                polyhedron,
                beam,
                ref_side_index,
                direction,
            )

            for target_plane in target_planes:
                target_normal = target_plane.normal.copy()
                target_normal.unitize()
                denom = direction.dot(target_normal)

                if abs(denom) <= TOL.absolute:
                    continue

                for edge in CutoffLLapJoint._face_edges(cutoff_face):
                    point_a = polyhedron.points[edge[0]]
                    point_b = polyhedron.points[edge[1]]
                    midpoint = Point(
                        (point_a.x + point_b.x) * 0.5,
                        (point_a.y + point_b.y) * 0.5,
                        (point_a.z + point_b.z) * 0.5,
                    )

                    if Vector.from_start_end(centroid, midpoint).dot(direction) <= TOL.absolute:
                        continue

                    points = [Point(point.x, point.y, point.z) for point in polyhedron.points]
                    moved = False

                    for vertex_index in edge:
                        point = points[vertex_index]
                        distance = Vector.from_start_end(point, target_plane.point).dot(target_normal)
                        travel = distance / denom

                        if travel <= TOL.absolute:
                            continue

                        points[vertex_index] = Point(
                            point.x + direction.x * travel,
                            point.y + direction.y * travel,
                            point.z + direction.z * travel,
                        )
                        moved = True

                    if not moved:
                        continue

                    replacement = Polyhedron(points, polyhedron.faces)
                    replacement_volume = CutoffLLapJoint._brep_volume(replacement)
                    if replacement_volume is None:
                        continue

                    volume_increase = replacement_volume - original_volume
                    if volume_increase <= TOL.absolute:
                        continue

                    if best_volume_increase is None or volume_increase < best_volume_increase:
                        best_replacement = replacement
                        best_volume_increase = volume_increase

        if best_replacement is None:
            if debug_status is not None:
                debug_status.append("sliver cleanup found no movable cutoff face edge")
            return None

        return best_replacement

    @staticmethod
    def _polyhedron_with_replaced_parallel_face(polyhedron, replacement_plane, debug_status=None):
        mesh = polyhedron.to_mesh()
        planes = [mesh.face_plane(index) for index in range(mesh.number_of_faces())]
        replacement_normal = replacement_plane.normal.copy()
        replacement_normal.unitize()

        candidate_indices = []
        for index, plane in enumerate(planes):
            normal = plane.normal.copy()
            normal.unitize()
            score = abs(normal.dot(replacement_normal))
            if score >= 0.95:
                candidate_indices.append(index)

        if not candidate_indices:
            if debug_status is not None:
                debug_status.append("sliver cleanup found no parallel lap face")
            return None

        original_volume = CutoffLLapJoint._brep_volume(polyhedron)
        best_replacement = None
        best_volume = original_volume or 0.0

        for candidate_index in candidate_indices:
            original_normal = planes[candidate_index].normal.copy()
            original_normal.unitize()

            oriented_replacement_plane = replacement_plane
            if original_normal.dot(replacement_normal) < 0.0:
                oriented_replacement_plane = Plane(replacement_plane.point, -replacement_plane.normal)

            candidate_planes = list(planes)
            candidate_planes[candidate_index] = oriented_replacement_plane

            points = CutoffLLapJoint._points_from_face_planes(polyhedron, candidate_planes, None)
            if points is None:
                continue

            replacement = Polyhedron(points, polyhedron.faces)
            replacement_volume = CutoffLLapJoint._brep_volume(replacement)
            if replacement_volume is None:
                continue

            if replacement_volume > best_volume + TOL.absolute:
                best_replacement = replacement
                best_volume = replacement_volume

        if best_replacement is None:
            return None

        return best_replacement

    @staticmethod
    def _points_from_face_planes(polyhedron, planes, debug_status=None):
        points = []
        for vertex_index in range(len(polyhedron.points)):
            incident_faces = []
            for face_index, face in enumerate(polyhedron.faces):
                if vertex_index in face:
                    incident_faces.append(face_index)

            if len(incident_faces) != 3:
                if debug_status is not None:
                    debug_status.append("unexpected vertex topology; using original")
                return None

            point = intersection_plane_plane_plane(
                planes[incident_faces[0]],
                planes[incident_faces[1]],
                planes[incident_faces[2]],
                tol=TOL.absolute,
            )
            if point is None:
                if debug_status is not None:
                    debug_status.append("replacement planes do not intersect; using original")
                return None
            points.append(Point(*point))

        return points
