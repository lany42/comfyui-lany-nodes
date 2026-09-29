# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Install the ComfyUI API double before test modules import the nodes.

test_extension.py loads the package in fresh interpreters to check that
imports stay free of host modules; tests here share one double instead.
"""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

HOST_DOUBLE = Path(__file__).with_name("host_double.py")

_spec = spec_from_file_location("host_double", HOST_DOUBLE)
host_double = module_from_spec(_spec)
_spec.loader.exec_module(host_double)
sys.modules.update(host_double.comfy_api_modules())
