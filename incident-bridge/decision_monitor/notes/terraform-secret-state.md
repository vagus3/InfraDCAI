# Terraform secret state mismatch

`ADR-010`에서는 Terraform이 SSM parameter의 경로만 관리하고 실제 secret 값은 알지 않도록 하기로 했습니다.

그런데 현재 PostgreSQL password는 다음 구조입니다.

```hcl
resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "aws_ssm_parameter" "postgres_password" {
  name  = "${local.ssm_prefix}/postgres_password"
  type  = "SecureString"
  value = random_password.postgres.result
}
```

`SecureString`은 Parameter Store에서 값을 보호하지만, Terraform이 만든 값 자체는 state를 거칩니다.

따라서 이 경우 Terraform의 desired/actual state는 서로 일치해도 ADR-010은 만족하지 않습니다.

수정할 때는 `random_password.postgres`를 Terraform에서 제거하고, SSM parameter 값은 bootstrap 단계에서 넣는 방식으로 맞출 예정입니다.

확인 항목:

1. `python -m decision_monitor.cli repo --root .`에서 ADR-010이 `VALID`
2. Terraform에 DB password 생성 resource가 없음
3. 배포 과정에서는 SSM에서 password를 계속 읽을 수 있음
