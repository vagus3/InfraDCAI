import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from decision_monitor.cli import exit_code
from decision_monitor.engine import acknowledgement_state, evaluate, finding_fingerprint
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

    def _evaluate_tf(self, body: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            infra = root / "infra"
            infra.mkdir()
            (infra / "main.tf").write_text(body, encoding="utf-8")
            return evaluate([DECISIONS[2]], {}, root)[0]

    def test_generated_securestring_secret_is_violation(self):
        result = self._evaluate_tf(
            'resource "aws_ssm_parameter" "password" {\n'
            '  name = "/demo/password"\n'
            '  type = "SecureString"\n'
            "  value = random_password.db.result\n"
            "}\n"
        )
        self.assertEqual(result.status, DecisionStatus.VIOLATED)
        kinds = [f["kind"] for f in result.evidence[0].details["findings"]]
        self.assertEqual(kinds, ["generated_secret"])

    def test_placeholder_securestring_is_still_a_violation(self):
        # The point of the corrected rule: a literal placeholder plus
        # ignore_changes does not keep the value out of state, because the
        # provider reads it back decrypted on every refresh.
        result = self._evaluate_tf(
            'resource "aws_ssm_parameter" "token" {\n'
            '  name = "/demo/token"\n'
            '  type = "SecureString"\n'
            '  value = "set-me-with-the-aws-cli"\n'
            "  lifecycle {\n"
            "    ignore_changes = [value]\n"
            "  }\n"
            "}\n"
        )
        self.assertEqual(result.status, DecisionStatus.VIOLATED)
        kinds = [f["kind"] for f in result.evidence[0].details["findings"]]
        self.assertEqual(kinds, ["terraform_managed"])

    def test_securestring_without_a_value_argument_is_valid(self):
        # The shape write-only / ephemeral arguments take: Terraform declares
        # the parameter but never carries the value.
        result = self._evaluate_tf(
            'resource "aws_ssm_parameter" "managed_elsewhere" {\n'
            '  name = "/demo/elsewhere"\n'
            '  type = "SecureString"\n'
            "}\n"
        )
        self.assertEqual(result.status, DecisionStatus.VALID)

    def _ack(self, result, **overrides):
        ack = {
            "accepted_on": "2026-09-19",
            "expires_on": "2026-12-31",
            "owner": "someone",
            "reason": "known, scheduled",
            "fingerprint": finding_fingerprint(result),
        }
        ack.update(overrides)
        result.acknowledgement = ack
        return result

    def test_findings_use_repo_relative_paths(self):
        # An absolute path would make the fingerprint differ between a laptop
        # and CI, so every run would look like drift.
        result = self._evaluate_tf(
            'resource "aws_ssm_parameter" "password" {\n'
            '  name = "/demo/password"\n'
            '  type = "SecureString"\n'
            "  value = random_password.db.result\n"
            "}\n"
        )
        files = [f["file"] for f in result.evidence[0].details["findings"]]
        self.assertEqual(files, ["infra/main.tf"])

    def test_acknowledgement_must_be_complete_unexpired_and_bound(self):
        result = self._evaluate_tf(
            'resource "aws_ssm_parameter" "password" {\n'
            '  name = "/demo/password"\n'
            '  type = "SecureString"\n'
            "  value = random_password.db.result\n"
            "}\n"
        )
        today = date(2026, 9, 19)

        result.acknowledgement = None
        self.assertEqual(acknowledgement_state(result, today), "none")

        # Merely existing is not enough -- that was the original bug.
        result.acknowledgement = {"owner": "someone"}
        self.assertEqual(acknowledgement_state(result, today), "malformed")

        self._ack(result, expires_on="2026-09-18")
        self.assertEqual(acknowledgement_state(result, today), "expired")

        self._ack(result, fingerprint="0000000000000000")
        self.assertEqual(acknowledgement_state(result, today), "stale")

        self._ack(result)
        self.assertEqual(acknowledgement_state(result, today), "active")

    def test_acknowledgement_goes_stale_when_the_violation_grows(self):
        one = (
            'resource "aws_ssm_parameter" "a" {\n'
            '  name = "/demo/a"\n'
            '  type = "SecureString"\n'
            '  value = "placeholder"\n'
            "}\n"
        )
        accepted = self._ack(self._evaluate_tf(one))
        self.assertEqual(acknowledgement_state(accepted, date(2026, 9, 19)), "active")

        # A second parameter appears. The old acknowledgement covered one
        # finding, so it must not keep silencing the check.
        worse = self._evaluate_tf(
            one
            + 'resource "aws_ssm_parameter" "b" {\n'
            '  name = "/demo/b"\n'
            '  type = "SecureString"\n'
            "  value = random_password.b.result\n"
            "}\n"
        )
        worse.acknowledgement = accepted.acknowledgement
        self.assertEqual(acknowledgement_state(worse, date(2026, 9, 19)), "stale")
        self.assertEqual(exit_code([worse]), 1)

    def test_acknowledged_violation_does_not_block_ci(self):
        violated = self._evaluate_tf(
            'resource "aws_ssm_parameter" "password" {\n'
            '  name = "/demo/password"\n'
            '  type = "SecureString"\n'
            "  value = random_password.db.result\n"
            "}\n"
        )
        self.assertEqual(violated.status, DecisionStatus.VIOLATED)

        violated.acknowledgement = None
        self.assertEqual(exit_code([violated]), 1)

        self._ack(violated)
        self.assertEqual(exit_code([violated]), 0)


if __name__ == "__main__":
    unittest.main()
