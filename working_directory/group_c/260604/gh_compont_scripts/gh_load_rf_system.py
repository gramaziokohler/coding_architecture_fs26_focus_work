# venv: ca-fs26-final-project

from compas_rhino.devtools import DevTools
DevTools.ensure_path()
ghenv.Component.Message = "Load RF System"

# -------------------- IMPORTS ---------------------

import pickle

# ------------------- EXECUTION --------------------

rf_system = None
success = False
message = ""

if filepath and run:
    try:
        # Load the pickled data
        with open(filepath, 'rb') as f:
            data = pickle.load(f)
        
        # Reconstruct the RF system from the meshes
        from a03_rf_system import RFSystem
        from a03_rf_system_hybrid import RFSystemHybrid
        
        if data['type'] == 'hybrid':
            rf_system = RFSystemHybrid(data['inner_mesh'], data['boundary_mesh'])
            message = f"Loaded RFSystemHybrid from: {filepath}"
        else:
            rf_system = RFSystem(data['mesh'])
            message = f"Loaded RFSystem from: {filepath}"
        
        success = True
        print(message)
        
    except Exception as e:
        success = False
        rf_system = None
        message = f"Error loading RF System: {str(e)}"
        print(message)
        import traceback
        traceback.print_exc()
else:
    success = False
    rf_system = None
    message = "Please provide a filepath and click run"
    print(message)