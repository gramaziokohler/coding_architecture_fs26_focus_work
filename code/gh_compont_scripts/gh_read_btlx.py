# venv: ca-fs26-focus-work

"""Reads a BTLx file into a COMPAS Timber model."""

# flake8: noqa
import os

import Grasshopper

from compas_timber.btlx import BTLxReader
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython


class ReadBTLx(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, path, read: bool):
        if not read:
            return None, [], 0

        if not item_input_valid_cpython(ghenv, path, "Path"):
            return None, [], 0

        path = str(path)
        if not os.path.exists(path):
            raise FileNotFoundError("BTLx file not found: {}".format(path))

        reader = BTLxReader()
        model = reader.read(path)
        errors = list(getattr(reader, "errors", []) or [])

        try:
            element_count = len(list(model.elements()))
        except Exception:
            element_count = 0

        return model, errors, element_count
