import math

def get_beam_fabrication_data(stocks):
    """
    Extracts fabrication data for each beam:
    - length
    - bounding box edge lengths
    - cut angle (start + end)

    Returns:
        list of dicts
    """

    data = []

    for stock in stocks:
        for item in stock["beams"]:
            beam = item["beam"]

            # --- 1. length ---
            length = beam.centerline.length

            # --- 2. bounding box (real part dimensions) ---
            bbox = beam.geometry.bounding_box()
            dx = bbox[1][0] - bbox[0][0]
            dy = bbox[3][1] - bbox[0][1]
            dz = bbox[4][2] - bbox[0][2]

            # --- 3. angle with respect to X-axis (global cut) ---
            vec = beam.centerline.direction
            angle = math.degrees(math.atan2(vec.y, vec.x))

            # --- 4. saving ---
            data.append({
                "beam_id": id(beam),
                "stock_id": stock["id"],
                "length": length,
                "edge_x": abs(dx),
                "edge_y": abs(dy),
                "edge_z": abs(dz),
                "cut_angle_deg": angle,
            })

    return data