# Incident Bridge 학습 지도

공식 자료 확인일: 2026-09-19. 아래는 학습·실험 제안이며 구현 완료 목록이 아니다.
성공 정의와 시스템 규약은 [DESIGN.md](DESIGN.md), 실제 관찰은
[스트리밍 실패 실험](docs/experiments/2026-09-19-streaming-failure.md)에 둔다.
문서를 읽었다는 사실과 실험을 통과했다는 사실을 구분한다.

## 먼저 공부할 순서

| 우선순위 | 주제 | 이 저장소에서 답할 질문 | 이해했다는 증거 |
|---|---|---|---|
| 제출 전 | 사용자 경험과 스트리밍 관측 | 왜 HTTP 200·ready 정상인데 답변은 실패하는가? | 같은 요청의 상태 코드·content·종료 이유를 비교한 기록 |
| 제출 전 | 회복 검증과 데이터 품질 | 정상 신호가 안 오는 상황과 서비스가 정상인 상황을 어떻게 구별하는가? | 증거 누락·오래된 결과로는 종료되지 않는 반례 |
| 제출 전 | IAM·OIDC·시크릿 소유권 | 누가 비밀을 생성·읽고, 어느 경로에 남기는가? | 값 없이 그린 권한/데이터 흐름과 실패 경로 검증 |
| 제출 전 | 재현 가능한 배포와 테스트 | 테스트 성공이 실제 앱 동작을 보장하는가? | 동일 버전의 가입→로그인→스트림 확인, 배포 증거 |
| AI 연결 시 | 근거 기반 triage 평가 | AI가 규칙보다 나은 점과 틀리는 조건은 무엇인가? | 고정 사례의 규칙/모델 결과 비교 |
| 제출 후 | SLO·burn rate·복구 목표 | 언제 호출할 정도로 심각하며, 얼마나 오래/많이 잃을 수 있는가? | 트래픽 규모에 맞춘 경보·RTO/RPO 판단 |

## 1. 스트리밍과 OpenTelemetry

읽을 코드: `app/main.py`, `app/routers/chat.py`, `app/llm.py`,
`incidentops/collectors/http_probe.py`.

먼저 HTTP 응답 시작, 첫 답변 content, 정상 완료의 시각을 구별한다. 현재 미들웨어 시간과
`/ready`의 단일 응답 시간은 사용자 답변 완료 시간이 아니다. 상태 이벤트는 답변 content가 아니다.
upstream의 조기 EOF도 정상 종료와 구분해야 한다.

프로젝트에 적용할 연습:

- 정상·즉시 오류·첫 답변 지연·중간 끊김을 통제된 upstream으로 비교한다.
- 서버 처리 시간과 외부 client가 본 시간을 나란히 기록한다. 어느 경계를 측정했는지 적는다.
- request_id/trace_id는 개별 사건 연결에 쓰고, 무제한 ID나 고객 원문을 metric label에 넣지 않는다.
- p95에는 측정 구간과 표본 수를 붙인다. 적은 표본은 개별 지연과 성공/시도 건수부터 보여준다.

최신 참고: OpenTelemetry의 GenAI semantic conventions는 별도 저장소로 이전됐다.
채택할 때는 사용한 버전과 각 항목의 안정성 표시를 확인한다. 오늘의 속성 이름을 영구 표준으로
가정하지 않는다. 이 프로젝트가 OTel을 이미 구현했다는 뜻은 아니다.
[이전 안내](https://opentelemetry.io/docs/specs/semconv/gen-ai/),
[현재 규약 저장소](https://github.com/open-telemetry/semantic-conventions-genai).

## 2. 사건 연결·재시도·회복

읽을 코드: `incidentops/matching.py`, `incident_store.py`, `service.py`.

같은 이벤트의 재전송과 별개의 사용자 실패를 구분하는 것이 멱등성의 출발점이다.
서비스가 조용하다는 이유만으로 회복됐다고 판단하지 않는다. collector가 멈췄을 수도 있다.

직접 답해 볼 질문:

- 같은 tenant의 로그인 장애와 스트리밍 장애를 합쳐도 되는가?
- 사건 발생 시각과 수신 시각이 다르면 어느 구간에 연결하는가?
- 이전 배포에서 성공한 결과를 새 배포의 회복 증거로 쓰지 않으려면 무엇을 비교하는가?
- 확인 요청 자체가 실패하면 VERIFYING을 유지할지, 언제 사람에게 넘길지?

답은 [DESIGN.md](DESIGN.md)의 규약과 연결하고, 실제 실행한 반례만 실험 기록에 남긴다.
DB 교체나 메시지 브로커 도입은 이 질문을 대신 해결하지 않는다.

## 3. Terraform 비밀·IAM·OIDC

읽을 코드: `infra/main.tf`, `infra/github_oidc.tf`, `infra/user-data.sh.tftpl`.

구분할 것: 저장소에 없는 비밀, CLI에서 가려진 비밀, 로그에 없는 비밀, state에 없는 비밀은
각각 다른 주장이다. 현재 ADR-010은 승인된 위반으로 남아 있다.

HashiCorp는 `sensitive` 표시와 state/plan에서 값을 제외하는 ephemeral·write-only 기능을
구별한다. 후자는 Terraform과 provider의 지원 조건을 확인해야 한다. 기존 resource에
`ignore_changes`를 추가했다고 그 기능을 얻는 것은 아니다.
[공식 민감 데이터 안내](https://developer.hashicorp.com/terraform/language/manage-sensitive-data).

연습은 비밀이 아닌 테스트 표식으로 한다. 이미 배포된 파라미터를 Terraform 관리에서 빼려면
리소스 삭제와 관리 소유권 이전을 구분하고, 과거 state 이력도 별도로 검토한다. 임의 apply는 하지 않는다.

OIDC는 장기 키를 없애도 신뢰 조건이 잘못되면 안전하지 않다. 실제 저장소의 subject, environment,
브랜치 보호, 최소 권한을 함께 확인한다. GitHub 공식 문서의 불변 commit SHA로 action 고정,
최소 token 권한, 신뢰하지 않는 입력을 shell 코드에 직접 넣지 않는 원칙도 학습한다.
[OIDC](https://docs.github.com/en/actions/reference/security/oidc),
[workflow 보안](https://docs.github.com/en/actions/reference/security/secure-use).

## 4. AI 평가와 권한 경계

읽을 코드: `incidentops/triage.py`, `fix_tasks.py`, `integrations/fix_webhook.py`.

OpenAI의 agent 평가 안내는 실행 trace로 문제를 찾고, 반복 비교에는 dataset과 eval run을
사용하는 접근을 설명한다. 이 프로젝트에서는 특정 유료 평가 제품을 도입하기 전에 작은
고정 사례 집합과 사람이 확인할 평가표로 시작해도 된다.
[공식 agent 평가 안내](https://developers.openai.com/api/docs/guides/agent-evals).

제안하는 사례는 정상, upstream 오류, 첫 답변 지연, DB 실패, 증거 부족이다. 모델·프롬프트 버전을
기록하고 같은 입력으로 규칙 기반 결과와 비교한다. 다음 항목을 따로 채점한다.

- 원인 후보가 근거와 맞는지, 인용한 evidence_id가 실제로 존재하고 내용을 뒷받침하는지.
- 증거가 부족할 때 판단을 보류하는지, 불필요한 위험 조치를 권하지 않는지.
- 분석 지연·호출 수·실측 또는 명시된 추정 비용. 5사례 성적으로 일반 정확도를 주장하지 않는다.

고객 문의·로그 안의 ‘이 명령을 실행하라’는 문장은 입력 데이터다. OWASP는 이런 외부 자료를 통한
간접 prompt injection을 다룬다. 모델에 경고 문구만 넣는 것으로 끝내지 말고, 실행 도구의 권한과
허용 작업을 코드·IAM에서 제한해야 한다. `allowed_paths` 문자열은 실행 환경의 강제 제한이 아니다.
[OWASP Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/).

## 5. SLO와 복구 목표 — 제출 후 확장

Google SRE의 burn rate는 SLO의 허용 오류 예산을 얼마나 빨리 쓰는지 나타낸다. baseline보다
지연이 몇 배 늘었는지를 보는 상대적 탐지와는 다른 질문이다. 먼저 무엇을 성공으로 셀지 정한다.
저트래픽 서비스는 한 번의 실패에도 비율이 크게 움직이므로 일반 경보 수치를 그대로 옮기지 않는다.
[SLO 기반 경보와 저트래픽 고려사항](https://sre.google/workbook/alerting-on-slos/).

이 프로젝트에서는 readiness, 실제 스트림 완료, synthetic 요청, 실제 사용자 요청을 구분해서 본다.
‘5회 연속 성공’은 데모의 완료 조건이지 운영 가용성 보장이 아니다.

추가로 RTO(복구까지 허용 시간), RPO(허용 데이터 손실 구간)를 정하고 백업을 실제로 복원해 본다.
이미지 rollback은 DB 데이터·비밀번호를 이전 상태로 되돌리지 않는다. 단일 EC2의 고장 범위와
감시자가 같은 서버에 있을 때의 한계도 설명할 수 있어야 한다.

## 6. 에이전트 지침 관리

공통 지침은 루트 [AGENTS.md](../AGENTS.md)에 둔다. Codex는 정해진 파일명과 디렉터리 순서로
지침을 찾으므로 임의의 `agent.md` 파일이 자동으로 읽힌다고 가정하지 않는다.
[OpenAI AGENTS.md 안내](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

현재 Claude 공식 문서는 버전·설정에 따른 직접 AGENTS.md 로딩과 `CLAUDE.md`의 `@AGENTS.md`
import를 모두 설명한다. 이 저장소에는 import만 있는 연결 파일을 둬 공통 규칙의 복제를 피한다.
새 세션에서 실제 읽은 지침을 확인하고, 안내 문서를 실행 권한이나 강제 보안 장치로 착각하지 않는다.
[Claude 프로젝트 지침 안내](https://code.claude.com/docs/en/memory).

문서는 실행 결과와 함께 갱신한다. 학습 주제를 읽었다는 이유로 패키지 업그레이드, MCP 서버 추가,
멀티에이전트 전환을 자동으로 수행하지 않는다. 필요성과 검증 방법이 생겼을 때 별도 작업으로 판단한다.
