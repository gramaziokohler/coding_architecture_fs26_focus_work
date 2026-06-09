
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

if 'inner_beam_width' not in dir():                        inner_beam_width = 0.06
if 'inner_beam_height' not in dir():                       inner_beam_height = 0.08
if 'base_beam_width' not in dir():                         base_beam_width = 0.08
if 'base_beam_height' not in dir():                        base_beam_height = 0.10
if 'arch_beam_width' not in dir():                         arch_beam_width = 0.08
if 'arch_beam_height' not in dir():                        arch_beam_height = 0.10
if 'max_distance' not in dir():                            max_distance = None
if 'max_distance_L' not in dir():                          max_distance_L = None
if 'max_distance_T' not in dir():                          max_distance_T = None
if 'max_distance_T_arch_base' not in dir():                max_distance_T_arch_base = None
if 'max_distance_T_inner_base' not in dir():               max_distance_T_inner_base = None
if 'max_distance_X' not in dir():                          max_distance_X = None
if 'z_height_threshold' not in dir():                      z_height_threshold = None
if 'arch_plane_A' not in dir():                            arch_plane_A = None
if 'arch_plane_B' not in dir():                            arch_plane_B = None
if 'arch_split_axis' not in dir():                         arch_split_axis = "x"
if 'tbutt_mill_depth' not in dir():                        tbutt_mill_depth = 0.0
if 'base_mill_depth' not in dir():                         base_mill_depth = 0.0
if 'preferred_face_vector' not in dir():                   preferred_face_vector = [0, 0, 1]
if 'support_tolerance' not in dir():                       support_tolerance = 0.01
if 'rhino_points' not in dir():                            rhino_points = None
if 'cutting_plane_inset_distance' not in dir():            cutting_plane_inset_distance = 0.0
if 'arch_A_inner_cross_beam_ref_side_index' not in dir():  arch_A_inner_cross_beam_ref_side_index = None
if 'arch_B_inner_cross_beam_ref_side_index' not in dir():  arch_B_inner_cross_beam_ref_side_index = None

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
    max_distance_T_inner_base=float(max_distance_T_inner_base) if max_distance_T_inner_base is not None else None,
    max_distance_X=float(max_distance_X) if max_distance_X is not None else None,
    z_height_threshold=float(z_height_threshold) if z_height_threshold is not None else None,
    sampling_points=sampling_points,
    arch_plane_A=arch_plane_A,
    arch_plane_B=arch_plane_B,
    arch_split_axis=arch_split_axis,
    tbutt_mill_depth=float(tbutt_mill_depth),
    base_mill_depth=float(base_mill_depth),
    preferred_face_vector=preferred_face_vector,
    cutting_plane_inset_distance=float(cutting_plane_inset_distance),
    arch_A_inner_cross_beam_ref_side_index=int(arch_A_inner_cross_beam_ref_side_index) if arch_A_inner_cross_beam_ref_side_index is not None else None,
    arch_B_inner_cross_beam_ref_side_index=int(arch_B_inner_cross_beam_ref_side_index) if arch_B_inner_cross_beam_ref_side_index is not None else None,
)

timber_model = creator.create_timber_model(process_joinery)
joining_errors = creator.joining_errors
trimmed_inner_beam_objects = getattr(creator, "trimmed_inner_beams", [])
print("Trimmed inner beam candidates: {}".format(len(trimmed_inner_beam_objects)))
cutting_planes_inner_beams = getattr(creator, "cutting_planes_inner_beams", [])
print("Cutting planes for trimmed inner beams: {}".format(len(cutting_planes_inner_beams)))
jack_rafter_cut_features_inner_beams = getattr(
    creator,
    "jack_rafter_cut_features_inner_beams",
    []
)
print(
    "JackRafterCut features for trimmed inner beams: {}".format(
        len(jack_rafter_cut_features_inner_beams)
    )
)

trimmed_inner_beam_geometries = getattr(
    creator,
    "trimmed_inner_beam_geometries",
    []
)
print(
    "Final trimmed inner beam geometries: {}".format(
        len(trimmed_inner_beam_geometries)
    )
)

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
beam_edges = []
inner_beams = []
inner_beam_edges = []
base_beams = []
arch_beams = []
arch_A_beams = []
arch_B_beams = []
failed_beams = []
beam_categories = []

geometry_errors = []

trimmed_inner_beams = []
trimmed_inner_beam_edges = []

for beam in timber_model.beams:
    category = beam.attributes.get("category", "unknown")
    beam_categories.append(category)

    try:
        geo = beam.attributes.get("trimmed_geometry")

        if geo is None:
            geo = beam.geometry

        beams.append(geo)
        beam_edges.append(str(beam.attributes.get("edge", None)))

        if category == "inner":
            inner_beams.append(geo)
            inner_beam_edges.append(str(beam.attributes.get("edge", None)))
        elif category == "base":
            base_beams.append(geo)
        elif category == "arch_A":
            arch_beams.append(geo)
            arch_A_beams.append(geo)
        elif category == "arch_B":
            arch_beams.append(geo)
            arch_B_beams.append(geo)
        elif category == "arch":
            arch_beams.append(geo)
        else:
            failed_beams.append(geo)

        if beam.attributes.get("trimmed_inner_candidate"):
            trimmed_inner_beams.append(geo)
            trimmed_inner_beam_edges.append(str(beam.attributes.get("edge", None)))

    except Exception as e:
        geometry_errors.append((category, e))
        print(
            "Could not add geometry of {} beam edge={}: {}".format(
                category,
                beam.attributes.get("edge"),
                e
            )
        )

        try:
            edge = beam.attributes.get("edge")
            centerline = None

            if edge is not None:
                centerline = rf_system_copy.mesh.edge_attribute(edge, "centerline")

            if centerline is not None:
                failed_beams.append(centerline)
                print("Added fallback centerline for failed {} beam.".format(category))

        except Exception as e2:
            print("Could not add fallback centerline: {}".format(e2))

if len(geometry_errors) > 0:
    ghenv.Component.Message = "{} beams failed to generate geometry!".format(len(geometry_errors))

print(
    "Output geometry: total={}, inner={}, base={}, arch={} (A={}, B={}), failed={}".format(
        len(beams),
        len(inner_beams),
        len(base_beams),
        len(arch_beams),
        len(arch_A_beams),
        len(arch_B_beams),
        len(failed_beams),
    )
)