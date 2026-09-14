# MyKnow 홈서버 실행 패키지

`Dockerfile`은 Linux x86_64 / Python 3.12 API 서버용이다. 기본 이미지 digest와 서버 wheel SHA256을 고정한다. 모델·CUDA·Blender는 이 서버 이미지에 설치하지 않는다. 워커는 각 실제 장비에서 실행한다.

운영 배포 성공 여부와 실제 접속 주소는 [DEPLOYMENT_STATUS](../docs/DEPLOYMENT_STATUS.md)에 기록한다. 이 디렉터리의 존재만으로 운영 서버가 가동 중인 것은 아니다.

## 배포 순서

1. 현재 DB와 서버 설정을 백업하고 [CENTRAL_OPERATIONS](../docs/CENTRAL_OPERATIONS.md)의 DB 초기화·기존 farm 바인딩·최초 관리자 지정·권한 단계를 수행한다. 기존 `admin-init`이나 `sql/bootstrap.sql`을 운영 DB에 다시 실행하지 않는다.
2. `clayfarm_gateway` 권한만 가진 전용 로그인 역할을 사용한다. DB 연결은 TLS를 사용하며, SQLAlchemy URL은 `postgresql+psycopg://` 형식이다. 운영 owner/admin 연결을 서버 런타임에 넣지 않는다.
3. 아래 환경값을 `/etc/myknow/secrets/clayfarm.env` 등 기존 서버 secret 관리 위치에 만든다. 소유자 root, mode 0600을 사용하고 출력·Git·이미지에 포함하지 않는다.

```text
CLAYFARM_DATABASE_URL=POSTGRESQL_PSYCOPG_TLS_URL
CLAYFARM_FARM_ID=EXISTING_FARM_UUID
SUPABASE_URL=EXISTING_SUPABASE_HTTPS_URL
SUPABASE_PUBLISHABLE_KEY=EXISTING_PUBLIC_KEY
SUPABASE_SERVICE_KEY=SERVER_ONLY_STORAGE_KEY
```

4. 검증한 소스 SHA에서 이미지를 만들고 태그/이미지 ID를 기록한다. 업로드할 때는 Private 저장소·레지스트리 범위를 유지한다. 이 패키지는 이미지를 외부 레지스트리에 자동 공개하지 않는다.

```sh
docker build --platform linux/amd64 -f deploy/Dockerfile -t clayfarm:SOURCE_SHA .
export CLAYFARM_IMAGE=clayfarm:SOURCE_SHA
export CLAYFARM_ENV_FILE=/etc/myknow/secrets/clayfarm.env
docker compose -f deploy/compose.yaml up -d --wait
```

5. 기존 HTTPS 프록시에서 별도 ClayFarm 호스트를 `127.0.0.1:8765`로 연결한다. 프록시가 컨테이너에 있으면 기존 네트워크 규칙에 맞는 비공개 연결을 별도로 구성한다. 공개 raw 포트를 열지 않는다. 원래 요청 path·query·body를 보존한다. 노드 서명에 이 세 값이 포함되므로 경로 접두사 제거 등 임의 rewrite를 사용하지 않는다. TLS·요청 제한·50MiB 업로드 한도를 확인한다.
6. `/health`의 queue_backend가 `public.cf_jobs/cf_tasks`, parallel_queue_enabled가 false인지 확인한다. 컨테이너 healthcheck는 API 응답뿐 아니라 DB 연결·기존 farm 바인딩·런타임의 중앙 RPC 실행 권한을 검사한다. Storage와 Auth의 실사용 성공은 별도로 검증한다.
7. 실제 로그인·AAL2 승인·노드 인증·기존 큐 작업·Storage 다운로드·권한 철회를 검증한 뒤 운영 적용 완료를 기록한다.

## 복구

직전 이미지 태그/ID와 환경 파일을 보존한다. 문제가 있으면 같은 Compose 프로젝트·state 볼륨을 유지한 채 `CLAYFARM_IMAGE`를 직전 이미지로 바꿔 다시 실행한다. 최초 배포를 중단할 때는 `docker compose -f deploy/compose.yaml stop api`를 사용한다. `down -v`, 기존 작업 큐 초기화 또는 워커 저널 삭제를 하지 않는다.

DB 변경 후 새 노드 ID가 작업 이력에 들어갔으면 기존 Auth FK로 자동 되돌리지 않는다. DB 복원은 백업 시점 이후 job/attempt 손실과 기존 사용자 영향까지 별도로 검토한다. API를 멈춰도 기존 legacy 큐 경로는 보존한다.
