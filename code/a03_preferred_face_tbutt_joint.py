"""
Custom COMPAS Timber T-butt joint with controllable receiving face.

Copy this file into a project folder that is on the Python path and import
``PreferredFaceTButtJoint`` wherever joint rules are defined.
"""

from compas.geometry import Vector
from compas_timber.connections import TButtJoint


class PreferredFaceTButtJoint(TButtJoint):
    """TButtJoint that can prefer or force a reference side on the cross beam.

    COMPAS Timber's default ``TButtJoint`` chooses the receiving face on the
    cross beam from the incidence angle between the butting beam and the cross
    beam reference sides. This class lets you override that behavior.

    Parameters
    ----------
    main_beam : :class:`compas_timber.elements.Beam`
        The butting beam, whose end is trimmed.
    cross_beam : :class:`compas_timber.elements.Beam`
        The receiving beam.
    mill_depth : float, optional
        Pocket/lap depth on the receiving beam.
    butt_plane : :class:`compas.geometry.Plane`, optional
        Plane used to cut the main beam.
    preferred_face_vector : :class:`compas.geometry.Vector` or sequence[float], optional
        Direction used to choose the receiving face. The ref side whose normal
        has the largest dot product with this vector is selected. Defaults to
        global Z, i.e. the upper face.
    cross_beam_ref_side_index : int, optional
        If set, this exact cross-beam ref side index is used. This takes
        precedence over ``preferred_face_vector``.
    """

    def __init__(
        self,
        main_beam=None,
        cross_beam=None,
        mill_depth=None,
        butt_plane=None,
        fastener=None,
        preferred_face_vector=None,
        cross_beam_ref_side_index=None,
        **kwargs
    ):
        super(PreferredFaceTButtJoint, self).__init__(
            main_beam=main_beam,
            cross_beam=cross_beam,
            mill_depth=mill_depth,
            butt_plane=butt_plane,
            fastener=fastener,
            **kwargs
        )
        self.preferred_face_vector = self._coerce_vector(preferred_face_vector or Vector(0, 0, 1))
        self.forced_cross_beam_ref_side_index = cross_beam_ref_side_index

    @property
    def __data__(self):
        data = super(PreferredFaceTButtJoint, self).__data__
        data["preferred_face_vector"] = self.preferred_face_vector
        data["forced_cross_beam_ref_side_index"] = self.forced_cross_beam_ref_side_index
        return data

    @staticmethod
    def _coerce_vector(vector):
        if isinstance(vector, Vector):
            result = vector.copy()
        else:
            result = Vector(vector[0], vector[1], vector[2])

        if result.length == 0:
            result = Vector(0, 0, 1)

        result.unitize()
        return result

    @property
    def cross_beam_ref_side_index(self):
        """Return the receiving face index on the cross beam."""

        if self.forced_cross_beam_ref_side_index is not None:
            return int(self.forced_cross_beam_ref_side_index)

        scores = {}
        for index, ref_side in enumerate(self.cross_beam.ref_sides[:4]):
            normal = ref_side.normal
            normal.unitize()
            scores[index] = normal.dot(self.preferred_face_vector)

        return max(scores, key=scores.get)


class TopFaceTButtJoint(PreferredFaceTButtJoint):
    """Convenience T-butt joint that always prefers global-Z receiving faces."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("preferred_face_vector", Vector(0, 0, 1))
        super(TopFaceTButtJoint, self).__init__(*args, **kwargs)
