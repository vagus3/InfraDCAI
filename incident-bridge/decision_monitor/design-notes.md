# Decision Monitor design notes

## 상태

| State | Meaning |
|---|---|
| `VALID` | 현재 확인한 값이 결정을 위반하지 않음 |
| `VIOLATED` | 코드/인프라가 받아들인 결정을 직접 위반함 |
| `REVISIT_REQUIRED` | 결정을 내릴 당시의 전제가 다시 검토할 조건에 도달함 |
| `UNKNOWN` | 필요한 값을 확인하지 못함 |

## ADR-001 — Single EC2 + Docker Compose

- check: SSM에서 읽은 normalized host load
- demo threshold: `>= 70%`
- threshold 도달 시: `REVISIT_REQUIRED`
- 자동으로 ECS/EKS 같은 대안을 선택하지 않음

## ADR-008 — SSM instead of SSH

- check: 실제 EC2 Security Group ingress
- rule: public TCP/22 금지
- 위반 시: `VIOLATED`

## ADR-010 — Secrets outside Terraform state

- check: `infra/` Terraform source
- rule: 실제 secret material을 `aws_ssm_parameter` value에 Terraform expression으로 전달하지 않음
- 위반 시: `VIOLATED`

## 아직 하지 않는 것

- 자동 인프라 변경
- 자연어 ADR을 바로 정책으로 실행
- 범용 Terraform parser 구현
- multi-cloud 검사
- architecture 대안 자동 선택

현재 목표는 세 가지 결정을 실제 저장소와 AWS 상태에서 반복해서 확인할 수 있게 만드는 것입니다.
