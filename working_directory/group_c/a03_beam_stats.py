from compas.geometry import Frame
from compas.geometry import Transformation
from compas_rhino.conversions import point_to_compas


def get_stats(timber_model, wood_density=500):
    """
    Erstellt allgemeine Statistiken über das Timber-Modell.
    wood_density: Dichte in kg/m3 (Standard ca. 500 für Nadelholz)
    """
    beams = list(timber_model.beams)


    length = b.centerline.length
    width = b.geometry.width
    height = b.geometry.height
    volume = length * width * height
    weight = volume * wood_density


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
