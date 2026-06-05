import math

def get_beam_fabrication_data(stocks):
    """
    Estrae dati di fabbricazione per ogni beam:
    - lunghezza
    - lunghezze spigoli bounding box
    - angolo di taglio (start + end)

    Returns:
        list di dict
    """

    data = []

    for stock in stocks:
        for item in stock["beams"]:
            beam = item["beam"]

            # --- 1. lunghezza ---
            length = beam.centerline.length

            # --- 2. bounding box (dimensioni reali pezzo) ---
            bbox = beam.geometry.bounding_box()
            dx = bbox[1][0] - bbox[0][0]
            dy = bbox[3][1] - bbox[0][1]
            dz = bbox[4][2] - bbox[0][2]

            # --- 3. angolo rispetto asse X (taglio globale) ---
            vec = beam.centerline.direction
            angle = math.degrees(math.atan2(vec.y, vec.x))

            # --- 4. salvataggio ---
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