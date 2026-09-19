"""Run the password bootstrap with a fake AWS CLI, never real credentials."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def rendered_template():
    # Substitute this template's inputs only; this is not Terraform validation.
    values = {
        "ssm_prefix": "/bootstrap-test",
        "aws_region": "ap-northeast-2",
        "site_address": "example.test",
        "ecr_repo_url": "example.test/app",
        "ecr_registry": "example.test",
        "openai_model": "test-model",
    }
    source = (ROOT / "infra/user-data.sh.tftpl").read_text()
    source = re.sub(
        r"(?<!\$)\$\{(" + "|".join(values) + r")\}",
        lambda match: values[match[1]],
        source,
    )
    return source.replace("$${", "${")


def test_rendered_user_data_has_valid_shell_syntax():
    subprocess.run(["bash", "-n"], input=rendered_template(), text=True, check=True)


@pytest.mark.parametrize(
    "mode,success,writes",
    [
        ("placeholder", True, True),
        ("existing", True, False),
        ("read_failure", False, False),
        ("partial_read_failure", False, False),
        ("write_failure", False, True),
    ],
)
def test_password_bootstrap(tmp_path, mode, success, writes):
    mock = tmp_path / "aws"
    mock.write_text(
        f"#!{sys.executable}\n"
        + '''import json
import os
from pathlib import Path
import stat
import sys

mode = os.environ["BOOTSTRAP_TEST_MODE"]
args = sys.argv[1:]
if args[:2] == ["ssm", "get-parameter"]:
    if mode.endswith("read_failure"):
        if mode == "partial_read_failure":
            print("partial-output")
        sys.exit(1)
    print("existing-test-password" if mode == "existing" else "set-me-with-the-aws-cli")
elif args[:2] == ["ssm", "put-parameter"]:
    value = args[args.index("--value") + 1]
    assert value.startswith("file://"), "secret must not be passed in argv"
    path = Path(value.removeprefix("file://"))
    record = {
        "path": str(path), "permissions": stat.S_IMODE(path.stat().st_mode),
        "password": path.read_text(), "argv": args,
    }
    Path(os.environ["BOOTSTRAP_TEST_RECORD"]).write_text(json.dumps(record))
    sys.exit(1 if mode == "write_failure" else 0)
else:
    sys.exit(2)
'''
    )
    mock.chmod(0o700)
    record_path = tmp_path / "record.json"
    source = rendered_template()
    start = source.index('PLACEHOLDER="')
    end = source.index("\n\n# ---------------------------------------------------------------------------", start)
    run = subprocess.run(
        ["bash", "-c", "set -euxo pipefail\n" + source[start:end]],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "TMPDIR": str(tmp_path),
            "BOOTSTRAP_TEST_MODE": mode,
            "BOOTSTRAP_TEST_RECORD": str(record_path),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (run.returncode == 0) == success
    assert record_path.exists() == writes
    output = run.stdout + run.stderr
    assert "existing-test-password" not in output
    assert "partial-output" not in output
    if writes:
        record = json.loads(record_path.read_text())
        assert re.fullmatch(r"[0-9a-f]{64}", record["password"])
        assert record["permissions"] == 0o600
        assert record["password"] not in output
        assert record["password"] not in " ".join(record["argv"])
        # Includes the failing PutParameter path: neither leaks a temp file.
        assert not Path(record["path"]).exists()
