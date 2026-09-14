# MyKnow 홈서버 실행 패키지

`Dockerfile`은 Linux x86_64 / Python 3.12 API 서버용이다. 기본 이미지 digest와 서버 wheel SHA256을 고정한다. 모델·CUDA·Blender는 이 서버 이미지에 설치하지 않는다. 워커는 각 실제 장비에서 실행한다.

운영 배포 성공 여부와 실제 접속 주소는 [DEPLOYMENT_STATUS](../docs/DEPLOYMENT_STATUS.md)에 기록한다. 이 디렉터리의 존재만으로 운영 서버가 가동 중인 것은 아니다.

## 배포 순서

1. 현재 DB와 서버 설정을 백업하고 [CENTRAL_OPERATIONS](../docs/CENTRAL_OPERATIONS.md)의 DB 초기화·기존 farm 바인딩·최초 관리자 지정·권한 단계를 수행한다. 기존 `admin-init`이나 `sql/bootstrap.sql`을 운영 DB에 다시 실행하지 않는다.
2. `clayfarm_gateway` 권한만 가진 전용 로그인 역할을 사용한다. DB 연결은 `sslmode=verify-full`로 인증서와 호스트 이름을 검증하며, SQLAlchemy URL은 `postgresql+psycopg://` 형식이다. 운영 owner/admin 연결을 서버 런타임에 넣지 않는다.
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

### CLI update feed

서명된 control wheel을 배포할 때는 컨테이너의 state 볼륨 아래에 다음 구조를 사용한다.

```text
/var/lib/clayfarm/updates/
  manifests/control-<version>.json
  artifacts/clayfarm_control-<version>-py3-none-any.whl
```

manifest의 공개키는 서버와 사용자 CLI의 `trust.json`에 동일하게 고정해야 한다. API는
서명이 유효하고 artifact hash가 일치하는 manifest만 `/v1/updates/check`와
`/v1/updates/artifacts/{release_id}`로 제공한다. 운영 feed에 올릴 wheel·manifest·서명키가
없는 상태에서는 `/v1/updates/check`가 업데이트 없음으로 응답한다. 릴리스 생성과 CLI 사용은
[`docs/CLI_UPDATES.md`](../docs/CLI_UPDATES.md)를 따른다.

### 기존 Docker HTTPS 프록시에 연결

`compose.edge.yaml`은 기존 프록시 네트워크에 API를 `clayfarm-api` 이름으로 연결한다. DB 전용 네트워크가 아니라 프록시의 애플리케이션 네트워크를 선택한다. 기본 Compose의 loopback 포트와 실행 제한은 그대로 적용된다.

```sh
export CLAYFARM_HTTPS_NETWORK=EXISTING_PROXY_NETWORK
docker compose -f deploy/compose.yaml -f deploy/compose.edge.yaml config --quiet
docker compose -f deploy/compose.yaml -f deploy/compose.edge.yaml up -d --wait
```

[Caddyfile.example](Caddyfile.example)의 호스트 이름을 실제 DNS 이름으로 바꾸고 기존 Caddyfile에 추가한다. 기존 파일을 예제로 교체하지 않는다. 설정 백업과 검증 뒤 해당 Caddy 실행 방식이 지원하는 reload를 사용한다. Caddy 2.11 이상에서 `caddy run --config ...`로 시작했고 API로 설정을 바꾸지 않았다면 `SIGUSR1` reload를 지원한다([공식 운영 문서](https://caddyserver.com/docs/running)). 도메인 DNS·인증서 발급·일반 HTTPS 접근은 각각 확인한다. 이 예제의 크기 제한은 요청 횟수 제한을 구현하지 않는다.

## 복구

직전 이미지 태그/ID와 환경 파일을 보존한다. 문제가 있으면 같은 Compose 프로젝트·state 볼륨을 유지한 채 `CLAYFARM_IMAGE`를 직전 이미지로 바꿔 다시 실행한다. 최초 배포를 중단할 때는 `docker compose -f deploy/compose.yaml stop api`를 사용한다. `down -v`, 기존 작업 큐 초기화 또는 워커 저널 삭제를 하지 않는다.

DB 변경 후 새 노드 ID가 작업 이력에 들어갔으면 기존 Auth FK로 자동 되돌리지 않는다. DB 복원은 백업 시점 이후 job/attempt 손실과 기존 사용자 영향까지 별도로 검토한다. API를 멈춰도 기존 legacy 큐 경로는 보존한다.

### DB 인증서 검증

Supabase의 DB 연결은 전용 CA가 필요할 수 있다. [공식 SSL 안내](https://supabase.com/docs/guides/platform/ssl-enforcement)에 따라 인증서를 확보하고, 공개 CA 파일을 서버의 읽기 전용 위치에 보관한다. 서버 URL에 `sslmode=verify-full&sslrootcert=/run/certs/database-ca.crt`를 지정하고 `compose.tls.yaml`을 함께 사용한다. TLS 오류가 나면 올바른 CA를 확인하며 인증서 검증을 끄지 않는다.

`CLAYFARM_DATABASE_CA`는 호스트의 CA 파일 경로다. 예를 들어 홈서버에서는 `/opt/clayfarm/certs/supabase-ca.crt`를 사용한다. 프록시와 전용 CA가 모두 필요하면 세 Compose 파일을 순서대로 적용한다.

`docker compose -f deploy/compose.yaml -f deploy/compose.edge.yaml -f deploy/compose.tls.yaml up -d --wait`

### 가입 메일

운영 OTP 메일에는 [email-code.html](email-code.html)을 signup confirmation과 magic link 템플릿에 적용한다. 이메일 확인과 TOTP를 비활성화하지 않는다. 기본 Supabase 발송은 일반 사용자 수신 및 무료 프로젝트의 템플릿 변경에 제약이 있으므로 운영 SMTP를 구성한다([공식 안내](https://supabase.com/docs/guides/auth/auth-smtp)).

현재는 사용자 승인으로 기존 Resend를 사용하며 발신자는 `ClayFarm <clayfarm@ssartnership.myknow.xyz>`다. 기존 검증된 인증 메일 도메인과 발송 키를 재사용하므로 키 교체 시 두 서비스의 설정을 함께 관리한다. SMTP 자격증명은 Supabase Auth 설정에만 공급하고 Git이나 API 이미지에 넣지 않는다. 현재 Management API의 `smtp_port`는 문자열 `"465"`를 요구한다. 기본 시간당 2회 한도가 custom SMTP 설정 후에도 남아 있으면 실제 가입이 429로 거부될 수 있다. 이 프로젝트는 발송 한도를 시간당 30회로 조정하고 같은 수신자 재발송 간격 60초와 기존 코드 검증 제한은 유지했다. 적용 성공과 실제 이메일 수신·코드 검증은 각각 확인한다.
