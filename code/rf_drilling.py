from compas.geometry import Frame, Point, Vector, Line, intersection_line_line
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
        self.screw_lines = []

    def process_drillings(self):
        """
        Iterates over the generated joints and assigns the Drilling feature to the beams.
        """
        print("--- Starting Drilling Generation ---")
        
        # FIXED: Uncommented so 'joints' is actually defined!
        joints = getattr(self.timber_model, 'joints', None) or getattr(self.timber_model, 'interactions', [])
        
        for joint in joints:
            self._apply_drilling_to_joint(joint)
            
        print(f"Successfully generated {self.drilling_count} drilling operations.")
        return self.timber_model

    def _apply_drilling_to_joint(self, joint):
        # 0. SKIP COMPLEX JOINTS
        # Filter out joints where the centerline intersection does not 
        # sit perfectly inside the physical contact volume.
        if isinstance(joint, (LMiterJoint, TBirdsmouthJoint, TButtJoint)):
            return

        # 1. Identify connected elements
        elements = getattr(joint, 'elements', None)
        if not elements and hasattr(joint, 'main_beam'):
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
        mid_pt = Point(
            (pt_a[0] + pt_b[0]) / 2.0,
            (pt_a[1] + pt_b[1]) / 2.0,
            (pt_a[2] + pt_b[2]) / 2.0
        )
        
        # 4. Calculate Screw Geometry
        dir_a = line_a.direction
        dir_b = line_b.direction
        screw_dir = dir_a.cross(dir_b)
        
        if screw_dir.length < 1e-5:
            screw_dir = beam_a.frame.zaxis if hasattr(beam_a, 'frame') else Vector(0, 0, 1)
        else:
            screw_dir.unitize()
            
        # Create the 3D line representing the physical screw
        start_pt = mid_pt + screw_dir * (-self.screw_length / 2.0)
        end_pt = mid_pt + screw_dir * (self.screw_length / 2.0)
        screw_line = Line(start_pt, end_pt)
        
        # 5. GENERATE BTLX-MAPPED DRILLINGS
        try:
            drill_a = Drilling.from_line_and_element(screw_line, beam_a, diameter=self.screw_diameter)
            drill_b = Drilling.from_line_and_element(screw_line, beam_b, diameter=self.screw_diameter)
            
            # 6. Apply to elements
            if hasattr(beam_a, 'add_features'):
                beam_a.add_features([drill_a])
                beam_b.add_features([drill_b])
            else:
                beam_a.add_feature(drill_a)
                beam_b.add_feature(drill_b)
                
            self.drilling_count += 1
            self.screw_lines.append(screw_line)
            
        except Exception as e:
            # We will still print the error just in case a LapJoint fails, 
            # so you know exactly what is happening in the background.
            print("Failed to map drilling geometry to element: {}".format(e))