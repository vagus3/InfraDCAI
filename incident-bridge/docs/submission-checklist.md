# 제출 직전 체크리스트 — 2026-09-22

사용자가 전달한 공고의 마감은 **2026-09-22 23:59**다. 시간대와 파일 형식·크기 등은 실제
신청 폼에서 최종 확인한다. 아래는 포트폴리오 준비용이며 공식 제출 형식을 추정하지 않는다.

## 오늘 남은 일

1. **최신 작업을 심사자가 볼 수 있게 올리기.** 확인 시점의 원격 `main`은 `f47cbd7`이고
   원격 `feature/infra`는 없었다. 현재 수정은 로컬 `feature/infra`에 있다. 변경 내역을 확인해
   커밋·push한 후 그 브랜치의 프로젝트 README 링크를 제출하거나, 배포 영향을 검토한 뒤
   기본 브랜치에 반영한다. main push는 workflow를 실행할 수 있으므로 무심코 병합하지 않는다.
2. **외부에서 링크 열기.** 로그인하지 않은 창 또는 심사자가 가진 권한으로 README·코드·
   실험 기록이 열리는지 확인한다. 로컬 파일 경로는 제출 링크가 아니다.
3. **폼이 요구하는 설명·자료 채우기.** 프로젝트 문제, 본인 역할, 구현한 범위, 실험 결과,
   미완성 범위를 분리한다. 영상이 요구되면 아래 흐름으로 짧게 녹화한다. 요구하지 않는
   PDF·영상·새 배포를 마감 직전에 필수 작업으로 늘리지 않는다.
4. **제출 완료 확인.** 저장만 했는지 최종 제출했는지 구별하고 접수 확인을 보관한다.

## 설명의 중심

“HTTP 200·readiness 정상만으로는 사용자 답변 성공을 알 수 없다는 실패를 재현하고,
고객 문의와 서비스 지표를 연결하는 운영 프로토타입을 만들었다. 아키텍처 결정과 실제
인프라의 불일치도 검사하며, 자동 회복 판정에 필요한 증거 규약을 설계했다.”

AI가 감시 대상 앱에서 사용되는 것과 운영 분석에서 사용되는 것을 구분한다. 기본 triage는
규칙 기반이다. webhook 인터페이스가 있다는 사실만으로 AI 운영 분석의 효과를 입증한 것은 아니다.
본인 역할은 실제 수행하고 설명할 수 있는 내용으로 작성한다. AI 도구의 도움도 숨기지 않는다.

## 시연 흐름

- 로컬 합성 데이터만 사용한다. webhook/SMTP 외부 전송 설정은 비운다.
- 토큰 연결 후 A 데모 → Triage → Fix task → Verify (demo). Verify의 고정 입력임을 설명한다.
- B 데모에서 5초 임계치 미만이지만 baseline보다 느려진 사례와 근거 부족 `UNKNOWN`을 보여준다.
- 스트리밍 실험 기록에서 실제 장애 재현과 수동 telemetry 입력의 차이를 설명한다.
- ADR-010은 `VIOLATED`이며 기존 위험 승인 때문에 exit 0이라는 점을 설명한다.

토큰·`.env`·고객 원문·AWS 계정 식별정보는 캡처와 영상에 넣지 않는다.

## 이번 확인 결과

로컬 Python 3.11.15, 임시 DB·합성 입력·mock 외부 통신 기준:

- `PYTHONPATH=. .venv/bin/python -m pytest -q incidentops/tests decision_monitor/tests app/tests`: 56 passed.
  Starlette/AnyIO의 deprecated alias 경고 1개. 앱 가입·DB·Redis 실연동 테스트는 아니다.
- `PYTHONPATH=. .venv/bin/python -m decision_monitor.cli repo --root .`: exit 0, 승인된 ADR-010 위반 유지.
- `.venv/bin/python -m pip check`: 의존성 충돌 없음.
- `INCIDENTOPS_TRIAGE_WEBHOOK_URL='' PYTHONPATH=. .venv/bin/python -m incidentops.demo all`: 두 합성 시나리오 완료.
- 브라우저: 토큰 연결, A의 OPEN → TRIAGED → READY_FOR_FIX → RESOLVED, B의 alert gap 표시 확인.
  관찰한 인터랙션 중 JS error/unhandled rejection 없음. 인터넷 공개 배포 검증은 아니다.
- CI 검사 대상에 `app/tests`를 추가했지만, 원격 CI 결과는 아직 확인하지 않았다.

## 오늘 마감 전에 새로 벌이지 않을 일

Kubernetes 전환, 멀티클라우드, 자동 코드 수정 에이전트, DB 교체, 대규모 추상화는 보류한다.
전체 증거 기반 회복 판정, endpoint/symptom 상관, tenant별 권한 분리, 외부 자유 텍스트 보호는
남은 과제로 명시한다. 지금은 실제로 작동하는 범위를 과장 없이 제출하는 것이 우선이다.
