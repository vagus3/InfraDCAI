import json
import tempfile
import unittest
from pathlib import Path

from decision_monitor.engine import evaluate
from decision_monitor.models import DecisionStatus


ROOT = Path(__file__).resolve().parents[2]
DECISIONS = json.loads((ROOT / "decision_monitor" / "decisions.json").read_text())["decisions"]


class DecisionEngineTests(unittest.TestCase):
    def test_public_ssh_is_violation_and_high_load_is_revisit(self):
        snapshot = json.loads(
            (ROOT / "decision_monitor" / "examples" / "violated-and-stale.json").read_text()
        )
        results = evaluate(DECISIONS[:2], snapshot, ROOT)
        by_id = {result.decision_id: result for result in results}
        self.assertEqual(by_id["ADR-008"].status, DecisionStatus.VIOLATED)
        self.assertEqual(by_id["ADR-001"].status, DecisionStatus.REVISIT_REQUIRED)

    def test_no_public_ssh_and_low_load_are_valid(self):
        snapshot = json.loads((ROOT / "decision_monitor" / "examples" / "compliant.json").read_text())
        results = evaluate(DECISIONS[:2], snapshot, ROOT)
        self.assertTrue(all(result.status == DecisionStatus.VALID for result in results))

    def test_generated_securestring_secret_is_violation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            infra = root / "infra"
            infra.mkdir()
            (infra / "main.tf").write_text(
                '''resource "aws_ssm_parameter" "password" {\n'''
                '''  name = "/demo/password"\n'''
                '''  type = "SecureString"\n'''
                '''  value = random_password.db.result\n'''
                '''}\n''',
                encoding="utf-8",
            )
            result = evaluate([DECISIONS[2]], {}, root)[0]
            self.assertEqual(result.status, DecisionStatus.VIOLATED)


if __name__ == "__main__":
    unittest.main()
