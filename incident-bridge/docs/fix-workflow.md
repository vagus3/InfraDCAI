# Fix workflow

Incident Bridge가 source code를 직접 수정하지는 않습니다.

incident를 triage한 뒤 `FixTaskBuilder`가 작업 파일을 만듭니다.

예:

```text
incidentops/data/artifacts/INC-12AB34CD-fix.md
```

작업 파일에는 다음 정보가 들어갑니다.

- 어떤 증상이 있었는지
- 현재 확인된 사실
- 예상 원인
- 수정 가능한 파일 경로
- 수정 후 확인할 항목

Codex나 별도 GitHub workflow에 연결하고 싶다면:

```bash
INCIDENTOPS_FIX_WEBHOOK_URL=...
```

을 설정합니다.

workflow에서 권장하는 순서는 다음과 같습니다.

```text
Fix task
  ↓
Branch / PR
  ↓
Tests
  ↓
Review / Merge
  ↓
Deploy
  ↓
Live service check
```

장애 원인이 불분명하거나 capacity/architecture 문제인 경우에는 fix task 생성을 막고 사람이 검토하도록 합니다.
