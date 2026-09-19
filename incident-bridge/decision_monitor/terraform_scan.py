"""Small, dependency-free Terraform source scanner.

This is deliberately narrow: it recognizes resource blocks and simple
assignments well enough to validate the ADR used by this repository. It is not
intended to replace Terraform's parser. A later version can swap this collector
for terraform show -json without changing the decision engine.
"""

from __future__ import annotations

import re
from pathlib import Path


RESOURCE_RE = re.compile(r'resource\s+"(?P<type>[^"]+)"\s+"(?P<name>[^"]+)"\s*\{')
ASSIGNMENT_RE_TEMPLATE = r"(?m)^\s*{key}\s*=\s*(?P<value>[^\n#]+)"


def _balanced_block(text: str, opening_brace: int) -> tuple[str, int]:
    depth = 0
    in_string = False
    escape = False
    for idx in range(opening_brace, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[opening_brace : idx + 1], idx + 1
    raise ValueError("Unbalanced Terraform block")


def iter_resource_blocks(text: str):
    pos = 0
    while match := RESOURCE_RE.search(text, pos):
        opening = text.find("{", match.start())
        block, end = _balanced_block(text, opening)
        yield match.group("type"), match.group("name"), block
        pos = end


def assignment(block: str, key: str) -> str | None:
    match = re.search(ASSIGNMENT_RE_TEMPLATE.format(key=re.escape(key)), block)
    if not match:
        return None
    return match.group("value").strip()


def scan_securestring_sources(root: Path) -> list[dict]:
    findings: list[dict] = []
    for tf_file in sorted(root.rglob("*.tf")):
        text = tf_file.read_text(encoding="utf-8")
        for resource_type, resource_name, block in iter_resource_blocks(text):
            if resource_type != "aws_ssm_parameter":
                continue
            param_type = assignment(block, "type")
            if not param_type or param_type.strip('"') != "SecureString":
                continue
            value = assignment(block, "value")
            if value is None:
                continue

            # Literal placeholders still enter state, but they are not secret
            # material. Dynamic secret sources (random_password, sensitive vars,
            # etc.) are the violation this ADR is meant to prevent.
            dynamic_secret = (
                "random_password." in value
                or re.search(r"\bvar\.(?:.*secret|.*password|.*token|.*key)\b", value, re.I)
                is not None
            )
            if dynamic_secret:
                findings.append(
                    {
                        "file": str(tf_file),
                        "resource": f"{resource_type}.{resource_name}",
                        "value_expression": value,
                        "message": "SecureString receives secret material through Terraform; the value will be represented in Terraform state.",
                    }
                )
    return findings
