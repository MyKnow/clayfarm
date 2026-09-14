# ClayFarm Work — 0.4.0.dev2 integration

새 CLI의 승인 계정·Ed25519 노드 인증을 기존 ClayFarm의 **동일한 PostgreSQL 3D DAG와 private Storage**로 연결한 개발 저장소다. MyKnow 홈서버에 중앙 API와 운영 DB 통합을 적용했고 공개 HTTPS·실제 이메일 로그인·Mac 자격증명 저장을 확인했다. 실제 MFA·Mac 노드 승인과 새 CLI 제출 → 기존 Windows TripoSR → 새 Mac Blender → 결과 다운로드를 같은 운영 큐에서 확인했다. Windows 새 CLI 전환·전체 모델 검증은 남아 있다.

현재 로컬 코드 버전은 `0.4.0.dev2`이며, 운영 API는 서명 wheel/feed를 발행하기 전까지 기존 `0.4.0.dev1` 상태로 유지된다.

**현재 사용자용 웹 화면은 없다. 서비스 주소는 CLI가 사용하는 API 서버이며, 웹 UI는 추후 작업이다.**

- 중앙 모드는 `public.cf_jobs`, `cf_tasks`, `cf_attempts`, `cf_workers`를 사용한다. 작업을 새 큐에 복제하지 않는다.
- 기존 `cf_rpc`와 새 gateway는 동일 dispatcher를 호출한다. 기존 등록과 저널을 보존한다.
- 별도 개발 큐는 `--development-queue` 또는 `demo`에서만 사용한다. 중앙 모드는 해당 실행 API를 거부한다.
- 실제 PostgreSQL·Supabase Storage API·Blender 통합 시험이 있다. 사람 인증과 재구성 입력 fixture는 운영 인증·AI 생성 증거가 아니다.
- Mac MPS/MLX GPU 연산은 확인했다. SD-Turbo는 실제 가중치 로드 후 메모리 상한에서 실패했다. MLX 모델 어댑터는 미구현이다. 둘 다 모델 ready로 승격하지 않았다.
- Windows RTX 4050 Laptop에서 TripoSR의 실제 CUDA 추론·좌표 보정·Blender 후처리·CPU revision과 SD-Turbo의 실제 CUDA 이미지 생성을 확인했다. signed release/운영 node ready는 발행하지 않았다.
- 합성 ancestry와 기계 검사 실패 결과는 `diagnostic_candidates`로 표시한다. `ready_candidates`는 실제 출력의 기계 검사 통과이며, 별도의 시각 승인까지 뜻하지 않는다.

현재 상태는 [IMPLEMENTATION_STATUS](docs/IMPLEMENTATION_STATUS.md), 재현·운영 경계는 [CENTRAL_OPERATIONS](docs/CENTRAL_OPERATIONS.md), 큐 계약은 [QUEUE_BRIDGE](docs/QUEUE_BRIDGE.md)를 따른다. 첨부 패키지의 문서는 `docs/*_UPSTREAM.md`에 구분해 보존했다.

## 로컬 Text-to-Sound

텍스트에서 음원을 만드는 작업은 로컬 모델 런타임과 기존 CLI 제어 경계를
사용한다. BGM(`lobby`, `preparation`, `combat`, `result`)과 SFX(`event_id`)는
서로 다른 스펙이며, Lobby와 Preparation을 한 곡으로 합치지 않는다. Stable
Audio 3 Small-Music/SFX의 CPU·CUDA·MLX 후보가 카탈로그에 있지만, 실제 고정
런타임·가중치·장비 측정이 끝난 프로필만 실행 가능 상태로 승격한다.

현재 PostgreSQL 중앙 브리지는 `reconstruct/process/preview`와 기존 3D
capability만 허용한다. 오디오를 중앙 작업으로 광고하거나 기존 3D 큐와
통합 완료로 표시하지 않으며, SQL task capability·중앙 워커·Storage E2E
마이그레이션이 끝난 뒤에만 중앙 제출 경로를 열 수 있다.

```sh
# 예제 스펙 확인
cat examples/bgm-lobby.json

# 운영자가 서명한 pinned release를 설치한 뒤 (라이선스/다운로드 동의 필요)
clayfarm models sync --profile sa3-small-music-cpu \
  --recipe ./stable-audio-small-music-release.json \
  --accept-license --allow-download
clayfarm models verify sa3-small-music-cpu --spec examples/bgm-lobby.json
clayfarm models generate sa3-small-music-cpu \
  --spec examples/bgm-lobby.json --out ./audio/lobby
```

생성 결과는 `asset.wav`, `waveform.json`, `spectrogram.svg`,
`audio-report.json`으로 구성된다. WAV를 사람이 청취 승인한 뒤에만 Unity용 OGG와
기존 `SoundManager`/`AudioMixer`에 연결한다. 전체 BGM/SFX 필드와 실패·검수
경계는 [AUDIO_PIPELINE](docs/AUDIO_PIPELINE.md)을 따른다.

### 사운드 방향 카드

사용자 문장을 모델 프롬프트로 직접 보내지 않으려면 schema version 2 SFX
스펙의 `direction` 카드를 작성한다. 카드는 검토 가능한 action·attack·tail·
주파수 sweep·필수 요소·금지 요소를 담고, `source_text`는 추적용 해시로만
보존한다. 다음 명령으로 카드와 모델 입력을 각각 확인할 수 있다.

```sh
clayfarm audio direction validate --spec examples/sfx-sword-whoosh-direction.json
clayfarm audio direction compile --spec examples/sfx-sword-whoosh-direction.json
clayfarm audio generate sa3-small-cpu \
  --spec examples/sfx-sword-whoosh-direction.json --out ./audio/sfx/sword-whoosh
```

컴파일된 prompt에는 원문이 포함되지 않으며, 모델 프로필이 지원하지 않는
negative/reference 조건은 자동 검수 조건으로 남는다. 전체 카드 필드와
후보·승인 경계는 [AUDIO_PIPELINE](docs/AUDIO_PIPELINE.md)에 기록한다.

### 절차적 SFX 후보 (`procedural-sfx`)

`procedural-sfx`는 모델 가중치·다운로드 없이 Python 표준 라이브러리 연산만으로
`beep`, `whoosh`, `impact`, `sword_swing`, `wind_whoosh`를 만드는 내장 프로필이다. 결과는
48 kHz 모노 PCM `asset.wav` 하나이며 `details.neural`은 항상 `false`다. 같은
`seed`·`seconds`·`frequency`에서는 항상 같은 바이트가 나온다.

```sh
# 내장 프로필 준비 (확인 프롬프트 승인 필요, 다운로드 없음)
clayfarm models sync --profile procedural-sfx
clayfarm models verify procedural-sfx

clayfarm models generate procedural-sfx \
  --spec examples/sfx-sword-swing.json --out ./audio/sfx/sword-swing
```

금속성 요소를 제외한 짧은 “휙” 후보는 `examples/sfx-wind-whoosh.json`을
사용한다. 두 효과 모두 절차적 후보이므로 `asset.wav`를 직접 듣고 선택한다.

이 출력은 Stable Audio 등 신경망 모델 결과가 아니고 게임에 바로 쓸 완성
사운드도 아니다. 다른 오디오와 마찬가지로 사람이 `asset.wav`를 청취 승인한
뒤에만 Unity 연결 단계로 넘긴다.

## Unity 임포트

ClayFarm FBX의 Mesh Compression은 **Medium 고정**이다. 리그·블렌드셰이프·모델 내부 애니메이션을 모두 사용하지 않는 에셋에는 Import BlendShapes 끄기, Animation Type None, Import Animation 끄기를 적용한다. Unity용 Editor 스크립트와 분류·설치 방법은 [UNITY_IMPORT_POLICY](docs/UNITY_IMPORT_POLICY.md)를 따른다.

## 설치

제어 CLI는 Python 3.12와 Git을 사용한다. Blender와 CUDA/MPS/MLX 모델 환경은 별도로 설치한다. 이 설치 과정은 모델을 다운로드하거나 GPU 드라이버를 변경하지 않는다. 비공개 저장소를 내려받으려면 GitHub 접근 권한이 필요하다.

```sh
git clone https://github.com/MyKnow/clayfarm.git
cd clayfarm
```

macOS Apple Silicon:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r locks/control-macos-arm64-py312.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
source .venv/bin/activate
clayfarm --version
clayfarm doctor
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r locks/control-windows-amd64-py312.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
# 활성화 스크립트 없이 실행할 경우 아래 경로를 사용한다.
.\.venv\Scripts\clayfarm.exe --version
.\.venv\Scripts\clayfarm.exe doctor
```

이후 예제의 `clayfarm`은 Windows에서 `.\.venv\Scripts\clayfarm.exe`로 대체할 수 있다. Windows lock은 생성했지만 이 신규 설치 경로의 Windows 검증은 아직 완료하지 않았다. `install.sh`/`install.ps1` 편의 설치기는 별도 환경을 만들며, 해시 고정 설치에는 위 절차를 사용한다.

## 검증

```sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/test_central.py --real-storage --blender /absolute/path/to/blender
```

두 번째 명령은 임시 Docker 네트워크·PostgreSQL·Storage만 만들고 종료 시 정리한다. 기존 서버에 접속하지 않는다. 실장비 옵션이 없는 검사는 명시적으로 skip한다. 게임 저장소 래퍼 전용 `tests_legacy/test_repository.py`는 이 독립 저장소의 테스트 대상이 아니다.

## 중앙 CLI

API 주소는 `https://clayfarm.myknow.xyz`다. Let's Encrypt 인증서와 일반 HTTPS 접속을 확인했다. 실제 적용 상태는 [DEPLOYMENT_STATUS](docs/DEPLOYMENT_STATUS.md)에 기록한다. 노드에 service key, DB 비밀번호, 다른 사람의 세션을 전달하지 않는다.

### 가입·참여 신청

```sh
clayfarm setup --server https://clayfarm.myknow.xyz --signup --role caller
clayfarm auth whoami
clayfarm access status
```

이메일과 이메일 인증 코드를 대화형으로 입력한다. `setup --role caller`는 가입/로그인 후 참여 신청까지 수행하며, 승인되기 전에는 작업을 제출할 수 없다. 기존 계정은 `--signup`을 생략한다. 코드 입력을 나중에 하려면 `clayfarm auth login --email YOUR_EMAIL --send-only`와 `clayfarm auth verify`를 사용한다. 인증 코드를 명령 인수나 파일에 저장하지 않는다.

메일 요청에서 429가 나오면 즉시 반복 요청하지 않는다. 운영 메일 제한은 프로젝트 전체 시간당 30회, 같은 주소의 재발송 간격은 60초다. 이미 받은 유효한 코드가 있으면 `clayfarm auth verify --email YOUR_EMAIL`로 새 메일 없이 검증한다. 별도 상태 폴더를 썼다면 모든 인증 명령에 같은 `--home`을 지정한다.

`vault_locked`는 이 장비의 자격증명 저장소를 사용할 수 없다는 뜻이다. CLI는 메일 발송과 이메일·MFA 코드 검증 전에 임시 비밀 없는 항목으로 저장·읽기·삭제를 확인한다. 기존 세션이나 노드 키를 덮어쓰지 않으며 평문 저장소로 전환하지 않는다. Mac의 login 키체인이 잠겨 있다면 본인 터미널에서 다음 순서로 확인한다.

```sh
security unlock-keychain "$HOME/Library/Keychains/login.keychain-db"
clayfarm auth check-vault
clayfarm auth login --email YOUR_EMAIL
```

첫 명령의 비밀번호는 Mac 터미널에만 입력한다. 별도 `--home`을 사용하는 경우 두 ClayFarm 명령에 모두 지정한다. `check-vault`는 메일을 보내지 않는다. 이전 버전에서 이메일 코드 검증 후 저장에 실패했다면 코드는 이미 소비됐을 수 있으므로 잠금을 해제한 뒤 새 로그인 코드를 받는다. 사전 점검 이후에 저장소가 다시 잠기면 저장이 실패할 수 있다. 기존 키체인을 초기화하거나 지우지 않는다([Apple 오류 설명](https://developer.apple.com/documentation/security/errsecinteractionnotallowed)).

### 관리자 승인

첫 관리자는 서버 운영자가 실제 이메일 검증이 끝난 Auth 계정을 지정한다. 이후 관리자 계정으로 로그인하고 MFA를 완료한다.

```sh
clayfarm auth mfa-enroll --verify-now
clayfarm admin requests
clayfarm admin approve REQUEST_UUID --grant creator-basic
clayfarm admin users
```

MFA 등록 키를 본인 인증기 앱에 추가한 뒤 같은 명령에서 현재 코드를 입력한다. 관리자 승인은 현재 AAL2 세션이 필요하다. 기존에 검증된 인증기가 있으면 등록을 바꾸지 않고 해당 인증기로 검증한다.

미완료 등록 키는 사용자별 OS 자격증명 저장소에만 임시 보관하여 재실행 때 같은 키를 사용하고, 검증 성공 후 제거한다. 키를 잃어버린 이전 버전의 미완료 등록은 `clayfarm auth mfa-enroll --restart --verify-now`로 다시 준비한다. `--restart`는 검증된 인증기를 해제하지 않는다. 별도 단계로 진행하려면 `--verify-now`를 생략하고 출력된 `next` 명령을 사용한다. 이 명령은 같은 `--home`을 유지한다. 등록 키는 JSON·리다이렉트된 출력으로 내보내지 않는다.

### 워커 등록·실행

계정 로그인 후 각 장비에서 새 노드 키를 등록한다. 관리자가 노드 신청을 승인하고 실행 엔진을 허용해야 한다.

```sh
clayfarm node register --name my-node
clayfarm node status
# 관리자 장비에서:
clayfarm admin requests
clayfarm admin approve NODE_REQUEST_UUID
clayfarm admin engines NODE_UUID --engines triposr blender
# 워커 장비에서:
clayfarm node selftest --blender /absolute/path/to/blender
clayfarm node warm --engine triposr --repo /path/to/TripoSR --python /path/to/python --test-image concept.png
clayfarm node worker --once
clayfarm node worker
```

Mac의 Blender 전용 워커에는 `blender`만 허용한다. 현재 중앙 3D 재구성기는 검증된 Windows CUDA 환경을 사용한다. MPS/MLX 런타임 탐지와 중앙 3D 모델의 실행 지원은 서로 다르다.

`node warm --install`은 source/model 전체 commit hash가 필요하다. 온라인·오프라인 실행마다 새 출력 경로를 검사한다. `admin engines`는 실행 허용 상한만 지정한다. 실제 warm/selftest 증거가 없는 엔진은 새 워커가 광고하지 않는다. 기존 실행기 설정을 지정하려면 `node configure --runtime FILE`을 사용하며, 이 명령은 기존 실행 설정 전체를 교체하므로 기존 값을 포함해야 한다.

### 3D 작업 제출·결과 확인

```sh
clayfarm jobs submit --engine triposr --concept concept.png --spec examples/legacy/hammer.spec.json
clayfarm jobs list
clayfarm jobs get JOB_UUID --wait 60
clayfarm jobs result JOB_UUID --out review
clayfarm jobs approve JOB_UUID --task PROCESS_TASK_UUID
```

`hammer.spec.json`은 해머용 예제이므로 제작할 에셋에 맞게 복사해 수정한다. GLB/FBX와 미리보기를 직접 검토한 뒤 후보를 승인한다. 기계 검사 통과와 사용자 시각 승인은 별개이며, 합성 결과는 승인할 수 없다. FBX를 Unity에 넣을 때는 위 Unity 임포트 규칙을 설치한다.

```sh
clayfarm jobs retry-submit JOB_UUID
clayfarm jobs cancel JOB_UUID
clayfarm node stop
clayfarm notify inbox
clayfarm models plan
clayfarm models list
```

`retry-submit`은 해당 CLI의 로컬 저널에 남은 제출을 재시도한다. `node stop`은 현재 계산이 끝난 뒤 새 작업 수신을 중지한다. 재시작할 때는 같은 `--home`으로 `node worker`를 실행해 저널과 미전송 결과를 이어서 사용한다. 모델 목록의 후보·설치 상태는 ready가 아니며 실제 실행 검증과 현재 메모리 조건을 충족해야 한다.

새 상태는 `~/.clayfarm-control`에 저장한다. `clayfarm legacy`, `assetgen`, `assetnode`는 보존된 기존 등록 방식으로 실행하므로 새 인증 세션을 자동 사용하지 않는다.

## CLI 버전과 업데이트

Control CLI는 [`docs/CLI_UPDATES.md`](docs/CLI_UPDATES.md)에 정의한 signed wheel 경로를
사용한다. 기능 개선마다 `src/clayfarm_control/version.py`의 버전을 올린 뒤 사용자는
다음 순서로 확인·다운로드·적용한다.

```sh
clayfarm update check
clayfarm update download
clayfarm update apply --yes
```

업데이트 키가 아직 등록되지 않았다면 운영자가 전달한 공개키를 먼저 `clayfarm trust add`로
고정한다. CLI는 서명·플랫폼·hash 검증에 실패한 wheel을 설치하지 않으며 백그라운드에서
임의로 업데이트하지 않는다.

## 서버 운영

상시 API 호스트는 MyKnow 홈서버, 데이터와 Storage는 기존 ClayFarm Supabase 프로젝트를 사용한다. 신규 farm이나 별도 작업 큐를 만들지 않는다. 백업·DB 변경·관리자 지정·서버 시작 순서는 [CENTRAL_OPERATIONS](docs/CENTRAL_OPERATIONS.md), 실제 적용 결과는 [DEPLOYMENT_STATUS](docs/DEPLOYMENT_STATUS.md)를 따른다. 서버 전용 자격증명과 사용자·노드 상태, 모델 캐시, 로그는 GitHub에 올리지 않는다.
