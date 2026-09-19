# Terraform secret state mismatch

이 문서는 ADR-010을 고치는 과정의 기록이다. 결론이 두 번 바뀌었다.

## 1차: 체커가 위반을 찾았다

`ADR-010`에서는 Terraform이 SSM parameter의 경로만 관리하고 실제 secret 값은 알지 않도록 하기로 했다.
그런데 PostgreSQL password는 다음 구조였다.

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

Terraform이 값을 생성하므로 그 값이 state에 남는다. `SecureString`은 Parameter Store에서 값을
보호하지만 Terraform이 만든 값 자체는 state를 거친다.

바로 위에 붙어 있던 주석이 이미 정답을 적고 있었다는 점이 이 건의 성격을 보여준다.

```
# Terraform creates the parameters but never holds the real values
```

의도는 문서화돼 있었고 코드가 드리프트했다. 사람은 주석을 다시 읽지 않고, 체커는 읽는다.

## 2차: 고쳤더니 VALID가 됐고, 그 VALID가 틀렸다

`random_password`를 제거하고 나머지 둘과 같은 형태로 맞췄다. 플레이스홀더 값에
`ignore_changes = [value]`를 걸고 진짜 값은 밖에서 넣는 방식이다. 체커는 `VALID`로 바뀌었다.

그런데 이 패턴이 애초에 성립하지 않는다.

AWS provider는 `aws_ssm_parameter`를 refresh할 때 `GetParameter`를 `WithDecryption: true`로
호출하고 복호화된 값을 state에 기록한다. `ignore_changes`는 plan의 diff를 억제할 뿐 read를
막지 않는다. 진짜 값을 넣은 뒤 `terraform plan`을 한 번만 돌려도 그 값이 state로 들어온다.

그러므로 `jwt_secret_key`와 `openai_api_key`도 같은 문제를 갖고 있었다. 셋 다였다.

체커가 `VALID`를 낸 이유는 규칙이 틀린 질문을 하고 있었기 때문이다.

| | 검사하던 것 | 검사했어야 하는 것 |
|---|---|---|
| 질문 | 비밀스러운 표현식이 `value`로 흘러드는가 | Terraform이 이 SecureString 리소스를 관리하는가 |
| 근거 | ADR에 적힌 해결책 | provider의 실제 동작 |

ADR의 틀린 전제를 그대로 규칙으로 옮긴 결과, 체커는 틀린 것을 맞다고 확인해주고 있었다.

## 지금 상태

규칙을 `terraform_securestring_ownership`으로 바꿨다. 이제 Terraform이 값을 갖는 SecureString
파라미터를 전부 보고한다. `value` 인자가 아예 없는 경우(write-only / ephemeral 인자의 형태)는
위반이 아니다.

```
Terraform manages 3 SecureString parameter(s); 0 of them generate the secret themselves.
```

상태는 `VIOLATED`다. `decisions.json`에 승인 기록을 남겨서 CI는 막지 않지만 내용은 크게 출력된다.
승인에는 날짜, 사유, 담당, 재검토 기한이 들어간다. 승인을 지우면 CLI가 종료 코드 1을 반환한다.

## 남은 작업

소유권 분리가 진짜 해결이다.

- Terraform: 네트워크, 인스턴스, IAM, 비밀 경로 규약까지만 관리한다
- 별도 초기화 절차: SSM 파라미터의 생성과 값을 소유한다. DB 값은 최초 1회 생성하고 재실행 시 재사용한다
- 런타임: 필요한 이름의 파라미터만 읽는다. 배포 전에 미설정·플레이스홀더·조회 실패를 검사한다

주의할 점 두 가지.

- 이미 Terraform이 관리하는 실리소스가 있다면 resource 블록을 그냥 지우면 파라미터 파괴 계획이
  생긴다. state와 리소스 존재를 확인하고 비파괴 소유권 이전을 계획해야 한다.
- 과거 state에 이미 비밀이 들어갔다면 경로를 고치는 것만으로 이력에서 사라지지 않는다.

## 검증 방법

실제 비밀 대신 비밀이 아닌 테스트 표식을 넣고, 계획과 state에서 그 표식이 어떻게 움직이는지
격리된 환경에서 관찰한다. 제출 자료에는 값이나 state 원문을 포함하지 않는다.

이 관찰은 아직 실행하지 않았다.
