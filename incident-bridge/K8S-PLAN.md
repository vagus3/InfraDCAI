# Kubernetes 학습 계획

## 이 계획의 전제

**운영 환경은 계속 EC2다.** K8s는 로컬 `kind` 클러스터에서 학습용으로만 돌린다.

이유는 두 가지다.

1. **비용** — EKS는 컨트롤 플레인만 시간당 $0.10, 노드 요금은 별도다. 켜놓고 공부할 물건이
   아니다. kind는 Docker 위에서 도는 클러스터라 공짜고, 배우는 내용의 90%는 동일하다.
2. **포트폴리오에서 더 강한 답이 나온다** — "필요 없어서 안 썼다"보다
   "양쪽 다 돌려보고 이 규모에서는 안 쓰기로 했다"가 낫다. 후자는 실제로 해본 사람만
   할 수 있는 말이다.

목표는 **K8s를 도입하는 것이 아니라, 도입 여부를 판단할 수 있게 되는 것**이다.

---

## 학습 방식

각 세션은 세 부분이다.

1. **만든다** — Compose의 한 조각을 K8s로 옮긴다
2. **깨뜨린다** — 일부러 망가뜨리고 무슨 일이 생기는지 본다
3. **답한다** — 로드맵 최종 목표의 질문에 답을 적는다

2번이 핵심이다. 정상 동작하는 것만 보면 "YAML을 썼다"에서 끝난다. 무엇이 어떻게 실패하는지
본 사람만 그 기능이 왜 있는지 안다.

총 10~12시간. 저녁 시간 기준 일주일 정도.

---

## Session 0 — 준비 (30분)

```bash
# macOS
brew install kind kubectl

# 클러스터 생성 (컨트롤플레인 1 + 워커 2)
kind create cluster --config k8s/kind-cluster.yaml --name mini-chatgpt

# Ingress 컨트롤러
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=180s

# 앱 이미지 빌드해서 클러스터에 밀어넣기
docker build -t mini-chatgpt:local .
kind load docker-image mini-chatgpt:local --name mini-chatgpt
```

`kind load`가 필요한 이유를 먼저 생각해볼 것. 클러스터 노드는 별개의 Docker 컨테이너라
로컬 데몬의 이미지 목록을 공유하지 않는다. 실제 환경에서 이 자리를 채우는 게 ECR이다.

---

## Session 1 — Pod와 Deployment (2시간)

> **답할 질문: Pod는 왜 죽어도 괜찮은가?**

### 만든다

```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-config.yaml
kubectl apply -f k8s/03-redis.yaml
kubectl apply -f k8s/02-postgres.yaml
kubectl apply -f k8s/04-app.yaml

kubectl -n mini-chatgpt get pods -w
```

`k8s/04-app.yaml`을 열어서 `replicas: 2`와 probe 두 개를 확인할 것.

### 깨뜨린다

**1. Pod를 죽여본다**

```bash
kubectl -n mini-chatgpt delete pod -l app=app --wait=false
kubectl -n mini-chatgpt get pods -w
```

새 Pod가 뜬다. 이름은 다르다. 누가 만들었는지 확인:

```bash
kubectl -n mini-chatgpt get replicaset
kubectl -n mini-chatgpt describe pod <새-pod-이름> | grep -A3 "Controlled By"
```

Deployment → ReplicaSet → Pod 관계를 눈으로 확인하는 게 목적이다.

**2. liveness probe를 일부러 틀리게 한다**

`04-app.yaml`의 livenessProbe `path`를 `/health`에서 `/nonexistent`로 바꾸고 apply.

```bash
kubectl -n mini-chatgpt get pods -w
kubectl -n mini-chatgpt describe pod <pod> | tail -20
```

`CrashLoopBackOff`가 뜨는 걸 본다. 재시작 간격이 점점 길어지는 것도 확인. 되돌릴 것.

**3. liveness를 `/ready`로 바꾼 뒤 Postgres를 죽인다**

```bash
kubectl -n mini-chatgpt delete statefulset postgres --cascade=orphan
kubectl -n mini-chatgpt delete pod postgres-0
```

앱 Pod들이 전부 재시작에 들어간다. **DB가 잠깐 흔들렸을 뿐인데 멀쩡한 앱이 다 죽는다.**
`app/main.py`에 왜 `/health`와 `/ready`를 나눠놨는지가 여기서 체감된다. 되돌릴 것.

### 적는다

- Pod가 죽어도 괜찮은 이유를, "Deployment가 다시 만들어주니까" 이상으로 적어볼 것.
  (힌트: 앱이 로컬 디스크나 메모리에 무엇을 안 남기기 때문에 가능한가?)
- liveness와 readiness를 한 엔드포인트로 합치면 왜 위험한가

---

## Session 2 — Service와 Ingress (2시간)

> **답할 질문: Service와 Ingress의 차이는?**

### 만든다

```bash
kubectl apply -f k8s/05-ingress.yaml
curl http://localhost/health
```

### 깨뜨린다

**1. Service 없이 통신해본다**

```bash
kubectl -n mini-chatgpt get pods -o wide          # Pod IP 확인
kubectl -n mini-chatgpt exec -it deploy/app -- sh
  # 컨테이너 안에서
  wget -qO- http://<redis-pod-ip>:6379   # Pod IP로 직접
  wget -qO- http://redis:6379            # Service 이름으로
```

Pod를 죽이고 다시 해본다. Pod IP는 바뀌지만 Service 이름은 그대로다.
**Service는 사라지는 Pod 앞에 붙는 고정된 이름**이라는 게 핵심이다.

```bash
kubectl -n mini-chatgpt exec -it deploy/app -- cat /etc/resolv.conf
kubectl -n mini-chatgpt get endpoints
```

`endpoints`가 Service 뒤에 실제로 물려 있는 Pod 목록이다. Pod를 죽이면 여기서 빠진다.

**2. readiness를 실패시켜서 endpoints에서 빠지는 걸 본다**

Redis를 지운다. 앱의 `/ready`가 503이 되고, endpoints에서 앱 Pod가 사라진다.
**죽지는 않았는데 트래픽은 안 간다.** 이게 readiness가 하는 일이다.

**3. Ingress 어노테이션을 지운다**

`05-ingress.yaml`에서 `proxy-buffering: "off"`를 지우고 apply한 뒤 스트리밍을 해본다.
nginx.conf, Caddyfile에 이어 **세 번째로 같은 문제**를 만나게 된다.

**4. Service 타입을 바꿔본다**

`04-app.yaml`의 `type: ClusterIP`를 `NodePort`로 바꾸고 apply.

```bash
kubectl -n mini-chatgpt get svc app
docker exec mini-chatgpt-worker curl -s localhost:<nodeport>/health
```

### 적는다

- Service와 Ingress의 차이 — L4/L7, 클러스터 내부/외부, 하나당 하나/여러 서비스를 라우팅
- ClusterIP / NodePort / LoadBalancer가 각각 어디까지 노출하는가
- Compose의 서비스 이름 DNS와 CoreDNS는 무엇이 같고 무엇이 다른가

---

## Session 3 — 상태와 스토리지 (2시간)

> **답할 질문: 왜 DB는 앱과 다르게 다뤄야 하는가?**

### 본다

```bash
kubectl -n mini-chatgpt get statefulset,pvc,pv
kubectl -n mini-chatgpt describe pvc data-postgres-0
```

`k8s/02-postgres.yaml`의 주석을 읽을 것. StatefulSet과 Deployment의 차이가 적혀 있다.

### 깨뜨린다

**1. StatefulSet을 지웠다 다시 만든다**

```bash
kubectl -n mini-chatgpt delete statefulset postgres
kubectl -n mini-chatgpt get pvc        # PVC는 남아있다
kubectl apply -f k8s/02-postgres.yaml  # 데이터도 그대로
```

**2. PVC를 지운다**

```bash
kubectl -n mini-chatgpt delete pvc data-postgres-0
```

이번엔 데이터가 사라진다. PVC와 PV의 생명주기가 Pod와 분리돼 있다는 것,
그리고 **StatefulSet 삭제로는 PVC가 안 지워진다**는 게 포인트다. 안전장치다.

**3. Postgres를 Deployment로 바꿔서 replicas 2로 올려본다**

같은 볼륨에 Postgres 프로세스 두 개가 붙으면 어떻게 되는지 본다.
(로그에 lock 관련 에러가 뜬다. 이게 StatefulSet이 존재하는 이유다.)

### 적는다

- Redis는 Deployment, Postgres는 StatefulSet으로 한 판단 근거
- PV / PVC / StorageClass의 역할 분담
- 상태 있는 워크로드를 K8s에 올리는 게 왜 까다로운가

---

## Session 4 — 설정과 시크릿 (1시간)

> **답할 질문: Secret은 정말 안전한가?**

```bash
kubectl -n mini-chatgpt get secret app-secrets -o jsonpath='{.data.JWT_SECRET_KEY}' | base64 -d
```

값이 그대로 나온다. **Secret은 인코딩일 뿐 암호화가 아니다.**

```bash
kubectl -n mini-chatgpt edit configmap app-config   # 값 변경
kubectl -n mini-chatgpt get pods                    # Pod는 그대로다
kubectl -n mini-chatgpt rollout restart deploy/app  # 재시작해야 반영
```

`envFrom`으로 주입한 값은 컨테이너 시작 시점에 결정된다. 볼륨으로 마운트하면 다르게
동작하는데, 그것도 한 번 해볼 것.

### 적는다

- Secret이 안전하지 않다면 실제로는 어떻게 하는가
  (etcd 암호화, Sealed Secrets, External Secrets Operator, 클라우드 시크릿 저장소)
- EC2 배포에서 SSM Parameter Store를 쓴 것과 비교하면 무엇이 다른가

---

## Session 5 — 스케일과 무중단 배포 (2~3시간)

> **답할 질문: Kubernetes에서 무중단 배포는 어떻게 되는가? / JWT는 왜 stateless인가?**

### 만든다

```bash
# metrics-server (HPA에 필요)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

kubectl apply -f k8s/06-hpa.yaml
kubectl -n mini-chatgpt get hpa -w
```

### 깨뜨린다

**1. 무중단 배포를 실제로 관찰한다**

터미널 두 개를 연다.

```bash
# 터미널 A: 계속 요청
while true; do curl -s -o /dev/null -w "%{http_code} " http://localhost/health; sleep 0.2; done

# 터미널 B: 롤아웃
kubectl -n mini-chatgpt set image deploy/app app=mini-chatgpt:local
kubectl -n mini-chatgpt rollout status deploy/app
```

200이 끊기지 않는지 본다. 그 다음 `04-app.yaml`에서 `maxUnavailable: 0`을
`maxUnavailable: 2`로 바꾸고 다시 해본다. **이번엔 끊긴다.**

readinessProbe를 지우고도 해볼 것. 아직 준비 안 된 Pod에 트래픽이 가면서 502가 섞인다.
무중단 배포는 K8s가 알아서 해주는 게 아니라 **probe와 롤아웃 전략이 맞아야** 되는 것이다.

**2. 롤백**

```bash
kubectl -n mini-chatgpt rollout history deploy/app
kubectl -n mini-chatgpt rollout undo deploy/app
```

EC2 배포의 `deploy.sh`에 직접 짠 롤백 로직과 비교해볼 것. 무엇이 편해졌고,
그 편의를 위해 무엇을 감수하고 있는지.

**3. replicas를 늘려서 로그인 상태를 확인한다**

```bash
kubectl -n mini-chatgpt scale deploy/app --replicas=4
```

브라우저에서 로그인하고 계속 대화해본다. 매 요청이 다른 Pod로 가는데도 로그인이 유지된다.
**JWT가 stateless하다는 게 이 지점에서 실제로 눈에 보인다.**

서버 세션이었다면 여기서 무엇을 추가해야 했을지 생각해볼 것. (세션 저장소 공유,
또는 sticky session — 후자는 Pod가 죽으면 그 Pod에 붙어있던 사용자가 다 로그아웃된다.)

**4. HPA를 발동시킨다**

```bash
kubectl -n mini-chatgpt run load --rm -it --image=busybox --restart=Never -- \
  sh -c "while true; do wget -qO- http://app.mini-chatgpt:8000/health; done"
kubectl -n mini-chatgpt get hpa -w
```

CPU가 request 대비 70%를 넘으면 replicas가 는다. **request를 안 걸어두면 HPA는 동작하지
않는다** — 비율의 분모가 없기 때문이다.

### 적는다

- 무중단 배포에 실제로 필요한 것들 (readiness probe, maxUnavailable, graceful shutdown)
- HPA가 무엇을 기준으로 판단하는가, 그리고 이 앱에서 CPU가 좋은 지표인가
  (스트리밍 응답은 대부분 상위 API를 기다리는 시간이다. CPU는 거의 안 오른다.
  그럼 무엇으로 스케일해야 하는가?)

---

## 여기까지 하면 안 해도 되는 것

시간 대비 효율이 낮거나, 검증할 환경이 없는 것들.

- **Affinity / Taint / Toleration** — 단일 노드 kind에서는 의미가 없다. 개념만 읽어둘 것.
- **Service Mesh (Istio, Linkerd)** — 서비스가 2개인데 메시를 얹을 이유가 없다.
- **Operator 패턴** — 만들 CRD가 없다.
- **VPA** — HPA를 이해했으면 개념 차이만 알면 된다.
- **Model / Tensor / Pipeline Parallelism** — GPU 클러스터가 없으면 검증이 불가능하다.

## 다음 단계 (여유가 생기면)

1. **Helm** — 지금 YAML 8개를 차트로 묶기. 환경별로 값만 바꾸는 게 왜 필요한지는
   지금 매니페스트에 `localhost`가 하드코딩된 걸 보면 바로 안다.
2. **ArgoCD / GitOps** — Git 상태와 클러스터 상태를 맞추는 것. 지금 `kubectl apply`를
   손으로 하는 걸 대체한다.
3. **Prometheus + Grafana** — 이미 구조화 로그와 `/ready`가 있으니 메트릭만 붙이면 된다.

---

## 마지막에 할 것: 비교표를 DECISIONS.md에 추가

이게 이 학습의 진짜 결과물이다. 다 하고 나서 아래를 **직접 채운다.**
남이 써준 걸 외우면 면접에서 바로 티가 난다.

| | Docker Compose (EC2) | Kubernetes (kind) |
|---|---|---|
| 배포 한 번에 걸리는 시간 | | |
| 무중단 배포 | | |
| Pod/컨테이너 하나 죽었을 때 | | |
| 설정 변경 반영 방법 | | |
| 시크릿 관리 | | |
| 롤백 | | |
| 학습에 걸린 시간 | | |
| 이 프로젝트 규모에서 필요한가 | | |

그리고 한 문단으로 적는다:

> "이 서비스에 Kubernetes를 도입하지 않기로 한 이유는 ___ 이고,
> ___ 조건이 되면 도입할 것이다."

빈칸을 자기 말로 채울 수 있으면 이 학습은 끝난 것이다.

---

## 정리

```bash
kind delete cluster --name mini-chatgpt
```

로컬이라 요금은 안 나가지만 Docker 리소스는 꽤 먹는다.
