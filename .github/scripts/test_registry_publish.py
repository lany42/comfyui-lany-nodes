# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Offline tests: python3 -m unittest discover -s .github/scripts."""

import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import registry_publish as publish

COMMIT = "a" * 40


class VersionTests(unittest.TestCase):
    def test_numeric_release_and_rc_order(self):
        tags = [
            "v0.0.0",
            "v4.1.2-rc0",
            "v4.1.2-rc2",
            "v4.1.2-rc10",
            "v4.1.2-rc32",
            "v4.1.2",
            "v4.1.10",
            "v4.2.0",
            "v4.10.0",
            "v10.0.0",
        ]
        versions = [publish.parse_version(tag, tag=True) for tag in tags]
        self.assertEqual(versions, sorted(set(versions)))

    def test_invalid_candidates(self):
        for tag in [
            "v.0.2.0",
            "1.2.3",
            "v1.2",
            "v01.2.3",
            "v1.2.3-rc01",
            "v1.2.3-rc",
            "v1.2.3-beta1",
            "v1.2.3+build",
            "v1.2.3\n",
            "v1.2.3; echo unsafe",
            "",
            None,
        ]:
            with self.subTest(tag=tag), self.assertRaises(publish.PublishError):
                publish.parse_version(tag, tag=True)

    def test_python_rc_spelling_matches_tag(self):
        candidate = publish.parse_version("v4.1.2-rc32", tag=True)
        for version in ("4.1.2-rc32", "4.1.2rc32"):
            self.assertEqual(candidate, publish.parse_version(version, python_rc=True))


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path("checkout")

    @patch.object(
        publish, "git", return_value="v4.1.2-rc2\nv.0.2.0\nv4.1.2-rc32\nv4.1.1"
    )
    def test_automatic_selection_ignores_malformed_history(self, git):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(publish.select_tag(self.repo, ""), "v4.1.2-rc32")
        self.assertIn("v.0.2.0", output.getvalue())

    @patch.object(publish, "git")
    def test_explicit_invalid_tag_fails_before_git(self, git):
        with self.assertRaises(publish.PublishError):
            publish.select_tag(self.repo, "v.0.2.0")
        git.assert_not_called()

    @patch.object(publish, "latest_registry_version")
    @patch.object(publish, "git", return_value="v.0.2.0\narchive")
    def test_no_valid_tags_skips_without_registry_call(self, git, registry):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(publish.decide(self.repo)["publish"], "false")
        registry.assert_not_called()

    @patch.object(publish, "latest_registry_version")
    @patch.object(publish, "git")
    def test_newer_equal_older_and_first_publications(self, git, registry):
        git.side_effect = lambda repo, command, *args: (
            COMMIT
            if command == "rev-parse"
            else '[project]\nname = "registry-node"\nversion = "4.1.2"'
        )
        for latest, expected in [
            (None, "true"),
            ("4.1.1", "true"),
            ("4.1.2-rc32", "true"),
            ("4.1.2", "false"),
            ("4.2.0", "false"),
        ]:
            with self.subTest(latest=latest):
                registry.return_value = latest
                decision = publish.decide(self.repo, "v4.1.2")
                self.assertEqual(decision["publish"], expected)
                self.assertEqual(decision["commit"], COMMIT)
                registry.assert_called_with("registry-node")
        # Both annotated and lightweight tags must resolve to a commit, not a tag object.
        self.assertIn(
            unittest.mock.call(
                self.repo, "rev-parse", "--verify", "refs/tags/v4.1.2^{commit}"
            ),
            git.call_args_list,
        )
        self.assertIn(
            unittest.mock.call(self.repo, "show", f"{COMMIT}:pyproject.toml"),
            git.call_args_list,
        )

    @patch.object(publish, "latest_registry_version")
    @patch.object(publish, "git")
    def test_bad_release_metadata_fails_before_registry(self, git, registry):
        for metadata in [
            "not toml",
            "[tool.other]\nx = 1",
            '[project]\nversion = "4.1.2"',
            '[project]\nname = "node"',
            '[project]\nname = "node"\nversion = "4.1.1"',
        ]:
            with self.subTest(metadata=metadata):
                git.side_effect = [COMMIT, metadata]
                with self.assertRaises(publish.PublishError):
                    publish.decide(self.repo, "v4.1.2")
        registry.assert_not_called()

    @patch.object(publish.subprocess, "run")
    def test_nonexistent_tag_fails_without_registry(self, run):
        run.return_value = subprocess.CompletedProcess([], 128, "", "unknown revision")
        with patch.object(publish, "latest_registry_version") as registry:
            with self.assertRaisesRegex(publish.PublishError, "Git read failed"):
                publish.decide(self.repo, "v4.1.2")
            registry.assert_not_called()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.urlopen = patch.object(publish.urllib.request, "urlopen").start()
        self.addCleanup(patch.stopall)

    def respond(self, data, status=200):
        response = io.BytesIO(json.dumps(data).encode())
        response.status = status
        self.urlopen.return_value = response

    def test_all_statuses_and_numeric_order_are_considered(self):
        self.respond(
            [
                {"version": "4.1.2", "status": "NodeVersionStatusActive"},
                {"version": "4.2.0", "status": "NodeVersionStatusDeleted"},
                {"version": "4.10.0-rc32", "status": "NodeVersionStatusFlagged"},
                {"version": "4.10.0-rc2", "status": "NodeVersionStatusPending"},
            ]
        )
        self.assertEqual(
            publish.latest_registry_version("registry-node"), "4.10.0-rc32"
        )
        request = self.urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://api.comfy.org/nodes/registry-node/versions"
        )
        self.assertEqual(self.urlopen.call_args.kwargs["timeout"], 30)

    def test_empty_list_is_the_only_empty_registry_result(self):
        self.respond([])
        self.assertIsNone(publish.latest_registry_version("node"))
        for data in [None, {}, {"versions": []}, [None], [{}], [{"version": "bad"}]]:
            with self.subTest(data=data):
                self.respond(data)
                with self.assertRaises(publish.PublishError):
                    publish.latest_registry_version("node")

    def test_http_and_connection_errors_fail(self):
        errors = [
            TimeoutError("timed out"),
            urllib.error.URLError("DNS failed"),
            *[
                urllib.error.HTTPError(
                    "https://api.comfy.org", code, "failure", {}, None
                )
                for code in (401, 403, 404, 429, 500)
            ],
        ]
        for error in errors:
            with self.subTest(error=error):
                self.urlopen.side_effect = error
                with self.assertRaisesRegex(
                    publish.PublishError, "Registry request failed"
                ):
                    publish.latest_registry_version("node")

    def test_unexpected_status_and_invalid_json_fail(self):
        self.respond([], status=204)
        with self.assertRaises(publish.PublishError):
            publish.latest_registry_version("node")
        response = io.BytesIO(b"<html>unavailable</html>")
        response.status = 200
        self.urlopen.return_value = response
        with self.assertRaises(publish.PublishError):
            publish.latest_registry_version("node")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "output"
        self.summary = Path(self.temp.name) / "summary"
        self.environment = patch.dict(
            os.environ,
            {
                "GITHUB_OUTPUT": str(self.output),
                "GITHUB_STEP_SUMMARY": str(self.summary),
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @patch.object(
        publish,
        "decide",
        side_effect=publish.PublishError("Registry request failed: timed out"),
    )
    def test_error_exits_nonzero_and_disables_publish(self, decide):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(publish.main([]), 1)
        self.assertEqual(self.output.read_text(), "publish=false\n")
        self.assertIn("::error::Registry request failed: timed out", errors.getvalue())
        self.assertIn("Publication check failed", self.summary.read_text())

    @patch.object(publish, "decide")
    def test_success_exports_exact_commit_and_decision(self, decide):
        decide.return_value = {
            "publish": "true",
            "tag": "v4.1.2",
            "commit": COMMIT,
            "latest": "4.1.1",
            "reason": "Newer",
        }
        with redirect_stdout(io.StringIO()):
            self.assertEqual(publish.main(["--repo", "checkout", "--tag", "v4.1.2"]), 0)
        self.assertEqual(
            self.output.read_text(), f"publish=true\ntag=v4.1.2\ncommit={COMMIT}\n"
        )
        self.assertIn("4.1.1", self.summary.read_text())


if __name__ == "__main__":
    unittest.main()
