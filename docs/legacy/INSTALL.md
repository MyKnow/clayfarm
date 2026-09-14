# 설치 · 배포 · 업데이트

## 두 층을 구분한다

**Worker 코어**는 Python 3.11+와 `clayfarm.pyz` 하나면 실행됩니다. PyTorch, CUDA, Blender를 이 환경에 같이 설치하지 않습니다. 등록과 큐 통신, 재개 전송, 로컬 journal, CLI가 코어의 역할입니다.

**실행기**는 Blender 설치본과 별도의 3D 모델 Python 환경입니다. 4070 4대의 드라이버·CUDA Toolkit·Visual Studio 설치 여부가 알려져 있지 않으므로 그 부분까지 무조건 자동 성공한다고 보장하지 않습니다. NVIDIA 드라이버를 자동 교체하거나 OS 보안 정책을 바꾸지 않습니다.

## 관리자 준비

새 전용 Supabase 프로젝트에서 `sql/bootstrap.sql`을 SQL Editor로 실행한 후, 압축을 푼 폴더에서 다음을 실행합니다.

```bash
python dist/clayfarm.pyz admin-init --workers 4 --apple 1 --out enrollments
```

이 명령은 키를 터미널에서 입력받아 Auth와 Storage REST API를 사용합니다. 사용자의 프로젝트를 임의로 선택하거나 기존 데이터를 수정하지 않습니다. 등록 파일 6개를 만듭니다.

- `caller.enrollment.json`: Codex/Claude가 CLI를 실행하는 컴퓨터 전용.
- `gpu-01`~`gpu-04.enrollment.json`: 각 NVIDIA 노드마다 하나씩.
- `mac-01.enrollment.json`: Mac 전용.

프로비저닝 중 연결이 끊기면 폴더를 확인하고 생성된 계정·membership을 정리한 뒤 진행해야 합니다. `admin-init` 자체는 자동 재개 프로비저너가 아닙니다. 중단되어 비어 있지 않은 폴더 위에 새 등록 파일을 덮어쓰지 않습니다. Auth 계정이 생성되고 membership이 누락됐으면 해당 UUID의 membership을 SQL Editor에서 등록하거나 사용하지 않는 Auth 계정을 제거합니다. 일반 작업 `submit`의 재시도 프로토콜과 관리자 초기 프로비저닝은 다릅니다.

Storage bucket은 private `clayfarm`, 업로드 파일 제한은 기본 50 MiB입니다. 실제 프로젝트/요금제 제한, 용량·대역폭 비용은 별도로 확인하세요. 모델 가중치는 Storage를 거치지 않고 각 노드의 Hugging Face 캐시에 보관합니다.

## Windows 노드

```powershell
.\install.ps1 -Enrollment .\gpu-01.enrollment.json -BootstrapRuntime
assetnode doctor --online
```

PowerShell에서 설치 스크립트가 차단되면 조직의 승인 절차를 따르세요. 설치기는 시스템 ExecutionPolicy를 바꾸지 않습니다. 설치 디렉터리는 기본 `%USERPROFILE%\.clayfarm`이며 사용자/SYSTEM ACL로 제한합니다. 새 터미널에는 `assetnode`, `assetgen`이 PATH에 반영됩니다.

Blender 4.x를 공식 설치 프로그램으로 설치하면 일반적인 `Program Files\Blender Foundation\...` 경로에서 탐지합니다. 다른 위치라면:

```powershell
assetnode configure --blender "D:\Tools\Blender\blender.exe"
assetnode selftest
```

`selftest`는 실제 Blender로 작은 테스트 mesh를 후처리하고 PNG를 렌더링합니다. AI 생성 테스트는 아닙니다.

### CUDA 모델 환경

기존에 검증한 TripoSR/SF3D Python 환경이 있으면 그것을 등록하는 편이 가장 재현성이 높습니다.

```powershell
assetnode warm --engine triposr --repo "D:\AI\TripoSR" --python "D:\AI\triposr-env\Scripts\python.exe" --test-image "D:\Assets\concept.png"
```

자동 설치를 시도하려면 Git과 uv, NVIDIA 드라이버, 호환 CUDA Toolkit, C++ 빌드 도구가 있어야 합니다.

```powershell
assetnode warm --engine triposr --install --test-image "D:\Assets\concept.png"
```

recipe는 Python 3.11, PyTorch 2.5.1 / torchvision 0.20.1 / CUDA 12.4 wheel을 먼저 준비한 뒤 공식 repository requirements를 설치합니다. **CUDA wheel은 NVIDIA 드라이버 또는 NVCC 전체 설치를 대신하지 않습니다.** upstream native extension 빌드가 실패할 수 있습니다. 로그는 `.clayfarm/engines/<engine>/setup.log`, smoke 로그는 같은 폴더에 남습니다.

SF3D에는 모델 접근 권한과 라이선스 동의가 필요합니다. 키는 로컬 터미널에서만 제공하고 채팅이나 Git에 붙이지 마세요. `--accept-model-license`는 라이선스를 대신 취득하는 옵션이 아닙니다.

```powershell
assetnode warm --engine sf3d --install --test-image "D:\Assets\concept.png" --accept-model-license
```

`warm`은 실제 두 번의 smoke 실행을 수행합니다. 첫 실행은 필요한 모델/배경 제거 캐시를 준비하고, 두 번째는 `HF_HUB_OFFLINE=1`로 모델 허브 다운로드 없이 실행합니다. 모든 라이브러리의 임의 외부 통신까지 방화벽으로 차단하는 검사는 아닙니다. 실패하면 `ready=false`를 유지합니다.

### 4대의 버전을 맞추기

첫 성공 노드의 `warm` 출력에 `git_commit`, `model_revision`이 있습니다. 다른 노드에서 그 값을 지정합니다.

```powershell
assetnode warm --engine triposr --install --ref <검증된_GIT_SHA> --model-revision <검증된_MODEL_SHA> --test-image "D:\Assets\concept.png"
```

첫 설치에서 revision을 생략하면 그 시점의 upstream main을 한 번 해석해 고정합니다. 워커가 작업마다 최신 버전을 가져오지는 않습니다. 코어 `uv.lock`은 별도 GPU 환경 requirements까지 잠그지 않습니다. `environment.freeze.txt`와 `resolved-recipe.json`이 감사 자료이며, 운영 전에는 네 대의 freeze를 비교해야 합니다. 완전 동일한 GPU 바이너리 배포는 v0.1 범위가 아닙니다.

### 실행과 자동 시작

```powershell
assetnode worker
```

정상 처리 확인 후 워커를 멈추고 설치기를 자동 시작 옵션으로 다시 실행합니다.

```powershell
assetnode stop
# 기존 worker 종료 후:
.\install.ps1 -Enrollment .\gpu-01.enrollment.json -Autostart
```

Windows Task Scheduler에 현재 사용자의 `ClayFarm Worker` 로그인 트리거를 등록합니다. OS 예약 작업 권한은 장비 정책에 따라 다릅니다. 실패하면 foreground worker로 사용합니다. 배터리에서 OS가 프로세스를 강제 종료하지 않도록 예약 작업은 살아 있지만, Worker는 기본적으로 배터리일 때 **새 작업을 claim하지 않습니다.**

## M5 Pro 24GB

```bash
bash install.sh --enrollment ./mac-01.enrollment.json --bootstrap-runtime
export PATH="$HOME/.clayfarm/bin:$PATH"
assetnode doctor --online
assetnode selftest
assetnode worker
```

Blender는 `/Applications/Blender.app/Contents/MacOS/Blender` 또는 PATH에서 찾습니다. v0.1 Mac 노드는 CPU 후처리, 검사, Cycles CPU 프리뷰를 수행합니다. **MLX/MPS 추론, Metal 렌더링 및 로컬 VLM은 구현하지 않았습니다.** 이는 실제로 검증하지 않은 M5 최적화 기능을 기본 설치에 넣지 않기 위한 범위 설정입니다. GPU 노드도 같은 CPU task를 수행할 수 있어서 Mac이 사라져도 Mac 전용 단계 때문에 전체가 멈추지 않습니다.

자동 시작:

```bash
assetnode stop
# 기존 worker 종료 후:
bash install.sh --enrollment ./mac-01.enrollment.json --autostart
```

`~/Library/LaunchAgents/dev.clayfarm.worker.plist`를 등록합니다. 로그인한 사용자 세션에서 실행됩니다. 덮개를 닫거나 잠자기에 들어가도 계속 연산한다는 보장은 없습니다. 깨어난 뒤 재시작 / lease 재할당 / outbox 재전송으로 회복합니다.

## 일상 관리

```bash
assetnode status
assetnode pause
assetnode resume
assetnode stop
assetnode doctor --online
```

`pause`는 새 claim만 막고 진행 중 작업은 마무리합니다. `stop`은 새 claim을 막고 계산을 마무리한 후 프로세스를 종료합니다. 업로드가 불가능하면 outbox는 남습니다. 재시작은 `assetnode worker` 또는 OS 자동 시작 작업으로 합니다. `resume` 자체가 종료된 프로세스를 다시 띄우지는 않습니다.

오프라인에서 캐시된 추가 작업을 실행하도록 허용하려면:

```bash
assetnode stop
# 기존 worker 종료 후:
assetnode configure --offline-speculation
assetnode worker
```

기본값은 off입니다. 입력이 완전히 캐시된 최근 task만 실행하고, authoritative 결과 확정은 재연결 후에 합니다. 이미 다른 노드가 완료한 결과는 덮어쓰지 않습니다. 중복 연산을 무조건 새로운 “좋은 후보”라고 간주하지 않습니다.

## 업데이트

배포 파일의 SHA-256을 확인한 후:

```bash
assetnode stop
# 기존 worker 종료 후:
assetnode update /path/to/new/clayfarm.pyz --sha256 <배포된_해시>
assetnode worker
```

파일 해시를 검증하고 새 파일의 `--version`이 실행되는지 확인한 다음 교체합니다. 이전 파일은 `bin/clayfarm.previous.pyz`에 남깁니다. 해시는 무결성 확인이지 게시자 서명의 대체물이 아닙니다. 신뢰한 배포 경로에서 파일과 해시를 받아야 합니다. SQL schema 자동 업그레이드는 없습니다. 미래 schema 변경은 별도 migration을 검토해 적용해야 합니다.

## 제거

먼저 `assetnode stop`으로 종료합니다. 미전송 outbox가 없는지 `status`와 서버 상태를 확인합니다. Windows는 예약 작업 `ClayFarm Worker`를 제거하고 PATH 항목을 지웁니다. macOS는 `launchctl bootout gui/$(id -u)/dev.clayfarm.worker` 후 plist를 제거합니다. 그다음 `.clayfarm` 폴더를 삭제합니다. **미전송 결과가 있는 폴더를 먼저 지우면 복구할 수 없습니다.** 모델의 공유 Hugging Face 캐시는 다른 앱도 쓸 수 있으므로 자동 삭제하지 않습니다.
