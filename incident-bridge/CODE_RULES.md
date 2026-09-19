# 코드 작성과 리뷰 기준

2026-09-19의 실제 코드 검토를 바탕으로 작성했다. 규칙 추가와 코드의 준수 여부는 별개다.
이 문서 작성 작업에서는 애플리케이션·인프라 코드를 수정하지 않았다. 마지막 표는 향후 개선
후보이며 자동 실행할 작업 목록이 아니다. `DESIGN.md`는 동작의 의미, 이 문서는 구현 기준을 정한다.

특정 문법을 썼다는 이유로 ‘AI 코드’라고 판단하지 않는다. 명확성, 정확성, 중복된 정책,
불필요한 추상화, 측정 가능한 비용을 기준으로 리뷰한다.

## 1. 읽을 수 있는 코드와 주석

- 이름에 도메인과 단위를 드러낸다. 지연은 seconds/ms, 비율은 0~1인지 명시한다.
  `data`, `result`, `helper`, `manager` 같은 이름은 좁은 문맥에서 의미가 분명할 때만 쓴다.
- 제어 흐름을 따라갈 수 있는 명시적인 분기를 쓴다. 중첩 삼항식, 부수효과가 있는 comprehension,
  한 줄에 압축한 비동기 호출·예외 처리를 피한다.
- 함수는 이름으로 설명한 책임을 수행한다. 조회 함수에 파일 생성·알림 발송을 섞지 않는다.
  의미 없는 forwarding 메서드를 계층마다 추가하지 않는다.
- 주석은 이유·제약·실패 조건을 설명한다. 코드를 그대로 번역한 주석, 과장된 품질 주장,
  변경 이력 에세이를 피한다. 긴 선택 근거는 `DECISIONS.md`, 튜토리얼은 `LEARNING.md`로 보낸다.
- public 경계에는 입출력·실패 의미를 설명한다. 사소한 함수마다 형식적인 긴 docstring을
  채우지 않는다. 구현과 다른 주석은 함께 수정한다.
- 기존 명명·타입 표기·포맷을 따른다. 표현 방식 통일만을 위해 무관한 파일까지 고치지 않는다.

## 2. 하드코딩을 분류해서 다룬다

| 값의 성격 | 둘 위치와 기준 | 이 프로젝트의 예 |
|---|---|---|
| 환경마다 다른 값 | 기존 Settings/env 또는 Terraform 변수, 시작 시 검증 | 주소·region·DB 연결·모델 선택 |
| 운영 정책 | 이름 있는 설정/정책, 단위·유효 범위·기본값 이유 명시 | 오류율·상관 시간 창·timeout·재시도 횟수 |
| 프로토콜·도메인 상수 | Enum 또는 해당 모듈 상수 | HTTP 메서드·SSE 종료 표식·사건 상태 |
| 테스트·데모 데이터 | 명시된 fixture/example, 실제 결과와 구분 | company-a, bad-v19, 예시 3.7초 |
| 판정 결과 | 실행 증거로 계산. 성공값을 고정하지 않음 | production_healthy, ci_passed |

- `0.2`, `45`, `30` 같은 정책값은 의미를 이름과 단위로 표현한다. 숫자를 전역 상수 모음으로
  옮기는 것만으로 해결됐다고 하지 않는다. 같은 정책은 한 곳에서 정의한다.
- 용도가 다른 timeout을 숫자가 같다는 이유로 묶지 않는다. 모든 리터럴을 환경변수로 만들지 않는다.
- 운영 환경에서 미설정·플레이스홀더 비밀을 정상값으로 쓰지 않는다.
- 고정 성공 응답이 필요한 데모는 합성 결과임을 표시하고 실제 검증 경로에서 격리한다.

## 3. 책임 분리와 재사용

- API 경계는 입력 검증·인증·HTTP 응답 변환, 도메인은 사건 정책·상태 전이, store는 SQL,
  integration/adapter는 외부 통신, frontend는 표시를 맡는다.
- 판정 함수는 가능한 한 입력을 받아 결과를 반환한다. 시각·설정·외부 응답을 내부에서 몰래
  가져와야 테스트되는 구조를 줄인다. 필요한 clock/client/store는 생성 시 전달할 수 있게 한다.
- 같은 이유로 함께 바뀌는 로직을 공통화한다. 조회·오류 변환 같은 반복은 줄일 수 있지만
  모든 공통 코드를 거대한 utils.py에 모으지 않는다.
- 상태 검증·갱신 시각·저장·이벤트 기록은 일관된 경로로 수행한다. 검증을 건너뛰는 편의 API를 만들지 않는다.
- OpenAI/Ollama의 전송·응답 차이는 adapter에 둔다. 공통 인터페이스가 content만 반환해서
  정상 완료·조기 EOF·오류를 잃는다면 인터페이스부터 검토한다.
- 실제 재사용처나 테스트 교체 지점에 근거해 추상화한다. 필요가 확인되지 않은 범용 repository,
  plugin registry, 추상 base class, DI framework는 도입하지 않는다.
- import 시점의 DB·파일·네트워크 부수효과를 줄이고 생성·종료 시점을 명시한다.

## 4. 로직·자료구조·알고리즘

- 제목·번역된 문구를 주요 판정 입력으로 쓰지 않는다. metric 종류·dependency 상태·시각·배포 정보
  같은 구조화된 필드를 우선한다. 텍스트 분류는 보조 휴리스틱으로 표시한다.
- metric 별칭은 입력 경계에서 정규화한다. 함수마다 다른 alias 목록을 반복하지 않는다.
- None과 숫자 0을 구분한다. 단위·범위·유한수 여부와 나눗셈의 분모를 검증한다.
  잘못된 값을 조용히 보정해 성공처럼 보이게 하지 않는다.
- 사건 시각은 timezone-aware UTC, 경과 시간은 monotonic clock을 쓴다. 조회의 시작·끝 구간을
  명시해 미래 데이터·수신 지연이 잘못 연결되지 않게 한다.
- timezone-aware라는 것만으로 UTC 정규화가 된 것은 아니다. 시각을 문자열로 저장·비교한다면
  offset과 정밀도를 통일한다. 시간대가 없는 입력의 거부/해석 정책도 정하고, 상관 구간은
  처리 시각과 사건 발생 시각 중 어느 것을 기준으로 하는지 명시한다.
- 최신 사건 하나가 필요하면 DB에서 상관 조건·정렬·LIMIT으로 제한한다. 전체 목록을 역직렬화한
  뒤 첫 원소만 고르지 않는다. 상관 조건을 생략한 단순 LIMIT 1도 해결책은 아니다.
- 중복 식별자를 DB 제약·트랜잭션과 연결한다. 조회 후 삽입만으로 동시 입력의 멱등성을 보장하지 않는다.
  read-modify-write의 갱신 손실과 중복 외부 작업도 검토한다.
- 조회 범위·보관 기간·화면 페이지 크기를 제한한다. 성능은 데이터 크기·쿼리 수·처리 시간으로
  확인한다. 측정 없이 캐시나 새 DB를 추가하지 않는다.
- 제한된 Terraform 문자열 검사를 범용 HCL 검증이라고 표현하지 않는다. 미지원 형태와
  불충분한 증거의 한계를 밝힌다. 실제로 유효하지 않은 설정을 안전하다고 테스트하지 않는다.

## 5. 비동기·자원 수명·실패 처리

- async 함수 안의 동기 SMTP·SQLite 호출도 blocking I/O다. 실행 위치를 확인하고 필요하면
  thread 경계나 async 구현을 사용한다. async 표기만 붙이거나 무조건 병렬화하지 않는다.
- 반복 호출이 많은 HTTP client는 수명을 명시해 재사용하고 종료 시 닫는다. HTTPX도 연결 풀을
  활용하도록 hot loop 안의 반복 client 생성을 피하라고 안내한다.
  [공식 async 문서](https://www.python-httpx.org/async/).
- 연결·읽기·쓰기·풀 대기와 업무 전체 제한 시간을 구별한다. 스트림의 첫 답변·청크 사이 대기 정책을
  정의한다. timeout=None은 대체 제한·취소 정책이 있을 때만 허용한다. HTTPX read timeout은
  전체 응답 완료 제한이 아니다. [공식 timeout 문서](https://www.python-httpx.org/advanced/timeouts/).
- 재시도는 오류 종류와 멱등성에 근거하며 횟수·총 시간에 상한을 둔다. 이미 내용을 전송한 스트림,
  알림·수정 요청을 무조건 처음부터 재실행하지 않는다.
- 예외는 복구할 수 있는 경계에서 처리한다. except Exception으로 정상값·빈 목록을 반환해
  오류를 숨기지 않는다. 외부 API 실패, 입력 오류, 검증 불충분을 구분한다.
- 의도한 도메인 오류만 HTTP 오류로 변환한다. 내부 구현의 모든 KeyError를 ‘incident 없음’으로 감추지 않는다.
- 취소·예외·정상 종료 모두에서 stream/client/file을 정리한다. 오류 로그에는 비밀·고객 원문 대신
  추적에 필요한 ID와 오류 종류를 남긴다.

## 6. 화면 컴포넌트와 API 호출

- 현재 vanilla HTML/JS에서도 API 호출, SSE 파싱, 상태 표시, incident row 렌더링을 의미 있는
  함수/모듈로 분리할 수 있다. 재사용을 위해 React 전환이 자동으로 필요한 것은 아니다.
- 렌더링은 전달받은 상태를 표시한다. 화면 버튼이 서버의 회복 판정을 대신하지 않는다.
- 외부 title·tenant·문의 내용을 innerHTML에 문자열로 삽입하지 않는다. 일반 텍스트는 textContent,
  HTML이 필요하면 명시적인 허용·정제 정책을 사용한다.
  [MDN innerHTML 보안 안내](https://developer.mozilla.org/en-US/docs/Web/API/Element/innerHTML).
- 사용자 데이터로 inline onclick 코드를 조립하지 않는다. 이벤트 리스너와 데이터를 분리한다.
- 공통 API 함수는 HTTP 오류·빈 응답·JSON 파싱 실패를 구분한다. 호출부는 대기·실패 상태를
  표시하고 중복 클릭·오래된 요청의 뒤늦은 응답을 처리한다.
- SSE 파서는 네트워크 chunk와 이벤트 경계가 같다고 가정하지 않는다. 부분 프레임과 종료 표시 없는
  EOF를 확인한다. 파싱과 화면 갱신은 각각 검증할 수 있게 분리한다.

## 7. 테스트와 리팩터링 완료 기준

- 기존 동작 보존과 정책 변경을 구분한다. 정책이 바뀌면 DESIGN.md와 관측 가능한 결과도 검토한다.
- 보안·데이터·상태 전이 버그에는 실제 실패 입력과 기대 결과의 회귀 테스트를 둔다.
  private 구현이나 메서드 호출 횟수를 베낀 테스트로 동작 검증을 대신하지 않는다.
- 기본 테스트는 결정적인 fixture와 고정 clock을 사용한다. 실제 외부 API·시간 대기·비용이 필요한
  통합 검증은 분리한다. 동작 영향이 없는 문서·표현 변경에 형식적인 테스트를 추가하지 않는다.
- 줄 수·추상화 수·테스트 개수는 품질 목표가 아니다. 가독성, 중복 정책 감소, 실제 버그 방지,
  측정한 비용 개선으로 판단한다.

## 8. API 권한과 외부 작업

- 데이터 형식 검증과 호출자 인증·작업 권한 검사를 구분한다. `tenant`나 incident ID를
  안다는 이유로 조회·수정 권한이 생기지 않는다. 공유 환경에서는 서버가 접근 범위를 검사한다.
- 수정 dispatch, 알림 발송, 회복 승인에는 허용된 호출자·대상·작업 범위를 확인한다.
  webhook/SMTP 주소를 설정했다는 사실은 개별 요청의 실행 승인이 아니다.
- 외부 전송은 필요한 필드만 허용 목록으로 구성한다. incident 전체 직렬화에는 고객 문의
  원문도 들어갈 수 있으므로 수신처·마스킹·보존 정책을 확인한다.
- 초안 생성과 실제 전송, 외부 요청 접수와 작업 완료를 구분한다. 중복 요청·응답 유실의
  처리 기준을 정하고, 외부 작업이 실패했는데 성공 상태만 저장되지 않게 한다.
- 로컬 데모의 접근 제한과 운영 인증을 구분한다. 공개하지 않을 데모에 큰 인증 플랫폼을
  무조건 추가하지 않지만, 실제 배포의 접근 제한을 확인하기 전에는 공개 가능한 API라고 쓰지 않는다.

## 확인된 개선 후보 — 2026-09-20 재현 결과로 갱신

2026-09-19에 읽은 상태를 아래 표에 적용 여부와 함께 남긴다. 각 항목은 `PYTHONPATH=. .venv/bin/python
-m pytest -q incidentops/tests decision_monitor/tests app/tests`로 재현했고, 커밋 메시지에
근거를 남겼다.

| 위치 | 확인한 내용 | 적용한 기준 | 상태 |
|---|---|---|---|
| matching.py | 심각도 기준 0.2, metric 별칭 반복, symptom 문자열 비교 | `error_rate_sev2_ratio` 설정으로 이동, alias 테이블 단일화 | 적용됨 |
| matching.py / incident_store.py | 최신 사건 하나를 위해 미해결 사건 전체 조회 | `IncidentStore.latest_open_incident()`가 상관 시간 창·`ORDER BY`·`LIMIT 1`을 SQL로 처리 | 적용됨 |
| triage.py | SHA 존재만으로 CODE_REGRESSION, 표시 문구로 원인 판단 | SHA 상관은 `confidence="low"`와 상관 관계임을 명시하는 문구로, 구조화된 신호(`dependency`, readiness 실패)는 `medium` 유지 | 적용됨 |
| service.py | 상태·시각·저장 반복, 이전 상태 검증 없이 전이 | `_set_status()`로 반복 제거, `RESOLVED` 상태에서의 모든 전이는 `IncidentAlreadyResolved` | 적용됨 |
| api.py | 반복 KeyError 처리, import 시 tracker/DB 생성 | `_map_domain_errors()` 컨텍스트 매니저, tracker는 lifespan에서 `app.state`로 생성 | 적용됨 |
| app/llm.py | 호출마다 client 생성, timeout 없음, 종료 이유 소실 | client는 선택적 주입(수명은 호출자 결정), 명시적 connect/read/write/pool timeout, `done`/`[DONE]` 없이 끝나면 `UpstreamIncompleteError` | 적용됨. `app/tests/test_llm.py`로 검증, `chat.py`도 새 예외를 처리하도록 수정 |
| integrations/notifications.py | async 함수 내부 동기 SMTP | `asyncio.to_thread`로 이동 | 적용됨 |
| incidentops/static/dashboard.html | 외부 필드 innerHTML 삽입, Verify의 성공 bool 고정 | `createElement`/`textContent`로 교체, inline onclick 제거, Verify 버튼과 로그에 합성 값임을 표시 | 적용됨 |
| decision_monitor/tests/test_engine.py | value 없는 SecureString fixture를 VALID로 기대 | 해당 모양은 `no_value_argument`로 분리해 `UNKNOWN` 처리. `VALID`는 SecureString 리소스가 아예 없을 때만 | 적용됨 |

추가로, 표에는 없었지만 같은 작업 중 발견해 같이 처리한 것: `fix-dispatch`·`notify`·`verify`에
`INCIDENTOPS_API_TOKEN` 기반 호출자 인증(§8), webhook payload를 `external.py`의 허용 목록으로 축소
(고객 문의 원문 등 `fact.details` 제외), `app/routers/chat.py`가 `UpstreamIncompleteError`를
`httpx` 오류와 같은 방식으로 처리하도록 연결.

의도적으로 남겨둔 것:

- `triage.py`의 `_from_webhook()`은 여전히 incident 전체를 직렬화해 외부 triage webhook으로
  보낸다. `dispatch_fix`/`send_notification`과 같은 종류의 노출이지만 이 표에 명시되지 않아
  범위를 넘겨 고치지 않았다.
- `IncidentStore`의 SQLite 호출은 `async def` 안에서 동기로 실행된다(§5의 blocking I/O 원칙).
  표에는 `integrations/notifications.py`의 SMTP만 명시돼 있었고, 이건 우선순위 표의 마지막
  항목("측정에 따른 조회 최적화")에 가까운 성격이라 손대지 않았다.
- `/api/v1/incidents` 조회는 여전히 페이지 크기 제한이 없다. 우선순위 표가 조회 최적화를
  가장 뒤로 두었고 아직 측정하지 않았다.

공개 노출 전에는 대시보드의 외부 문자열 렌더링과 입력 인증부터 별도로 점검한다는 문장은
이제 완료된 항목을 가리킨다. 다음에 볼 것은 위 "의도적으로 남겨둔 것"이다.
학습 순서는 [LEARNING.md](LEARNING.md), 동작 규약은 [DESIGN.md](DESIGN.md)를 따른다.

### 추가 확인 — 2026-09-20, 2026-09-20 수정 반영

아래 세 항목은 최초 작성 시 프로젝트 `.venv`의 Python으로 기존 `IncidentStore`·`IncidentMatcher`를
호출해 재현했다("관찰 결과" 열). 이후 같은 날 수정했고, 회귀 테스트로 고정했다("수정 후" 열).
각 회귀 테스트는 `incidentops/tests/test_incidentops.py`에 있다.

| 항목 | 입력·절차 | 관찰 결과 (수정 전) | 수정 후 |
|---|---|---|---|
| 시간 구간 | 현재 UTC보다 1시간 전인 시각을 `+09:00`으로 표현한 신호와 하루 뒤 신호를 저장하고 `recent_telemetry(tenant, 30)` 호출 | 두 신호 모두 반환됨. offset 혼용 문자열 비교와 조회 상한 부재 | naive datetime 거부, 모든 시각 UTC 정규화, 창을 양쪽으로 제한(`test_future_dated_signal_falls_out_of_the_correlation_window`) |
| 재전송 | 같은 tenant·message_id의 `CustomerEmail`을 `add_customer_email()`에 두 번 전달 | 같은 incident에 고객 fact 2개 | `(tenant, message_id)` unique index + 재전송은 기존 incident를 그대로 반환(`test_resent_customer_email_does_not_duplicate_the_fact`) |
| 장애 연결 | 같은 tenant에서 `/login`의 5xx 신호 후 하루 뒤 `/chat/stream` 지연 신호 전달 | 같은 incident ID로 합쳐짐 | `latest_open_incident()`가 상관 시간 창을 SQL에서 강제(`test_unrelated_failure_a_day_later_does_not_merge_into_the_old_incident`) |

endpoint/symptom까지 포함한 전체 상관 조건(DESIGN.md 3번)은 아직 시간 창만 적용했다. 같은 시간
창 안에서 서로 다른 endpoint/symptom의 신호가 합쳐지는 경우는 남아 있다.

별도로 정적 확인했던 사항(수정됨): `incidentops/api.py`에는 자체 인증·작업 권한 검사가 없었다.
`fix-dispatch`·`notify`·`verify`는 이제 `INCIDENTOPS_API_TOKEN`이 설정된 경우 `Authorization:
Bearer` 검사를 거친다. 미설정 시 이전과 동일하게 열려 있으며, 이것이 미설정 배포를 노출해도
안전하다는 뜻은 아니다. integrations의 webhook payload는 incident 전체를 포함했으나 이제
`external.py`의 허용 목록만 나간다(고객 문의 원문 등 `fact.details`는 제외). 배포 앞단의
접근 제한 유무와 실제 외부 노출 여부는 이번에도 검증하지 않았다.

우선순위는 공개 공유 전 접근 통제·안전한 화면 출력·전송 데이터 범위, 핵심 기능 정확성을 위한
시간/상관/중복 처리·증거 기반 회복 판정, 이후 측정에 따른 조회 최적화 순이다.
이 기록은 별도 승인 없이 코드를 수정하라는 지시가 아니다.
