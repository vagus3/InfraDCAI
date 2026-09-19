# AGENTS.md

코딩 에이전트를 위한 문서다. 코드를 열어보면 알 수 있는 내용은 적지 않는다. 읽지 않으면
반드시 틀리는 것만 적는다.

## 저장소 배치

git 루트는 `InfraDCAI`이고 프로젝트는 `incident-bridge/` 하위에 있다. 이 차이 때문에 함정이 하나 있다.

- GitHub은 저장소 루트의 `.github/workflows/`만 워크플로우로 인식한다. 그래서 워크플로우
  파일은 루트에 두고, 각 job에 `defaults.run.working-directory: incident-bridge`를 건다.
- `uses:` 스텝에는 `working-directory`가 적용되지 않는다. `actions/upload-artifact`의 `path`
  같은 값은 저장소 루트 기준으로 써야 한다.
- 워크플로우를 `incident-bridge/.github/`로 되돌리지 말 것. 그렇게 하면 조용히 아무것도
  실행되지 않는다. 실패도 아니고 그냥 실행이 안 된다.

## 실행

가상환경은 `incident-bridge/.venv`에 있다. 모든 명령은 `incident-bridge/`에서 실행한다.

Python은 3.11을 쓴다. 3.13 이상에서는 `asyncpg` 휠 빌드가 실패한다. 검증된 조합은 3.11.15다.

`requirements.txt`(앱)와 `incidentops/requirements.txt`(운영 도구)는 별개다. 테스트만 돌린다면
후자로 충분하지만, 앱을 기동하려면 둘 다 필요하다.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r incidentops/requirements.txt

PYTHONPATH=. .venv/bin/python -m pytest -q incidentops/tests decision_monitor/tests
PYTHONPATH=. .venv/bin/python -m incidentops.demo all
PYTHONPATH=. .venv/bin/python -m decision_monitor.cli repo --root .
PYTHONPATH=. .venv/bin/python -m uvicorn incidentops.api:app --port 8090
```

`PYTHONPATH=.`를 빼면 import가 깨진다. 패키지가 설치되는 형태가 아니라 경로 기반이다.

## 변경 전에 알아야 할 사실

아래는 전부 확인된 내용이다. 이걸 모르고 고치면 틀린 주장을 문서에 쓰게 된다.

- ADR-010은 미해결이다. Terraform이 `aws_ssm_parameter`를 관리하는 한, provider가 refresh 때
  `WithDecryption`으로 값을 읽어 state에 쓴다. `ignore_changes`는 plan의 diff를 막을 뿐
  read를 막지 않는다. 이 문제가 해결됐다고 쓰지 말 것. `decision_monitor`가 이 상태를
  VIOLATED로 보고하며, 승인 기록이 있어서 CI는 막지 않는다.
- `app/main.py`의 `duration_ms`는 스트림 완료 시간이 아니다. `call_next()`는 `StreamingResponse`
  객체가 만들어지는 시점에 반환되고 본문은 그 뒤에 흐른다. `/chat/stream`의 실제 응답 시간을
  재려면 제너레이터 안에서 계측해야 한다.
- `incidentops/collectors/http_probe.py`가 보내는 `p95_latency`는 표본 1개다. 백분위수가 아니다.
- `app/routers/chat.py`는 upstream 오류를 HTTP 200 스트림 안의 error 이벤트로 내보낸다.
  그래서 5xx 비율과 `/ready`만 보면 이 실패가 보이지 않는다. 이 프로젝트의 대표 실험이 바로
  이 실패를 관측 가능하게 만드는 것이다.
- `app/` 에는 테스트가 없다. `pytest`가 통과해도 앱이 기동한다는 뜻이 아니다. requirements의
  핀 문제로 회원가입이 전부 500을 반환하던 동안에도 테스트는 전부 통과했다. 기록은
  `docs/experiments/2026-09-19-streaming-failure.md`에 있다.
- `user-data.sh.tftpl`은 `set -euxo pipefail` 상태다. 여기서 시크릿을 다루는 명령은 추적에
  그대로 찍히고, 그 출력은 `aws ec2 get-console-output`으로 읽힌다. `deploy.sh`가 `-x`를 빼둔
  이유가 이것이다.

## 하지 말 것

- `terraform apply`를 임의로 실행하지 않는다. 비용이 발생하고 되돌리기 어렵다.
- `.env`, `*.tfvars`, `*.tfstate`, `.venv`를 커밋하지 않는다.
- 시크릿을 명령행 인자나 로그에 노출하지 않는다.
- 미검증 내용을 검증된 것처럼 쓰지 않는다. `RUNBOOK.md`의 검증일 표와 `K8S-PLAN.md`는
  직접 실행한 뒤에만 채운다.

## 검증 방법

변경을 넣었으면 최소한 아래를 통과해야 한다.

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q incidentops/tests decision_monitor/tests
PYTHONPATH=. .venv/bin/python -m decision_monitor.cli repo --root .   # exit 0 이어야 함
```

`decision_monitor`가 0이 아닌 코드로 끝나면, 승인되지 않은 아키텍처 결정 위반이 생긴 것이다.
승인 없이 통과시키려고 `|| true`를 붙이지 말 것. `decisions.json`에 승인 기록을 남기거나
위반을 고치거나 둘 중 하나다.

## 문서 역할 분담

새 내용을 아무 파일에나 덧붙이지 않는다. 시제로 구분한다.

| 파일 | 시제 | 담는 것 |
|---|---|---|
| `README.md` | - | 무엇이고 어떻게 실행하는가 |
| `DECISIONS.md` | 과거 | 왜 그렇게 골랐나, 무엇과 비교했나, 언제 뒤집나 |
| `DESIGN.md` | 현재 당위 | 무엇이 참이어야 하나 (성공의 정의, 증거 규약, 판정 기준) |
| `RUNBOOK.md` | 명령 | 장애 시 지금 무엇을 하라 |
| `docs/architecture.md` | 현재 서술 | 구성 요소와 데이터 흐름 |
| `LEARNING.md` | - | 이 프로젝트로 무엇을 배우는가 |

같은 주제라도 시제가 다르면 다른 파일이다. 예를 들어 "SecureString을 왜 이렇게 다루나"는
`DECISIONS.md`, "무엇이 위반인가"는 `DESIGN.md`, "유출됐을 때 무엇을 하나"는 `RUNBOOK.md`다.
