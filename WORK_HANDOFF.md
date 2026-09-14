> 이 파일은 첨부 개발 패키지의 원본 인수인계다. 현재 통합 상태는 docs/IMPLEMENTATION_STATUS.md와 docs/CENTRAL_OPERATIONS.md를 우선 확인한다. 문서의 제안은 운영 배포 권한이 아니다.

# ClayFarm 실제 Work 작업 인계

## 작업 대상과 사실

사용자의 목표는 새 설명서가 아니라 기존 ClayFarm을 CLI-first 이기종 에셋 제작 팜으로 구현하는 것이다.
이 패키지는 0.3.0.dev1 **개발 브랜치용 추가 코드**다. 실제 Mac Work 저장소를 수정한 결과가 아니다.
다른 프로젝트(Reflet/Reflect/게임 본체 등)를 ClayFarm 대신 수정하지 않는다.

첨부 ZIP은 여기서 제공된 실물 파일을 열어 사용한다. `/mnt/data/...` 문자열을 Mac 로컬 경로로 간주하지 않는다.
현재 Work에 ZIP이 없으면 첨부된 패키지를 실제 경로로 확보한 뒤 진행한다. 파일을 확인하지 않고 적용 완료로 보고하지 않는다.

## 변경 전

1. 현재 Work 루트, `git status --short`, 현재 브랜치/HEAD, remotes, AGENTS.md/CLAUDE.md와 사용자 변경을 읽는다.
2. README.md, docs/IMPLEMENTATION_STATUS.md, TEST_REPORT.md를 읽고 **구현·미구현·모의 시험** 경계를 유지한다.
3. 이 패키지의 `src/clayfarm`은 2026-09-11 v0.2.2 pyz 복원본이다. 현재 Work 소스가 더 최신이면 현재 소스를 우선한다.
4. 원본 개인 enrollment가 사용되었으면 이전 자격증명은 접근 통제하고, 승인 기반 인증의 교체 검증 후 기존 인증을 철회한다.
5. 개인 enrollment·Supabase secret·node private key·메일 비밀번호를 Git에 넣지 않는다. 사용자 PC의 다른 앱/모델/프로세스를 종료하지 않는다.

## 보수적 반영

- 자동 보조기는 기존 파일 덮어쓰기 없이 `<repo>/tools/clayfarm-control`에 이 패키지를 추가한다.
- `python scripts/apply_to_work.py --target <실제-Git-root>`는 계획만 출력한다. `--apply`가 있을 때만 새 폴더를 생성한다.
- root CLI/pyproject/기존 DB를 자동으로 덮어쓰는 스크립트가 아니다. 실제 구조에 맞춰 필요한 추가 코드를 통합한다.
- 기존 outbox/journal/worker state/모델 캐시를 초기화하지 않는다. 커밋·push는 해당 Work 규칙과 사용자 요청 범위를 따른다.

## 첫 통합 과제: 이중 큐 해소

**새 승인 시스템의 사용자/노드가 기존 3D 작업까지 안전하게 수행하도록 연결한다.**

- 운영 중앙 서버 코드·SQL·Auth/RLS/Storage 정책을 먼저 확인한다. 이 패키지에는 그것들이 완전하게 들어 있지 않다.
- 사용자 승인 ↔ 요청 권한, 노드 공개키 승인 ↔ 기존 작업 claim/결과 Storage scope의 명시적 bridge를 설계한다.
- `admin_init()`를 승인마다 재실행하지 않는다. 원본은 새 farm을 만든다.
- 사람의 세션/서비스키를 워커에 전달하지 않는다. 노드 전용 인증을 유지하고 현재 차단 상태를 서버에서 매번 확인한다.
- 새 계정·노드로 실제 SF3D 또는 TripoSR → Blender → 결과 다운로드를 시험한다.
- bridge 전에는 신규 `jobs`와 legacy 큐가 연결됐다고 보고하지 않는다.

## 두 번째: 실장비 실행 프로필

- Windows 4050/4070 Laptop, Mac M5 Pro 24GB의 실제 backend/driver/RAM/unified 예산을 탐지한다.
- CUDA/MPS 이미지 adapter 5개에 대해 공식 upstream 호환 Python·torch·diffusers·safetensors 및 전이 의존성을 고정한 hash lock을 만든다.
- 모델 repo full commit 및 전체 필요 파일 hash를 확인하고 **관리자가 승인한 release key로 서명**한다. 미확인 hash/메모리 값을 꾸며 넣지 않는다.
- 먼저 작은 실제 작업 하나를 실행해 peak memory, 속도, 산출물, timeout/OOM, 배터리 조건을 기록한다.
- CPU fallback을 GPU 실행 성공으로 표시하지 않는다. MLX는 아직 adapter가 없으므로 우선순위 모델부터 실제 연결한다.
- Mac을 CPU 전용으로 되돌리지 않는다. 고메모리 모델은 요구사항에 남기되 검증되기 전 ready를 부여하지 않는다.
- 3D/텍스처/VFX/UI/SFX/리깅/애니메이션 각각의 출력 계약과 품질 검증을 갖춘 adapter를 단계적으로 추가한다.

## 세 번째: 배포 및 전체 CLI parity

- 아직 미구현: core updater/full TUF/root rotation, canary rollout, 자동 neural model target reconciliation, 계정 삭제/관리자 위임,
  OS-native 알림/웹 UI, Python 없는 장비 bootstrap.
- 현재 signed recipe는 Ed25519 단일 trust key + sequence/expiry 검증이며 full TUF가 아니다.
- 설치·모델 업데이트의 로컬 소유자 동의와 중앙 관리자 승인을 구분한다.
- 웹에만 기능을 추가하지 않는다. 모든 새 운영 기능은 공통 API+CLI 계약으로 먼저 구현한다.

## 필수 시험과 보고

- 원본 기능 regression + `python -m pytest -q`를 실행하고 로그를 보관한다.
- `clayfarm demo --out <새-디렉터리>`는 사람 Auth가 fixture임을 명시한다. 실물 SVG/WAV 생성만 실제다.
- 테스트를 통과시키려고 보안 검사를 삭제하거나 후보 모델을 ready로 하드코딩하지 않는다.
- 노드 중지/인터넷 단절/업로드 실패/재시작/서버 승인 중복/기존 작업 보존/권한 철회를 실장비에서 검증한다.
- 최종 보고는 변경 파일, 테스트 환경, 실제 실행 모델, 미완료 요구, 커밋·push 여부를 분리한다.
