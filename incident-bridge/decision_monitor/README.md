# Decision Monitor

`DECISIONS.md`에 적어둔 설계 결정을 실제 코드와 AWS 상태에서 다시 확인하기 위한 작은 도구입니다.

현재는 두 종류를 구분합니다.

- `VIOLATED`: 결정은 그대로 유효하지만 구현/운영 상태가 그 결정을 어김
- `REVISIT_REQUIRED`: 결정을 어긴 것은 아니지만, 당시의 전제가 더 이상 맞지 않을 가능성이 있음

예를 들어 `SSM을 사용하고 public SSH를 열지 않는다`는 결정이 있는데 Security Group에 `22/tcp 0.0.0.0/0`이 추가되면 `VIOLATED`입니다.

반대로 `single EC2로 충분하다`는 결정에서 처음 정한 부하 기준을 계속 넘는다면 잘못된 설정이라고 단정하지 않고 `REVISIT_REQUIRED`로 표시합니다.

## 현재 확인하는 항목

| Decision | Check | Result |
|---|---|---|
| ADR-001: single EC2 + Compose | host load | `REVISIT_REQUIRED` |
| ADR-008: SSM instead of SSH | Security Group ingress | `VIOLATED` |
| ADR-010: secret value outside Terraform state | Terraform source | `VIOLATED` |

## 로컬 실행

```bash
python -m decision_monitor.cli repo --root .
python -m decision_monitor.cli snapshot decision_monitor/examples/compliant.json --root .
python -m decision_monitor.cli snapshot decision_monitor/examples/violated-and-stale.json --root .
```

현재 저장소를 검사하면 ADR-010을 확인할 수 있습니다. PostgreSQL password를 `random_password`에서 만들고 `aws_ssm_parameter`의 값으로 넘기고 있기 때문에 실제 secret 값이 Terraform state를 거치게 됩니다.

이 사례는 [`notes/terraform-secret-state.md`](notes/terraform-secret-state.md)에 정리했습니다.

## AWS 상태 확인

```bash
python -m pip install -r decision_monitor/requirements.txt

python -m decision_monitor.cli live \
  --region ap-northeast-2 \
  --project mini-chatgpt \
  --root .
```

현재 live collector는 다음을 확인합니다.

1. EC2에 연결된 Security Group ingress
2. SSM으로 읽은 host 1-minute load average

load 값은 빠른 실험용입니다. 장기적으로는 CloudWatch CPUUtilization 같은 운영 지표로 교체할 수 있습니다.

## 테스트 시나리오

1. `DECISIONS.md`에서 ADR-008 확인
2. AWS에서 public SSH가 없는 상태를 검사
3. Security Group에 `22/tcp 0.0.0.0/0` 추가
4. 다시 검사해서 `VIOLATED` 확인
5. 부하를 올리고 ADR-001이 `REVISIT_REQUIRED`로 바뀌는지 확인

핵심은 `VIOLATED`와 `REVISIT_REQUIRED`를 같은 문제로 취급하지 않는 것입니다.

구현 범위는 [`design-notes.md`](design-notes.md)에 정리했습니다.
