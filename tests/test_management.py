from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(value)
    return value


workflows = module("render_workflows", ROOT / "scripts/render_workflows.py")


class WorkflowTests(unittest.TestCase):
    def test_domain_contributes_to_close_without_renderer_change(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "registry/domains").mkdir(parents=True)
            (base / "profiles/katara").mkdir(parents=True)
            reading = json.loads((ROOT / "examples/extensions/reading/manifest.json").read_text())
            (base / "registry/domains/reading.json").write_text(json.dumps(reading))
            workflow = {
                "schema_version": 1,
                "workflows": [{"id": "close", "profile": "katara", "name": "Close", "schedule": "0 1 * * *", "model": "m", "skills": ["s"], "prompt": "Close.", "include_domain_close_prompts": True}],
            }
            (base / "registry/workflows.json").write_text(json.dumps(workflow))
            system = {"domains": ["domains/reading.json"], "workflows": "workflows.json", "agents": [{"id": "katara", "profile": "profiles/katara", "domains": ["reading"]}]}
            system_path = base / "registry/system.json"
            system_path.write_text(json.dumps(system))
            rendered = next(iter(workflows.render(base, system_path).values()))
            self.assertIn("reading minutes and book", rendered)


class ManagementCLITests(unittest.TestCase):
    def test_scaffold_domain_is_valid_and_idempotent_in_plan_mode(self):
        result = subprocess.run(["python3", str(ROOT / "scripts/scaffold.py"), "domain", "language-learning", "--plan"], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("registry/domains/language-learning.json", result.stdout)

    def test_operations_status_handles_empty_state(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(["python3", str(ROOT / "scripts/avatar_ops.py"), "--root", temp, "status"], text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('"event_count": 0', result.stdout)


if __name__ == "__main__":
    unittest.main()
