from compas.geometry import Point, Vector, Line, intersection_line_line
from compas_timber.fabrication import Drilling
from compas_timber.connections import (
    LMiterJoint,
    TBirdsmouthJoint,
    TButtJoint,
    TLapJoint,
    XLapJoint,
    TStepJoint
)

class DrillingProcessor:
    """
    A helper class to apply Drilling features (screws/dowels) to the joints 
    of a generated TimberModel.
    """
    def __init__(self, timber_model, screw_diameter=0.006, screw_length=0.150):
        self.timber_model = timber_model
        self.screw_diameter = screw_diameter
        self.screw_length = screw_length
        self.drilling_count = 0

    def process_drillings(self):
        """
        Iterates over the generated joints and assigns the Drilling feature to the beams.
        """
        print("--- Starting Drilling Generation ---")
        
        # Access joints gracefully (handles slight differences in API versions)
        # joints = getattr(self.timber_model, 'joints', None) or getattr(self.timber_model, 'interactions', [])
        
        for joint in joints:
            self._apply_drilling_to_joint(joint)
            
        print(f"Successfully generated {self.drilling_count} drilling operations.")
        return self.timber_model

    def _apply_drilling_to_joint(self, joint):
        # 1. Identify connected elements
        elements = getattr(joint, 'elements', None)
        if not elements and hasattr(joint, 'main_beam'):
            # Fallback for older/alternative joint property mappings
            elements = [joint.main_beam, getattr(joint, 'cross_beam')]
            
        if not elements or len(elements) < 2:
            return
            
        beam_a = elements[0]
        beam_b = elements[1]
        
        # 2. Extract centerlines
        line_a = beam_a.centerline
        line_b = beam_b.centerline
        
        # 3. Find intersection or closest approach points
        res = intersection_line_line(line_a, line_b)
        if not res or res[0] is None:
            return
            
        pt_a, pt_b = res
        
        # Find the mathematical midpoint in the connection zone
        mid_pt = Point(
            (pt_a[0] + pt_b[0]) / 2.0,
            (pt_a[1] + pt_b[1]) / 2.0,
            (pt_a[2] + pt_b[2]) / 2.0
        )
        from compas.geometry import Frame, Point, Vector, intersection_line_line
from compas_timber.fabrication import Drilling

# ... [previous setup code remains the same] ...
        # 4. Calculate Screw Direction (Z-axis of the drill)
        dir_a = line_a.direction
        dir_b = line_b.direction
        screw_dir = dir_a.cross(dir_b)
        
        if screw_dir.length < 1e-5:
            screw_dir = beam_a.frame.zaxis if hasattr(beam_a, 'frame') else Vector(0, 0, 1)
        else:
            screw_dir.unitize()
            
        # The starting point of the drill (backing up half the screw length from the midpoint)
        start_pt = mid_pt + screw_dir * (-self.screw_length / 2.0)
            
        # 5. Create a Local Coordinate Frame for the Drilling
        # The Z-axis of this frame defines the drill bit's path.
        # We generate arbitrary X and Y axes perpendicular to Z to complete the frame.
        z_axis = screw_dir
        temp_x = Vector(1, 0, 0) if abs(z_axis.x) < 0.9 else Vector(0, 1, 0)
        y_axis = z_axis.cross(temp_x)
        y_axis.unitize()
        x_axis = y_axis.cross(z_axis)
        x_axis.unitize()
        
        drilling_frame = Frame(start_pt, x_axis, y_axis)
        
        # 6. Instantiate the Drilling feature
        drilling_feature = Drilling(
            frame=drilling_frame, 
            diameter=self.screw_diameter, 
            length=self.screw_length
        )
        
        # 7. Apply the feature to both beams
        if hasattr(beam_a, 'add_features'):
            beam_a.add_features([drilling_feature])
            beam_b.add_features([drilling_feature])
        elif hasattr(beam_a, 'add_feature'):
            beam_a.add_feature(drilling_feature)
            beam_b.add_feature(drilling_feature)