# Incident Bridge

운영 중인 서비스에서 고객 문의와 모니터링 알람이 서로 따로 움직이는 문제를 확인하기 위해 만든 실험 프로젝트입니다.

모니터링은 정해둔 임계치를 넘는 문제는 잘 찾지만, 고객이 먼저 체감하는 성능 저하는 놓칠 수 있습니다. 반대로 CPU나 오류율이 잠깐 올라가도 실제 고객 영향은 없을 수 있습니다.

이 프로젝트에서는 고객 문의와 최근 서비스 지표를 같은 incident에 묶고, 수정 후에는 CI 성공 여부가 아니라 실제 서비스 상태가 회복됐는지까지 확인합니다.

## 현재 구현 범위

- 5xx, p95 latency, readiness 신호 수집
- 고객 문의 메일을 tenant 기준으로 최근 지표와 연결
- 이미 열린 incident가 있으면 고객 문의를 같은 사건에 추가
- 고객이 먼저 문제를 발견한 경우 최근 지표에서 놓친 변화 확인
- incident 유형 분류 및 다음 조치 작성
- 수정 작업용 문서 생성 (`allowed paths`, 확인 항목 포함)
- CI / 배포 / 운영 상태 확인 후 incident 종료
- 고객 안내 문안 생성
- Architecture Decision Monitor와 연계 가능한 구조

외부 LLM이나 Codex 연동은 선택 사항입니다. 기본 동작은 규칙 기반으로 실행되며, 외부 triage/fix workflow가 필요할 때 webhook으로 교체할 수 있습니다.

## 흐름

```text
Service metrics ──────────────┐
                             │
Customer email ──────────────┼─> Incident
                             │      │
Decision check ──────────────┘      ├─> Triage
                                    ├─> Fix task
                                    ├─> CI / Deploy
                                    └─> Live service check
                                             │
                                      RESOLVED / ESCALATED
```

## 데모 1: 모니터링이 먼저 발견한 경우

1. `/chat`의 5xx rate가 설정값을 넘습니다.
2. incident가 생성됩니다.
3. 이후 고객 문의가 들어오면 기존 incident에 연결됩니다.
4. 두 시각의 차이를 기록합니다.
5. 수정/rollback 후 서비스 상태를 다시 확인합니다.

예시:

```text
14:00  5xx alert -> incident opened
14:06  customer email received

customer report lag: 360s
```

여기서 보고 싶은 것은 단순히 "알람이 울렸다"가 아니라, 고객 신고 전에 문제를 발견할 수 있었는지입니다.

## 데모 2: 고객 문의가 먼저 들어온 경우

현재 latency alert를 `p95 >= 5s`로 설정했다고 가정합니다.

```text
baseline p95    1.1s
current p95     3.7s
alert threshold 5.0s
```

알람은 울리지 않지만 고객 입장에서는 응답 시간이 3배 이상 늘었습니다.

고객이 "응답이 느려졌다"고 문의하면 최근 tenant 지표를 확인하고 다음 내용을 incident에 남깁니다.

```text
The 5.0s latency alert did not fire even though
p95 increased from 1.10s to 3.70s (3.4x).
```

이 결과를 이후 alert/SLI 개선의 근거로 사용할 수 있습니다.

## 실행

검증한 로컬 환경은 Python 3.11.15입니다. 아래 설치는 운영 도구용이며, 감시 대상 채팅 앱을
기동하려면 별도로 `requirements.txt`의 의존성도 필요합니다.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r incidentops/requirements.txt
export PYTHONPATH=.

make test
make demo
```

API와 대시보드를 실행하려면:

```bash
make serve
```

브라우저에서 `http://127.0.0.1:8090`을 엽니다.

## 실제 서비스 지표 연결

기존 Mini ChatGPT 서비스의 `/health`, `/ready`를 간단히 수집할 수 있습니다.

```bash
python -m incidentops.collectors.http_probe \
  --target https://YOUR-WORKLOAD \
  --ingest http://127.0.0.1:8090 \
  --tenant demo-customer \
  --interval 15
```

## 고객 메일 연결

메일 시스템 자체를 incident 코드 안에 넣지 않았습니다. Gmail, SES, n8n 등의 workflow에서 필요한 값만 정리해서 아래 endpoint로 전달합니다.

```http
POST /api/v1/customer-email
```

```json
{
  "tenant": "company-b",
  "customer": "Beta Support",
  "subject": "응답 속도가 너무 느립니다",
  "body": "평소보다 응답이 오래 걸립니다."
}
```

메일을 받은 뒤 바로 장애라고 단정하지 않고, 최근 서비스 지표와 같이 봅니다.

## 수정 workflow 연결

Incident Bridge는 직접 repository를 수정하지 않습니다. triage 결과를 바탕으로 수정 범위와 확인 항목이 적힌 task 파일을 만듭니다.

```text
incidentops/data/artifacts/INC-XXXXXXXX-fix.md
```

외부 Codex/GitHub workflow를 연결하려면 `INCIDENTOPS_FIX_WEBHOOK_URL`을 설정합니다.

수정 작업이 끝나도 incident는 바로 종료되지 않습니다. 다음 항목을 다시 확인합니다.

```text
CI passed
Deploy succeeded
Live service healthy
(optional) architecture decision check passed
```

하나라도 실패하면 `ESCALATED`로 남깁니다.

## 코드 구조

```text
incidentops/
├── matching.py        # metric / customer email을 incident에 연결
├── triage.py          # incident 유형과 다음 조치 판단
├── fix_tasks.py       # 수정 작업 문서 생성
├── incident_store.py  # sqlite 저장
├── reporting.py       # 운영 기록 / 고객 문안
├── api.py
└── collectors/

decision_monitor/      # DECISIONS.md와 실제 코드/인프라 확인
```

## 설계 메모

- 고객 문의는 사실 하나로 취급하지 않고 서비스 지표와 같이 확인합니다.
- CPU가 높다고 자동으로 EKS 이전 같은 결론을 내리지 않습니다.
- 외부 LLM은 triage나 수정 계획 보조에만 연결할 수 있습니다.
- 실제 incident 종료는 배포 후 서비스 확인 결과로 결정합니다.
- 고객에게 보내는 메일은 기본적으로 draft 생성까지만 하고 사람이 확인하는 흐름을 권장합니다.

자세한 내용은 [`docs/architecture.md`](docs/architecture.md), 실제 데모 조건은 [`docs/scenarios.md`](docs/scenarios.md)를 참고하세요.

학습 순서와 공식 참고 자료는 [`LEARNING.md`](LEARNING.md), 지켜야 할 규약과 미구현 범위는
[`DESIGN.md`](DESIGN.md)에 있습니다. 에이전트 작업 지침은 저장소 루트의 [`AGENTS.md`](../AGENTS.md)에서 관리합니다.
코드 작성·리뷰 기준과 아직 적용하지 않은 개선 후보는 [`CODE_RULES.md`](CODE_RULES.md)에 있습니다.
