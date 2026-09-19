# Test scenarios

## 1. Monitor-detected incident

### 준비

서비스가 정상 상태이고 5xx rate가 낮은 상태에서 시작합니다.

### 문제 발생

의도적으로 문제가 있는 배포를 하거나 테스트 입력으로 5xx rate를 올립니다.

```text
5xx_rate = 0.31
```

### 기대 결과

- incident 생성
- deployment SHA가 triage에 사용됨
- 이후 고객 문의가 들어오면 같은 incident에 연결
- 고객 문의가 도착하기 전까지의 시간을 기록
- rollback/fix 후 live check 통과 시 RESOLVED

## 2. Customer-reported latency regression

### 준비

```text
baseline p95 = 1.1s
alert = 5.0s
```

### 문제 발생

```text
current p95 = 3.7s
```

5초를 넘지 않으므로 latency alert는 발생하지 않습니다.

고객 문의:

```text
응답 속도가 평소보다 많이 느립니다.
```

### 기대 결과

- 고객 문의로 incident 생성
- 최근 telemetry에서 1.1s -> 3.7s 변화 확인
- alert가 발생하지 않았다는 사실을 `alert_gap`으로 기록
- 원인이 부족하면 UNKNOWN으로 남기고 자동 수정하지 않음

## 3. Failed post-deploy check

### 조건

```text
CI = pass
Deploy = success
Production health = fail
```

### 기대 결과

```text
ESCALATED
```

코드 수정과 배포가 성공했더라도 서비스가 회복되지 않았다면 완료 처리하지 않습니다.
