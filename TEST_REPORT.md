# 테스트 보고 — Work 통합, 2026-09-12

첨부 패키지 작성 당시 결과는 [TEST_REPORT_UPSTREAM](docs/TEST_REPORT_UPSTREAM.md)에 보존했다.

## 추가 검증 — Private 업로드·홈서버 배포 준비, 2026-09-14

- 기존 core·제어 계층·실제 Blender·journal 회귀: **173 passed, 12 subtests passed**.
- 실제 PostgreSQL 17·Supabase Storage API·Blender 중앙 통합: **20 passed**. 사람 인증과 재구성 입력은 fixture다.
- 서버 준비 상태·배포 파일 포함 검사: **11 passed**(신규 healthcheck 5개, 기존 packaging 6개).
- Linux amd64 서버 이미지 빌드, CLI version, `pip check`, Compose 구성 검사 통과. Python 3.12 서버 wheel 33개 SHA256 고정.
- 읽기 전용 루트·UID 10001·전용 볼륨으로 실제 Linux API와 PostgreSQL 연결 시험. 동일 중앙 큐 health, 준비 상태 exit 0, 비로그인 401, DB 종료 후 준비 상태 exit 1 및 비밀 미출력 확인. Auth/Storage 주소는 fixture이므로 hosted E2E는 아니다.
- Gitleaks v8.18.4로 업로드 대상 소스만 별도 복사해 검사: **no leaks found**. 가상환경·모델·작업 저널·로그·서버 환경 파일은 업로드 대상에서 제외했다.
- 로컬 기록: ignored `work/publish-preflight-20260914/`. 운영 Supabase 코드/작업 상태는 읽기만 했고 DB·Storage·홈서버 서비스는 변경하지 않았다. GitHub/홈서버 인증 복구가 남아 있다.

## 추가 검증 — Unity 임포트 규칙, 2026-09-14

- macOS Unity **6000.3.22f1** 실제 FBX 임포트 **8개 시나리오 통과**, batch exit 0. Blender **5.2.1**로 리그·블렌드셰이프·애니메이션 클립이 포함된 합성 FBX를 생성했다.
- ClayFarm 범위 Medium 고정, StaticMeshes만 세 옵션/실제 클립·블렌드셰이프 제외, 중첩·유사 이름·대소문자 경로, 재임포트 강제, 개별 기능 설정 및 스케일/Read-Write/userData 보존을 확인했다.
- `.venv/bin/python -m pytest -q`: **114 passed, 22 skipped**. 이번 실행에서 PostgreSQL 및 Python Blender 검사는 환경변수를 설정하지 않아 skip했다. 기존 중앙·실장비 검증 수치를 이번 실행 결과로 합산하지 않는다.
- 재현 방법: [tests/unity](tests/unity/README.md). 이번 로그와 receipt는 ignored `work/unity-import-policy-20260914/`에 보관했다.
- 독립 시험 프로젝트에서 확인했다. 게임 프로젝트 설치·실제 생성 에셋의 시각/로딩 품질·Windows Unity 시험·커밋·push는 수행하지 않았다.

## 기존 Work 통합 검증 — 2026-09-12

| 검증 | 결과 | 증거 경계 |
|---|---|---|
| 제어 계층 단위/계약 + 기존 core/Blender/journal Python 시험 | 최종 전체 171 passed, 12 subtests passed | 기존 게임 저장소 래퍼 tests_legacy/test_repository.py는 대상 밖 |
| 최종 중앙 통합 실행기 | 20 passed, 최종 gateway 권한 축소 뒤 관련 2개 재검증 통과 | 실제 PostgreSQL 17, Storage API v1.60.4; 사람 Auth는 fixture |
| 최종 모델·실행 자격증명 경계 회귀 | 30 passed | 기존 29개 재검증과 gateway 환경값 비상속 검사 1개 추가 |
| 실제 Blender DAG | 위 중앙 시험에 포함 | 합성 재구성 입력 → 실제 후처리·6뷰·Storage·caller 다운로드; mock 유지 및 승인 거부 |
| 원본 SQL smoke | 위 중앙 시험에 포함 | 새 migration 이후 원본 cf_rpc의 RLS·queue·attempt 계약 |
| Mac 제어 계층 clean install | 성공 | 새 Python 3.12 venv + --require-hashes lock + editable package + CLI version |
| Mac 모델 환경 | 설치·의존성 검사 성공 | torch 2.14.0/diffusers 0.40.0/transformers 5.17.0/MLX 0.32.2. 모델 실행 성공과 별개 |
| MPS/MLX 실제 GPU tensor | 성공 | MPS device=mps:0, MLX Device(gpu, 0), 연산값 확인 |
| SD-Turbo MPS | 실제 모델 로드/실행 실패 | 고정 fp16 가중치. 현재 가용 메모리에서 budget 초과 OOM, ready=false |
| OOM 후 복구 | 새 프로세스의 MPS/MLX 연산 성공; 모델 재시도는 OOM | 신경망 생성 성공으로 승격하지 않음 |
| Windows CUDA | RTX 4050 Laptop에서 실제 TripoSR CUDA 추론·CPU mesh extraction 온라인/새 오프라인 실행 통과 | 고정 source/weights, 단일 입력. 새 CLI/운영 큐 end-to-end 아님 |
| Windows 시각 결함 | 원본 GLB 후처리 의자가 누워도 hard_pass가 통과함을 확인. 최종 official viewer 변환·exact executor에서 upright 및 legacy/revision 호환 통과 | 의미상 정면과 입력 대비 색감은 caller 검토 필요. 정점색/shader 연결 삭제는 확인되지 않음 |
| Windows SD-Turbo | 고정 fp16 가중치, 실제 CUDA 512×512 이미지 생성 성공 | CPU fallback/socket 사용 없음. unsigned 진단이며 모델 운영 ready 미발급 |
| Windows CUDA 실패 복구 | allocator 예산 5%에서 실제 OOM, sanitized 실패·PNG 없음, 프로세스 종료/VRAM baseline 복귀 뒤 새 프로세스 재실행 성공 | 재생성 이미지 hash 동일. 의도적으로 제한한 예산 시험이며 운영 부하 최대값이 아님 |
| SDXL CUDA/MPS 사전점검 | UNet 1680개 F16 tensor 최소 5,134,927,368B > 현재 장비 예산. fp16 파일과 header 구조·offset 확인 후 설치 전 차단 | 메타데이터/부분 header 검증이며 전체 weight hash·실제 forward·OOM 실행은 아님 |
| 최종 축·메모리 통합 | 중앙 20개 재통과. 공식 viewer yaw 보정 후 관련 49개 통과(신규 1개 포함) | 중복 실행 포함. 실제 Blender와 단위/fixture 범위를 구분 |
| 최종 CUDA 예산/registry/models 회귀 | 53 passed, 신규 예산 전달/적용 테스트 2개 포함 | 최초 calibration 상한을 모델 로드 전에 적용. Windows 최신 entry에서도 실제 제한 OOM과 회수 확인 |
| 운영 OTP/MFA·hosted DB/Storage | 미실행 | 운영 서버 변경·배포·live end-to-end 성공 주장 없음 |

실행 명령:

- `python scripts/test_central.py --real-storage --blender /opt/homebrew/bin/blender --evidence work/final-integration-evidence`
- `CLAYFARM_TEST_BLENDER=/opt/homebrew/bin/blender python -m pytest -q tests --ignore=tests/test_central_bridge.py tests_legacy/test_core.py tests_legacy/test_blender.py tests_legacy/test_journal_paths.py`
- `python scripts/verify_model_hardware.py --profile sd-turbo-mps --python RUNTIME_PYTHON --model-dir PINNED_WEIGHTS --manifest HASH_MANIFEST --out NEW_DIRECTORY`

마지막 전체 로그는 `work/final-acceptance-python.log`이다. `ready_candidates`에는 합성 ancestry가 없고 기계 검사를 통과한 결과만 담는다. 합성 결과·검사 실패는 `diagnostic_candidates`로 내려가며 미리보기·다운로드 증거는 유지한다. 기존 mock 표식을 놓친 worker 결과도 parent lineage로 판별한다.

Windows 상세 수치·소스 hash·실제 실행 범위는 `docs/WINDOWS_HARDWARE_RESULT.json`에 기록했다. Windows 모델 환경은 TripoSR torch2.5.1+cu124, SD-Turbo torch2.5.1+cu124/diffusers0.31.0/transformers4.46.3이며 Mac 모델 환경과 별도로 검증했다.
SD-Turbo의 설치 환경 snapshot은 `locks/model-diagnostic-windows-py311.freeze.txt`이며 원격 freeze SHA256과 일치했다. 이것은 설치된 버전 목록이고 wheel hash로 잠근 설치 파일은 아니다. 실제 실행한 8개 제어 runtime 파일 hash도 수신 당시 로컬 통합본과 독립적으로 대조해 일치했다. 그 후 추가한 CUDA 요청 예산 적용은 별도의 source hash와 검증으로 기록한다.
최신 runtime `a8590aeb…`에서 `device_budget_bytes=322122547` 요청만으로 실제 제한 OOM·sanitized receipt·exit1·프로세스 종료·VRAM baseline 복귀를 확인했다. 외부 allocator 설정은 사용하지 않았다. 정상 이미지 생성/재생성은 앞선 runtime `0f597964…`의 증거이며, 최신 runtime에서 정상 생성까지 재실행한 것으로 주장하지 않는다.

SD-Turbo MPS는 3번째 실제 실행도 현재 동적 예산에서 OOM이었다. 마지막 적용 budget 916,570,112B, sampled driver peak 1,175,420,928B, 3.31초였다. 드라이버 메모리 샘플과 allocator 제한값은 같은 측정 대상이 아니다. SDXL 사전점검의 Mac 가용 RAM은 6,092,210,176B였으며 이후 실행 직전 probe에서는 감소했다. SDXL 차단 근거와 Windows 사전점검 값은 `docs/SDXL_PREFLIGHT.json`에 있다.

SD-Turbo 고정 model commit: `b261bac6fd2cf515557d5d0707481eafa0485ec2`. 12개 파일 SHA256을 기록하고 3개 대형 safetensors 파일을 upstream LFS SHA256과 대조했다. 두 번째 실패 receipt의 샘플 peak: host 349,880,320 bytes, MPS 1,175,420,928 bytes, 실행 17.31초. 이는 실패한 제한 실행의 샘플이며 정상 모델 메모리 요구량/성능 보장이 아니다. 가중치/가상환경/진단 receipt는 ignored work에 보관하고 signed release나 current ready state를 발급하지 않았다.

Mac 원본 Git HEAD는 작업 중 다른 작업에 의해 변경됐다. 최초 import `33e3b8fb366a5d8f9cea0b93d387488e44fe5a0e`, 마지막 읽기 확인 `5a39fd28e38ceed2343f5a886ec2d0f457a89c94`. 원본 ClayFarm 14개 core 파일은 import 이후 변경되지 않았고 해당 경로 Git status는 비어 있었다. 이 작업은 원본 저장소에 쓰지 않았다.

이 저장소는 신규 `main` 브랜치이며 아직 commit/remote/push가 없다. 테스트 성공, 운영 배포, GPU 모델 실행 검증을 각각 별도로 기록한다.
