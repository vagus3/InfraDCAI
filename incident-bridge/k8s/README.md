# k8s/

로컬 `kind` 클러스터용 매니페스트. **운영 배포 경로가 아니다** — 운영은 `infra/`의
EC2에서 돌아간다. 여기는 K8s가 실제로 무엇을 해주는지 손으로 확인해보기 위한 것이다.

학습 순서와 실습 내용은 **[../K8S-PLAN.md](../K8S-PLAN.md)** 에 있다. 이 파일은 명령어 참조용.

## 빠른 실행

```bash
kind create cluster --config k8s/kind-cluster.yaml --name mini-chatgpt

kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=180s

docker build -t mini-chatgpt:local .
kind load docker-image mini-chatgpt:local --name mini-chatgpt

kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-config.yaml
kubectl apply -f k8s/02-postgres.yaml
kubectl apply -f k8s/03-redis.yaml
kubectl apply -f k8s/07-ollama.yaml     # 메모리 부족하면 생략 (아래 참고)
kubectl apply -f k8s/04-app.yaml
kubectl apply -f k8s/05-ingress.yaml

kubectl -n mini-chatgpt get pods -w
```

Ollama를 띄웠다면 모델을 한 번 받아야 한다.

```bash
kubectl -n mini-chatgpt exec -it deploy/ollama -- ollama pull llama3.2
```

`http://localhost` 로 접속.

## 파일

| 파일 | 내용 |
|---|---|
| `kind-cluster.yaml` | 노드 3개, 호스트 80/443 포트 매핑 |
| `00-namespace.yaml` | Namespace |
| `01-config.yaml` | ConfigMap + Secret |
| `02-postgres.yaml` | StatefulSet + PVC + headless Service |
| `03-redis.yaml` | Deployment + Service |
| `04-app.yaml` | Deployment(replicas 2) + probes + Service |
| `05-ingress.yaml` | Ingress (SSE 버퍼링 해제 포함) |
| `06-hpa.yaml` | HorizontalPodAutoscaler (metrics-server 필요) |
| `07-ollama.yaml` | 선택. 2Gi 요청 |

각 파일의 주석에 "왜 이렇게 했는지"가 적혀 있다. YAML보다 주석이 본체다.

## 메모리가 부족하면

Ollama 없이 OpenAI API를 쓰면 된다.

```bash
# 01-config.yaml 의 LLM_PROVIDER 를 openai 로 바꾸고
kubectl -n mini-chatgpt create secret generic openai \
  --from-literal=OPENAI_API_KEY=sk-...
# 04-app.yaml 의 env 에 secretKeyRef 추가
```

## 알려진 문제 (그리고 그게 왜 학습거리인지)

**앱 Pod 2개가 동시에 시작하면서 둘 다 `create_all()`을 호출한다.**

`app/database.py`의 `init_db()`가 앱 시작 시 테이블을 만드는데, replica가 2개라
경쟁 상태가 생길 수 있다. Compose에서는 컨테이너가 하나라 안 보이던 문제다.

제대로 된 해법은 마이그레이션을 앱 시작에서 분리하는 것이다 — Alembic + K8s Job,
또는 initContainer. **여러 인스턴스를 띄우면 드러나는 종류의 문제**라서 남겨뒀다.
직접 고쳐보는 게 좋은 연습이다.

## 정리

```bash
kind delete cluster --name mini-chatgpt
```
