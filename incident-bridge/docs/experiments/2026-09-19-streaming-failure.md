# 실험: 모니터링이 보지 못하는 스트리밍 실패

실행일: 2026-09-19. 로컬 환경. AWS 리소스는 쓰지 않았다.

## 묻는 것

`DESIGN.md` 1번이 성공을 "사용자가 content를 받고 정상 종료까지 관찰한 경우"로 정의한다.
현재 수집하는 신호는 `5xx_rate`, `p95_latency`, `readiness` 셋뿐이다.

이 셋이 모두 정상인데 사용자는 답을 못 받는 상태가 실제로 가능한가. 가능하다면
`incidentops`는 그걸 탐지하는가.

## 구성

| 요소 | 실행 방식 |
|---|---|
| Postgres 16 / Redis 7 | docker compose, 호스트에 55432 / 56379로 노출 |
| 채팅 앱 | uvicorn, `127.0.0.1:8100`, Python 3.11.15 |
| LLM upstream | 통제 가능한 대역 서버. `MODE=healthy`와 `MODE=reject` 전환 |
| Incident Bridge | uvicorn, `127.0.0.1:8090`, 빈 SQLite로 시작 |

실제 모델을 쓰지 않은 이유는 장애를 원할 때 일으키기 위해서다. `MODE=reject`는 Ollama의
`/api/chat`이 404를 반환하는 상황을 흉내낸다. 모델을 안 받아둔 상태, 잘못된 키, rate limit이
모두 앱 입장에서는 같은 모양이 된다.

## A. 기준선 — upstream 정상

```
/ready        200  {"ready":true,"checks":{"postgres":"ok","redis":"ok"}}
/chat/stream  200

data: {"stage": "history_loaded", "messages": 1}
data: {"content": "안녕"}
data: {"content": "하세요"}
data: {"content": ". 무엇을"}
data: {"content": " 도와드릴까요?"}
data: [DONE]
```

`DESIGN.md`의 성공 조건 셋을 모두 만족한다. content를 받았고, upstream이 정상 종료했고,
클라이언트가 종료 표시를 관찰했다.

## B. upstream 실패

upstream만 `MODE=reject`로 바꿨다. 앱도 DB도 그대로다.

```
/health       200  {"status":"ok"}
/ready        200  {"ready":true,"checks":{"postgres":"ok","redis":"ok"}}
/chat/stream  200  응답시간 0.013s

data: {"stage": "history_loaded", "messages": 3}
data: {"error": "The model is unavailable right now."}
```

사용자가 받은 답변은 0자다.

관측한 응답을 기존 telemetry 입력 형식에 대입하면 다음과 같다. 아래 지연은 한 요청의
표본이며 p95가 아니다. 5xx 비율도 트래픽 구간을 집계한 결과가 아닌 실험 입력이다.

| 신호 | 값 | 이 신호만 보면 |
|---|---|---|
| `readiness` | 1 | 정상 |
| `5xx_rate` | 0 | 정상 |
| `p95_latency`에 넣은 단일 표본 | 0.013s | 임계치 미만 |
| 사용자가 받은 답변 | 0자 | 실패 |

지연 기반 탐지로도 잡히지 않는다. 실패가 **빠르기 때문에** 더 건강해 보인다.

원인은 `app/routers/chat.py`에 주석으로 이미 적혀 있다.

```python
except httpx.HTTPStatusError as exc:
    # The upstream model rejected us (bad key, rate limit, model not
    # pulled). Status is already 200 by now, so the only way to tell
    # the client is an in-band error event.
```

SSE는 헤더를 먼저 보낸다. 첫 이벤트를 내보낸 시점에 상태 코드는 이미 200으로 확정된다.
그래서 이후에 무슨 일이 나든 HTTP 계층에서는 성공이다.

## C. Incident Bridge에 넣어보면

관측 결과를 바탕으로 만든 값 셋을 `/api/v1/signals/telemetry`에 수동으로 넣었다.
실제 `http_probe`는 `/ready`의 readiness와 단일 응답 시간만 보내며 5xx 비율을 수집하지 않는다.
아래 0.013s는 `/chat/stream` 표본이므로 실제 probe의 `/ready` 측정값과도 구분한다.

```
readiness=1.0  5xx_rate=0.0  p95_latency=0.013
```

결과:

```
GET /api/v1/incidents
incident 수: 0
```

`matching.py`의 `_alert_reason()`이 임계치를 넘는 것이 없으므로 `None`을 반환하고, 신호는
telemetry 테이블에만 쌓인다. 모니터링 경로로는 아무 일도 일어나지 않는다.

## D. 고객이 신고하면

```
POST /api/v1/customer-email
{"tenant":"demo","customer":"Probe User","subject":"답변이 안 옵니다", ...}
```

```
incident   : INC-5924F25E
trigger    : customer_email
symptom    : request failures
alert_gap  : None
facts      :
   [customer_email] customer_report: Probe User: 답변이 안 옵니다

지표 근거 fact 수: 0
```

incident는 만들어진다. 다만 고객 신고 하나뿐이고 뒷받침할 지표 증거가 없다.

`alert_gap`이 `None`인 것도 짚어둘 만하다. `_find_subthreshold_regression()`은 symptom이
`performance degradation`일 때만 동작하는데, 이 신고는 키워드상 `request failures`로 분류됐다.
지연이 아니라 실패라서 맞는 분류이지만, 그 경로에는 baseline 비교가 아예 없다.

## 결론

네 가지가 확인됐다.

1. HTTP 상태와 readiness가 정상인 채로 사용자가 답변을 받지 못하는 상태가 실재한다
2. 빠른 실패는 지연 기반 탐지를 통과한다
3. 정상 범위로 수동 입력한 telemetry에서는 incident가 생성되지 않았다
4. 이 실험에서는 고객 신고로만 incident가 만들어졌으며 지표 증거가 붙지 않았다

실제 collector를 연결한 자동 탐지·복구·회복 검증까지 완주한 실험은 아니다.

이건 임계치를 낮춰서 풀리는 문제가 아니다. 재고 있는 값이 사용자 경험과 무관한 지점에서
측정되고 있다.

## 다음에 할 것

- 스트림 제너레이터 안에서 결과 이벤트를 발행한다. 첫 content 시각, 종료 이유, 받은 바이트 수
- `http_probe`가 `/ready`가 아니라 인증된 `/chat/stream`을 통과하게 한다
- `DESIGN.md` 2번 규약을 그 이벤트에 적용한다. 특히 `sample_count`와 실제/합성 구분
- 단일 표본을 `p95_latency`로 보내는 것을 멈춘다

## 부수적으로 발견한 것

이 실험을 돌리려고 처음으로 앱을 실제 기동해봤고, 깨끗한 환경에서 세 군데가 막혔다.
전부 `requirements.txt` 문제이고 같은 커밋에서 고쳤다.

| 증상 | 원인 |
|---|---|
| `asyncpg` 휠 빌드 실패 | `0.29.0`이 Python 3.13+ 미지원. 3.14에서 막힘 |
| 기동 중 `the greenlet library is required` | SQLAlchemy asyncio가 greenlet을 요구하는데 플랫폼에 따라 안 딸려옴 |
| 회원가입 전부 HTTP 500 | `passlib 1.7.4`가 `bcrypt.__about__`을 읽는데 bcrypt 4.1에서 제거됨. 핀이 없어 5.0.0이 설치됨 |

세 번째가 특히 중요하다. 깨끗한 설치에서 **인증이 전혀 동작하지 않았다.** 테스트는
`incidentops`와 `decision_monitor`만 덮고 있어서 `app/`의 이 상태를 아무도 몰랐다.
