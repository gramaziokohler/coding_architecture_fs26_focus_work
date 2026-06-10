from compas_rhino.devtools import DevTools
DevTools.ensure_path()
ghenv.Component.Message = "Metal Plates + Base Laps"

import importlib
import Rhino.Geometry as rg
from compas_rhino.conversions import box_to_rhino, brep_to_compas, brep_to_rhino
from compas_timber.fabrication import LapProxy
import base_lap
import metal_plate_lap
importlib.reload(base_lap)
importlib.reload(metal_plate_lap)
from base_lap import create_base_beam_plates_from_points, apply_laps_single_beam
from metal_plate_lap import create_metal_plates, apply_laps

# GH inputs — add these as component inputs in Grasshopper:
#   timber_model      : full TimberModel
#   points            : points on base beam centerlines for base lap locations
#   use_llap_joint    : bool — True = LLap (no base plates), False = LMiter (with base plates)
#   base_lap_size     : list [x, y, z] in metres, e.g. [0.100, 0.140, 0.015]
#   beam_width        : float, optional cross-section width override for base beams
#   arch_beam_height  : float, e.g. 0.10
#   arch_plate_size   : list [w, l, t], e.g. [0.040, 0.105, 0.005]
#   base_beam_height  : float, e.g. 0.14
#   base_plate_size   : list [w, l, t], e.g. [0.045, 0.185, 0.005]
if False:
    timber_model = points = base_lap_size = beam_width = use_llap_joint = None
    arch_beam_height = arch_plate_size = base_beam_height = base_plate_size = None
    timber_model_out = base_lap_count = metal_lap_count = base_plates = metal_plates = all_plates = None
    base_lap_volumes = metal_lap_volumes = beams = None

use_llap_joint   = bool(vars().get("use_llap_joint") or False)
base_lap_size    = tuple(vars().get("base_lap_size") or (0.100, 0.140, 0.015))
beam_width       = vars().get("beam_width")          or None
arch_beam_height = vars().get("arch_beam_height")    or 0.10
arch_plate_size  = tuple(vars().get("arch_plate_size") or (0.046, 0.111, 0.0025))
base_beam_height = vars().get("base_beam_height")    or 0.14
base_plate_size  = tuple(vars().get("base_plate_size") or (0.051, 0.191, 0.0025))

base_plates       = []
metal_plates      = []
base_lap_volumes  = []
metal_lap_volumes = []
base_lap_count    = 0
metal_lap_count   = 0
timber_model_out  = None

if timber_model is not None:

    # Clear all stale LapProxy features once before either step runs.
    # apply_laps (step 2) used to do this internally, but that wiped out the
    # base lap pockets added by step 1 whenever base beams are also involved in
    # LMiterJoint metal plate laps (LMiter mode).
    for _b in timber_model.beams:
        if hasattr(_b, "features") and _b.features:
            for _f in [f for f in list(_b.features) if isinstance(f, LapProxy)]:
                try:
                    _b.remove_feature(_f)
                except Exception:
                    try:
                        _b.features.remove(_f)
                    except Exception:
                        pass

    # --- Step 1: Base beam laps ---
    # Filter base beams from the full model by their category attribute.
    if points:
        base_beams = [b for b in timber_model.beams
                      if b.attributes.get("category") == "base"]
        print(f"Found {len(base_beams)} base beams")

        base_plate_data = create_base_beam_plates_from_points(
            base_beams,
            points,
            plate_size=base_lap_size,
            beam_width=beam_width,
        )

        base_compas_breps = []
        base_beam_list    = []

        for box, beam, contact_normal in base_plate_data:
            try:
                rhino_brep = rg.Brep.CreateFromBox(box_to_rhino(box))
                if not rhino_brep:
                    print("Warning: base plate CreateFromBox returned None")
                    continue
                base_plates.append(rhino_brep)
                base_compas_breps.append(brep_to_compas(rhino_brep))
                base_beam_list.append(beam)
            except Exception as e:
                print(f"Warning: could not convert base plate: {e}")

        base_lap_pairs = apply_laps_single_beam(base_compas_breps, base_beam_list)
        base_lap_count = len(base_lap_pairs)
        for lap, beam in base_lap_pairs:
            try:
                base_lap_volumes.append(brep_to_rhino(lap.volume.transformed(beam.modeltransformation)))
            except Exception as e:
                print(f"Warning: could not visualize base lap: {e}")

    # --- Step 2: Metal plate laps at LMiterJoints ---
    metal_plate_data = create_metal_plates(
        timber_model,
        use_llap_joint=use_llap_joint,
        arch_beam_height=arch_beam_height,
        arch_plate=arch_plate_size,
        base_beam_height=base_beam_height,
        base_plate=base_plate_size,
    )

    lap_brep_beam = []

    for box, beam_a, beam_b, contact_normal, lap_box_a, lap_box_b in metal_plate_data:
        try:
            # Visual plate for viewport display.
            rhino_brep = rg.Brep.CreateFromBox(box_to_rhino(box))
            if not rhino_brep:
                print("Warning: metal plate CreateFromBox returned None")
                continue
            metal_plates.append(rhino_brep)

            # Per-beam lap breps — each positioned at that beam's own side face.
            for lap_box, beam in [(lap_box_a, beam_a), (lap_box_b, beam_b)]:
                lap_rhino = rg.Brep.CreateFromBox(box_to_rhino(lap_box))
                if lap_rhino:
                    lap_brep_beam.append((brep_to_compas(lap_rhino), beam))
        except Exception as e:
            print(f"Warning: could not convert metal plate: {e}")

    metal_lap_pairs = apply_laps(lap_brep_beam)
    metal_lap_count = len(metal_lap_pairs)
    for lap, beam in metal_lap_pairs:
        try:
            metal_lap_volumes.append(brep_to_rhino(lap.volume.transformed(beam.modeltransformation)))
        except Exception as e:
            print(f"Warning: could not visualize metal lap: {e}")

    # Both steps modify beams in-place — expose the updated model once at the end.
    timber_model_out = timber_model

all_plates = base_plates + metal_plates

# Collect processed beam geometry (beams with all pockets subtracted).
beams = []
if timber_model_out:
    for beam in timber_model_out.beams:
        try:
            beams.append(brep_to_rhino(beam.geometry))
        except Exception as e:
            print(f"Warning: beam geometry failed: {e}")

print(f"Base plates: {len(base_plates)} ({base_lap_count} laps), Metal plates: {len(metal_plates)} ({metal_lap_count} laps)")
