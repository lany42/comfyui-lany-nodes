# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Run the frontend contracts using locally installed Node.js."""

import shutil
import subprocess
import warnings
from pathlib import Path

import pytest


def test_seed_frontend(tmp_path):
    node = shutil.which("node")
    if node is None:
        message = "to run this project's frontend tests, please install node."
        warnings.warn(message, pytest.PytestWarning, stacklevel=1)
        pytest.skip(message)

    suite = Path(__file__).with_name("seed.test.mjs")
    result = subprocess.run(
        [
            node,
            "--experimental-vm-modules",
            "--test",
            str(suite),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
