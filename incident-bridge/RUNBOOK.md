# 운영 절차서

> 이 문서는 아직 **검증되지 않았다**. 각 절차를 한 번씩 직접 실행해보고, 실제 출력과 다른
> 부분을 고쳐야 한다. 검증하지 않은 런북은 장애 상황에서 오히려 시간을 잡아먹는다.
> 확인한 항목에는 날짜를 적어둘 것.

| 절차 | 검증일 |
|---|---|
| 정상 배포 | |
| 수동 롤백 | |
| 인스턴스 접속 | |
| 시크릿 교체 | |
| 전체 재구축 | |

---

## 배포

### 정상 경로

`main`에 푸시하면 자동으로 진행된다.

```
push → GitHub Actions → 이미지 빌드 → ECR 푸시(태그: commit sha)
     → SSM send-command → 인스턴스에서 /opt/app/deploy.sh 실행
     → docker compose pull && up -d
     → /ready 폴링 (최대 90초)
     → 성공: .last_good_image 갱신 / 실패: 이전 이미지로 자동 롤백
     → GitHub Actions가 외부에서 https://SITE/health 확인
```

### 배포 상태 확인

```bash
# 인스턴스 안의 배포 로그 (자동 롤백 여부가 여기 남는다)
aws ssm start-session --target <INSTANCE_ID>
sudo tail -50 /var/log/app-deploy.log
```

### 수동 롤백

자동 롤백은 "새 이미지가 뜨지 않은 경우"만 잡는다. 컨테이너는 정상이지만 동작이 잘못된
경우 — 예를 들어 응답은 200인데 내용이 틀린 경우 — 는 사람이 판단해야 한다.

```bash
aws ssm start-session --target <INSTANCE_ID>
sudo -i
cd /opt/app

# ECR에서 되돌릴 커밋 sha 확인
aws ecr describe-images --repository-name mini-chatgpt \
  --query 'sort_by(imageDetails,&imagePushedAt)[*].[imageTags[0],imagePushedAt]' \
  --output table

./deploy.sh <되돌릴-commit-sha>
```

---

## 장애 대응

먼저 어디까지 살아있는지 확인한다. 위에서부터 순서대로.

```bash
curl -sS https://<SITE>/health   # 프로세스가 떠 있는가
curl -sS https://<SITE>/ready    # 의존성에 닿는가 (어느 것이 죽었는지 알려준다)
```

### 증상: 접속이 아예 안 됨 (연결 거부 / 타임아웃)

1. 인스턴스가 살아있는지: `aws ec2 describe-instance-status --instance-ids <ID>`
2. 접속해서 컨테이너 상태 확인:
   ```bash
   aws ssm start-session --target <INSTANCE_ID>
   sudo docker compose -f /opt/app/docker-compose.yml ps
   ```
3. Caddy가 죽었으면 로그: `sudo docker compose -f /opt/app/docker-compose.yml logs caddy`
   - 인증서 발급 실패가 가장 흔하다. Let's Encrypt는 실패 횟수 제한이 있으므로
     같은 도메인으로 반복 재시도하면 몇 시간 막힌다.

### 증상: 502 또는 503

Caddy는 살아있고 app이 죽은 상태.

```bash
sudo docker compose -f /opt/app/docker-compose.yml logs --tail 100 app
curl -s http://127.0.0.1:8000/ready | python3 -m json.tool
```

`/ready` 응답이 어느 의존성이 문제인지 바로 알려준다.

- `postgres: unreachable` → Postgres 컨테이너 로그 확인. 디스크가 찼는지 `df -h`도 볼 것.
- `redis: unreachable` → Redis 컨테이너 확인. 메모리 상한에 걸린 경우는 LRU로 처리되므로
  보통 여기가 원인은 아니다.

### 증상: 응답이 스트리밍되지 않고 한 번에 나옴

프록시 버퍼링 문제다.

- 로컬: `nginx/nginx.conf`의 `proxy_buffering off` 확인
- 배포: `/opt/app/Caddyfile`의 `flush_interval -1` 확인
- 앱은 `X-Accel-Buffering: no` 헤더를 이미 보내고 있다

`curl -N` 없이 테스트하면 curl 자체가 버퍼링하므로 같은 증상으로 보인다. 먼저 이것부터 확인.

### 증상: 채팅이 "The model is unavailable right now."를 반환

앱은 정상이고 상위 모델 API가 거절한 것이다.

```bash
sudo docker compose -f /opt/app/docker-compose.yml logs app | grep llm_upstream_error
```

로그의 `status_code`로 구분한다.

- `401` → API 키가 잘못됨. 아래 "시크릿 교체" 참고
- `429` → 레이트 리밋 또는 크레딧 소진. OpenAI 대시보드 확인
- `404` → `OPENAI_MODEL` 이름이 틀렸거나 해당 계정에서 못 쓰는 모델

### 증상: 특정 사용자만 실패한다고 함

응답 헤더의 `X-Request-ID`를 받아서 로그에서 찾는다.

```bash
sudo docker compose -f /opt/app/docker-compose.yml logs app | grep <request-id>
```

로그가 JSON이므로 `jq`로 필터링해도 된다.

### 증상: 디스크가 찼다

```bash
df -h
sudo docker system df
sudo docker system prune -a --volumes   # 주의: 볼륨까지 지우면 DB 데이터가 사라진다
```

로그 로테이션과 ECR 라이프사이클을 걸어뒀지만, Caddy 인증서 갱신 로그나 Postgres WAL이
쌓일 수 있다. 볼륨을 지울 때는 `--volumes`를 빼는 쪽을 기본으로 할 것.

---

## 유지보수

### 시크릿 교체

```bash
aws ssm put-parameter --overwrite --type SecureString \
  --name /mini-chatgpt/openai_api_key --value "sk-new-key"

# 값은 컨테이너 시작 시점에 주입되므로 재배포해야 반영된다
aws ssm start-session --target <INSTANCE_ID>
sudo /opt/app/deploy.sh $(cat /opt/app/.last_good_image)
```

JWT 시크릿을 바꾸면 **발급된 모든 토큰이 무효가 된다**. 전원 로그아웃되는 것이 의도한
동작일 때만 바꿀 것.

### 인스턴스 접속

SSH 포트가 없다.

```bash
aws ssm start-session --region ap-northeast-2 --target <INSTANCE_ID>
```

안 되면: SSM 에이전트가 떠 있는지, 인스턴스 프로파일에 `AmazonSSMManagedInstanceCore`가
붙어 있는지, 아웃바운드 443이 열려 있는지 확인.

### 전체 재구축

인스턴스를 버리고 다시 만드는 것이 고치는 것보다 빠를 때가 있다. 그게 인프라를 코드로
관리하는 이유다.

```bash
cd infra
terraform apply -replace=aws_instance.app
# EIP는 유지되므로 도메인은 그대로다
# 새 인스턴스에는 이미지가 없으므로 Actions에서 재배포를 한 번 돌린다
```

Postgres 데이터는 사라진다. 지금은 계정뿐이라 감수하는 부분이고, 그 판단 근거는
DECISIONS.md 2번에 있다.

### 전체 삭제

```bash
cd infra
terraform destroy
```

`terraform destroy`로도 안 지워지는 것: ECR에 남은 이미지(저장소 삭제가 막힐 수 있다),
CloudWatch 로그 그룹. 요금이 계속 나가는지 며칠 뒤 청구서에서 확인할 것.
