# Architecture notes

## 왜 만들었나

운영 알람과 고객 문의를 따로 보면 두 가지 문제가 생깁니다.

1. 모니터링이 문제를 먼저 잡았는데 고객 문의를 별도 티켓으로 처리할 수 있습니다.
2. 고객은 문제를 느끼는데 기존 threshold는 정상이라고 판단할 수 있습니다.

그래서 둘을 tenant와 시간 범위를 기준으로 같은 incident에 연결합니다.

## Incident 상태

```text
OPEN
  ↓
TRIAGED
  ↓
READY_FOR_FIX
  ↓
FIX_IN_PROGRESS
  ↓
VERIFYING
  ├─ RESOLVED
  └─ ESCALATED
```

`RESOLVED`는 CI가 통과했다는 뜻이 아닙니다. 배포 후 실제 서비스 상태까지 정상이어야 합니다.

## 데이터 입력

### TelemetrySignal

현재는 다음 값만 다룹니다.

- `5xx_rate`
- `p95_latency`
- `readiness`

실서비스에서는 CloudWatch, Prometheus, OpenTelemetry 등의 collector로 대체할 수 있습니다.

### CustomerEmail

고객 문의에서 사용하는 값은 아래 정도로 제한했습니다.

- tenant
- customer
- subject
- body
- received_at

메일 provider 로직은 core에서 분리했습니다.

## 매칭 방식

현재 구현은 단순합니다.

1. 같은 tenant의 열린 incident 확인
2. 있으면 고객 메일/새 지표를 해당 incident에 추가
3. 없으면 최근 telemetry 조회
4. 고객이 성능 저하를 신고한 경우 baseline 대비 변화 확인

분산 tracing 기반 correlation은 아직 구현하지 않았습니다.

## Triage

기본 구현은 규칙 기반입니다.

```text
recent deployment found  -> CODE_REGRESSION
dependency signal found  -> DEPENDENCY_FAILURE
terraform / SG mismatch  -> INFRA_CONFIG
cpu / memory pressure    -> CAPACITY
otherwise                -> UNKNOWN
```

`CAPACITY`, `UNKNOWN`은 자동 수정 task를 만들지 않습니다.

외부 모델을 사용하고 싶다면 `INCIDENTOPS_TRIAGE_WEBHOOK_URL`을 설정할 수 있습니다. 모델 응답이 incident 종료 여부를 결정하지는 않습니다.

## Fix task

수정 workflow에 넘기는 문서는 다음 내용을 포함합니다.

- incident 요약
- 현재 확인된 사실
- 수정 가능한 경로
- 다음 확인 항목

repository 전체를 자유롭게 수정하도록 요청하지 않는 이유는 incident와 무관한 변경을 줄이기 위해서입니다.

## 배포 후 확인

수정 이후 아래 조건을 확인합니다.

```text
CI
Deploy
Production health
Decision check (optional)
```

실서비스 확인이 실패하면 CI가 성공했더라도 incident를 닫지 않습니다.

## 현재 한계

- SQLite 사용
- tenant + 시간 범위 기반 매칭
- 간단한 keyword 기반 고객 문의 분류
- built-in triage는 heuristic
- 메일 및 coding workflow는 외부 연결 필요
- 고객 메시지 자동 발송은 기본값으로 두지 않음
