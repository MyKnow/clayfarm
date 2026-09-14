# ClayFarm Control — 0.3.0.dev1

**CLI-first 관리 계층의 첫 개발 빌드. 운영 완료판이 아니다.**

이 패키지는 사용자가 제공한 v0.2.2 워커의 `dist/clayfarm.pyz`에서 복원한 기존 소스를 보존하고,
`clayfarm_control`을 별도 패키지로 추가한다. 사용자 Mac의 Work 저장소나 운영 Supabase를 수정한 결과가 아니다.
원본의 개인별 `worker.enrollment.json`은 포함하지 않는다.

## 지금 실행한 범위

- 실제 FastAPI + SQLite 트랜잭션 + CLI 클라이언트 + Ed25519 장비 서명 + 재생 공격 방지.
- 참여 신청 → 관리자 승인 → 노드 목표 구성 → 검증 → 작업 claim → 실제 SVG/WAV 생성 → 업로드/완료/다운로드.
- 이메일 OTP/MFA는 Supabase HTTP 어댑터를 작성하고 **모의 HTTP 응답**으로 계약 시험. 실제 메일 전송/계정 발급 미실행.
- 레지스트리: 17개 모델 / 39개 실행 프로필 / 11개 하드웨어 구간. 실행 어댑터가 있는 것은 **7개 프로필**이다.
- 그중 CPU 2개 프로필은 실제 파일 생성 검증. CUDA/MPS 이미지 5개 프로필은 코드만 구현했고 실장비 검증하지 않았다.
- MLX, 대형 3D, 리깅, 모션 생성은 레지스트리 후보이며 새 관리 계층의 실행 어댑터는 아직 없다.

**신규 승인 큐는 기존 v0.2.2 3D 큐와 별개다.** 승인된 새 계정으로 기존 `cf_rpc`의 3D 작업을 바로 실행할 수 있다고 보고하면 안 된다.
실제 중앙 서버 소스·스키마를 확인해 이 경계를 통합하는 작업이 다음 단계다. `WORK_HANDOFF.md`를 따른다.

## 설치

Python 3.11 이상이 먼저 필요하다. 이번 설치기는 Python/드라이버를 자동 다운로드하거나 권한을 상승시키지 않는다.
OS별 설치기는 전용 가상환경을 만들고 패키지를 설치한다. 기존 설치 디렉터리는 덮어쓰지 않는다.
직접 의존성은 고정했지만 이 실행 환경의 PyPI DNS 접근 실패로 **전이 의존성 해시 lock 생성 및 새 환경 온라인 설치 검증은 못 했다**.
`evidence/dependency-lock-attempt.log`를 참고한다. 운영 배포 전 OS별 해시 lock을 생성해야 한다.

```bash
# macOS: 먼저 계획만 확인. --apply일 때 pip 다운로드/설치를 실행한다.
bash install.sh --python python3
bash install.sh --python python3 --apply
# 출력된 전용 venv의 clayfarm 절대경로를 사용하거나 해당 bin 디렉터리를 PATH에 추가한다.
```

```powershell
# Windows: Python 실행 파일을 선택한다. PowerShell 정책을 자동으로 우회하지 않는다.
.\install.ps1 -Python python
.\install.ps1 -Python python -Apply
```

소스 개발 환경에서는 다음도 가능하다.

```bash
python -m venv .venv
# macOS
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/clayfarm --help
# Windows에서는 .venv\Scripts\python.exe 와 .venv\Scripts\clayfarm.exe 사용
```

새 상태 기본 경로는 `~/.clayfarm-control`이다. 기존 `~/.clayfarm`, 기존 journal/outbox를 덮어쓰지 않는다.
`assetgen`, `assetnode`, `clayfarm legacy ...`는 기존 v0.2.2 명령을 실행한다. 이들은 새 승인 인증을 자동으로 주입받지 않는다.

## 서버·메일·GPU 없이 검증

개발/시험 의존성을 설치한 환경에서:

```bash
python -m pytest -q
clayfarm demo --out ./demo-first-run --json
clayfarm node probe --json
clayfarm models plan --experimental --json
```

`demo`는 디렉터리를 비우거나 덮어쓰지 않으므로 새 출력 경로를 사용한다.
**demo의 사람 인증은 메모리 안의 fixture이다.** 공개 서버는 이 인증기를 사용하지 않는다.
생성된 `asset.svg`, `asset.wav`는 실제 파일이지만 신경망 생성물이 아닌 제한된 SVG/DSP 결과물이다.

## 실제 서버 연결

일반 워커에 DB 비밀번호나 Supabase secret/service_role 키를 전달하지 않는다.
이 서버는 Supabase Auth의 `/user` 응답으로 사람 세션을 확인한 뒤 자체 권한 장부를 확인한다.
가입을 실제로 사용하려면 Supabase 이메일 OTP 템플릿, 일반 사용자용 SMTP, 프로젝트 정책을 운영자가 준비해야 한다.

서버 프로세스의 환경에 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`를 넣는다. DB는 기본 별도 SQLite이다.
운영 PostgreSQL은 `CLAYFARM_DATABASE_URL`과 `[postgres]` 의존성이 필요하며 `cf_control` private schema를 사용한다.
이번 세션에서는 PostgreSQL/Supabase 통합 시험을 실행하지 않았다. 서버 전용 DB 권한은 클라이언트에 노출하지 않는다.

```bash
clayfarm --home ./server-state control init
clayfarm --home ./server-state control serve --host 127.0.0.1 --port 8765
```

서버 자체는 로컬 HTTP만 기본 허용한다. 외부 노드는 HTTPS 역방향 프록시를 구성한 주소를 사용한다.
공개 bind는 `CLAYFARM_ALLOW_REMOTE=1`의 별도 운영자 opt-in이 필요하다. TLS·rate limit·백업·서버 격리는 운영 과제다.

첫 관리자도 먼저 일반 계정의 이메일 확인을 완료한다. 서버 운영자가 **그 계정의 실제 Auth UUID**를 확인해 아래 명령을 실행한다.
첫 가입자를 자동으로 관리자로 만들지 않는다. 이미 최초 관리자가 있으면 다른 사용자로 bootstrap하지 않는다.

```bash
clayfarm --home ./server-state control bootstrap --user-id '<verified-auth-uuid>' --email '<verified-email>'
```

`bootstrap`은 서버 DB 접근권을 가진 운영자 명령이다. 입력 UUID의 이메일 소유권을 다시 온라인 검증하는 기능은 없으므로
운영자가 확인된 UUID/이메일을 사용해야 한다. 클라이언트에는 이 DB 접근권을 주지 않는다.

## 가입·신청·관리자 승인

```bash
# 첫 실행. 이메일 코드는 터미널에 입력한다.
clayfarm setup --server https://farm.example.org --signup --email user@example.org --role both
# 재로그인은 --signup을 빼거나 auth login 사용
clayfarm auth login --email user@example.org
clayfarm auth whoami
clayfarm access status
clayfarm node status
```

OTP를 별도 단계로 처리하려면 `auth login --send-only` 또는 `auth signup --send-only` 후
`auth verify --code-stdin`을 사용한다. 먼저 setup으로 서버 주소가 설정되어 있어야 한다.
메일함 확인은 별도 필요하며, ClayFarm 웹사이트 방문은 필요하지 않다.

관리자는 먼저 MFA를 등록·확인한 뒤 관리 API를 사용한다. secret은 대화형 화면에서만 출력하며 JSON 로그로 반환하지 않는다.

```bash
clayfarm auth mfa-enroll
clayfarm auth mfa-verify --factor '<factor-id>'
clayfarm admin requests
clayfarm admin approve '<request-id>'
clayfarm admin desired '<node-id>' --profiles deterministic-ui procedural-sfx --expected-revision 0
clayfarm notify inbox
clayfarm notify watch --timeout 60
```

`--yes`는 일반 확인만 생략한다. 인증·관리자 권한·MFA·라이선스 동의를 대체하지 않는다.
CLI 에러는 stderr에 JSON으로 반환한다. `--no-input`은 필요한 입력이 없으면 대기하지 않고 실패한다.

## 노드 활성화·실제 작업

승인 상태와 ready는 다르다. 노드 소유자의 자동 설치 허용은 별도다.

```bash
clayfarm node policy --auto-install-builtin
clayfarm node reconcile
clayfarm node capabilities --json
clayfarm node worker
# 다른 터미널: 현재 작업을 마무리한 뒤 stop 요청
clayfarm node stop
```

CPU builtin 자동 준비만 이번 버전에 구현했다. 대형 신경망 모델은 승인된 서명 recipe·다운로드·라이선스 동의가 있어야 한다.
GPU 5개 프로필은 실제 CUDA/MPS 실행 코드가 있으나, **승인된 OS별 dependency lock/모델 hash recipe를 번들하지 않았다**.
따라서 최초 릴리스 작성·실장비 검증 전에는 바로 neural ready로 바뀌지 않는다.

```bash
clayfarm jobs submit --profile deterministic-ui --spec examples/ui.json
clayfarm jobs get '<job-id>' --wait 120
clayfarm jobs result '<job-id>' --out ./result.svg
clayfarm jobs submit --profile procedural-sfx --spec examples/sfx.json
```

등록 없이 builtin 로컬 실행도 가능하다.

```bash
clayfarm models sync --profile procedural-sfx
clayfarm models verify procedural-sfx
clayfarm models generate procedural-sfx --spec examples/sfx.json --out ./sfx-local
```

## Windows/macOS 자동 시작

```bash
clayfarm service plan
clayfarm service install
clayfarm service uninstall
```

로그인한 사용자 모드만 대상으로 한다. 로그인 전 system service는 미구현이다.
macOS plist·Windows Task XML을 만들어 등록하는 코드는 있으나 실제 두 OS의 등록·Keychain 접근은 미검증이다.

## 파일 위치

- `src/clayfarm/`: 원본 pyz에서 복원한 v0.2.2 코드. 개인 enrollment 제외.
- `src/clayfarm_control/`: 새 CLI/API/인증/레지스트리/모델/노드 실행 계층.
- `tests/`: 모의 외부 Auth와 실제 로컬 연산을 구분한 시험.
- `docs/IMPLEMENTATION_STATUS.md`: 구현·미구현·검증 경계.
- `docs/SECURITY.md`: 인증·배포·실행 신뢰 경계와 운영 전 필수 보강.
- `WORK_HANDOFF.md`: 실제 Work 저장소 반영 지침.
- `evidence/`: 실제 실행 기록과 샘플. 실장비 벤치마크가 아님.
