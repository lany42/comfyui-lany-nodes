# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Run the frontend contracts using the development-only Node.js runtime."""

import subprocess
import sys
from pathlib import Path


def test_seed_frontend(tmp_path):
    suite = Path(__file__).with_name("seed.test.mjs")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "nodejs_wheel",
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
