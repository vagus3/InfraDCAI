# Incident Bridge

고객 문의와 서비스 지표를 연결해 기존 모니터링의 사각지대를 설명하는 클라우드 운영 실험 프로젝트입니다.

- [프로젝트 소개·실행·데모](incident-bridge/README.md)
- [HTTP 200 스트리밍 실패 실험과 한계](incident-bridge/docs/experiments/2026-09-19-streaming-failure.md)
- [설계 규약과 미구현 범위](incident-bridge/DESIGN.md)
- [인프라 선택 근거](incident-bridge/DECISIONS.md)
- [제출 전 체크리스트](incident-bridge/docs/submission-checklist.md)

실제 프로젝트는 `incident-bridge/`에 있습니다. 기본 분석은 규칙 기반이고 AI 분석은 선택적
webhook 연결 지점입니다. 화면의 회복 판정은 합성 시연이며 실제 자동 복구를 입증하지 않습니다.
