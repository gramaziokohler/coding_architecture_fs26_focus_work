# venv: ca-fs26-focus-work

from compas_rhino.devtools import DevTools
DevTools.ensure_path()
ghenv.Component.Message = "Timber Model (Geometric + Support Points)"

# -------------------- IMPORTS ---------------------

import importlib
import a03_timber_model_geometric
import a03_extra_split_beams

importlib.reload(a03_timber_model_geometric)
importlib.reload(a03_extra_split_beams)

from a03_timber_model_geometric import GeometricTimberModelCreator
from a03_extra_split_beams import mark_support_points_on_beams
from a03_rf_system_hybrid import RFSystemHybrid

# ------------------- DEFAULTS ---------------------

if 'inner_beam_width' not in dir():               inner_beam_width = 0.06
if 'inner_beam_height' not in dir():              inner_beam_height = 0.08
if 'base_beam_width' not in dir():                base_beam_width = 0.08
if 'base_beam_height' not in dir():               base_beam_height = 0.10
if 'arch_beam_width' not in dir():                arch_beam_width = 0.08
if 'arch_beam_height' not in dir():               arch_beam_height = 0.10
if 'max_distance' not in dir():                   max_distance = None
if 'max_distance_L' not in dir():                 max_distance_L = None
if 'max_distance_T' not in dir():                 max_distance_T = None
if 'max_distance_T_arch_base' not in dir():       max_distance_T_arch_base = None
if 'max_distance_X' not in dir():                 max_distance_X = None
if 'z_height_threshold' not in dir():             z_height_threshold = None
if 'arch_plane_A' not in dir():                   arch_plane_A = None
if 'arch_plane_B' not in dir():                   arch_plane_B = None
if 'arch_split_axis' not in dir():                arch_split_axis = "x"
if 'support_tolerance' not in dir():              support_tolerance = 0.01
if 'rhino_points' not in dir():                   rhino_points = None

# ---------------- RF SYSTEM WRAPPING --------------

rf_system_copy = rf_system

is_hybrid = (
    isinstance(rf_system_copy, RFSystemHybrid) or
    type(rf_system_copy).__name__ == 'RFSystemHybrid' or
    hasattr(rf_system_copy, 'get_combined_mesh')
)

if is_hybrid:
    boundary_count = len([
        e for e in rf_system_copy.boundary_mesh.edges()
        if rf_system_copy.boundary_mesh.is_edge_on_boundary(e)
    ])

    if boundary_count == 0:
        class RFSystemWrapper:
            def __init__(self, hybrid):
                self.mesh = hybrid.inner_mesh
        rf_system_copy = RFSystemWrapper(rf_system_copy)
    else:
        class RFSystemWrapper:
            def __init__(self, hybrid):
                self._hybrid = hybrid
                self._mesh = None

            @property
            def mesh(self):
                if self._mesh is None:
                    self._mesh = self._hybrid.get_combined_mesh()
                return self._mesh

        rf_system_copy = RFSystemWrapper(rf_system_copy)

sampling_points = int(sampling_points) if sampling_points > 2 else 20

# ------------------- CREATE MODEL -----------------

creator = GeometricTimberModelCreator(
    rf_system_copy,
    inner_beam_width=inner_beam_width,
    inner_beam_height=inner_beam_height,
    base_beam_width=base_beam_width,
    base_beam_height=base_beam_height,
    arch_beam_width=arch_beam_width,
    arch_beam_height=arch_beam_height,
    max_distance=float(max_distance) if max_distance is not None else None,
    max_distance_L=float(max_distance_L) if max_distance_L is not None else None,
    max_distance_T=float(max_distance_T) if max_distance_T is not None else None,
    max_distance_T_arch_base=float(max_distance_T_arch_base) if max_distance_T_arch_base is not None else None,
    max_distance_X=float(max_distance_X) if max_distance_X is not None else None,
    z_height_threshold=float(z_height_threshold) if z_height_threshold is not None else None,
    sampling_points=sampling_points,
    arch_plane_A=arch_plane_A,
    arch_plane_B=arch_plane_B,
    arch_split_axis=arch_split_axis,
)

timber_model = creator.create_timber_model(process_joinery)
joining_errors = creator.joining_errors

# ---------------- SUPPORT ATTRIBUTES --------------

if rhino_points:
    mark_support_points_on_beams(
        timber_model,
        rhino_points,
        tolerance=float(support_tolerance),
    )
    support_beams = [
        beam for beam in timber_model.beams
        if beam.attributes.get("support_points")
    ]
    print("Marked support points on {} beams.".format(len(support_beams)))
else:
    print("No support points provided.")

# ------------------- OUTPUT GEOMETRY --------------

if len(joining_errors):
    ghenv.Component.Message = "Found {} joining errors!".format(len(joining_errors))

beams = []
geometry_errors = []

for beam in timber_model.beams:
    try:
        beams.append(beam.geometry)
    except Exception as e:
        geometry_errors.append(e)
        print("Could not add geometry of beam: {}".format(e))

if len(geometry_errors) > 0:
    ghenv.Component.Message = "{} beams failed to generate geometry!".format(len(geometry_errors))
