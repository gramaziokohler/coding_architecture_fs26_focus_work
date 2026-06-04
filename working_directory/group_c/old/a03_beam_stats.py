from compas.geometry import Frame
from compas.geometry import Transformation
from compas_rhino.conversions import point_to_compas


def basic_arrange_beams(timber_model, origin, gap):
    origin = point_to_compas(point)

    frame = Frame(origin, [0, 1, 0], [0, 0, 1])
    beam_grid = []
    for i, beam in enumerate(timber_model.beams):
        stock_beam = beam.geometry
        trans = Transformation.from_frame_to_frame(beam.frame, frame)
        stock_beam = stock_beam.transformed(trans)
        beam_grid.append(stock_beam)
        frame.point.x += gap


def get_stats(timber_model, wood_density=500):
    """
    Erstellt allgemeine Statistiken über das Timber-Modell.
    wood_density: Dichte in kg/m3 (Standard ca. 500 für Nadelholz)
    """
    beams = list(timber_model.beams)


    length = [b.centerline.length for b in beams]
    width = [b.geometry.width for b in beams]
    height = [b.geometry.height for b in beams]
    volume = [l * w * h for l, w, h in zip(length, width, height)]
    weight = [v * wood_density for v in volume]


    stats_msg = "\n".join(
        [
            "--- MODEL STATS ---",
            f"Length: {length:.2f} m",
            f"Volume: {volume:.2f} m³",
            f"Weight: {weight:.1f} kg",
            "-------------------",
        ]
    )

    print(stats_msg)

    return stats_msg
