# 테스트 보고 — Work 통합, 2026-09-12

첨부 패키지 작성 당시 결과는 [TEST_REPORT_UPSTREAM](docs/TEST_REPORT_UPSTREAM.md)에 보존했다.

## 검 휘두르기 절차적 SFX 후보 — 2026-09-14

- `$claude-worker` Opus 스냅샷에서 `procedural-sfx`의 `sword_swing` 검증·구현·문서 변경을 검토하고 원 저장소에 적용했다.
- 실제 CLI 경로로 `examples/sfx-sword-swing.json`을 실행했다. 48 kHz mono PCM16, 0.35초 후보, clipping 0, peak -1 dBFS, RMS -19.242 dBFS를 확인했다.
- 전체 회귀 실행: **177 passed, 2 skipped**. 기존 `beep`·`whoosh`·`impact` 출력은 변경 전과 바이트 동일하다.
- 이 결과는 `neural:false`인 절차적 후보다. Stable Audio 모델 실행, 중앙 오디오 큐, Unity 최종 청취 승인을 의미하지 않는다.

## CLI 버전·업데이트 — 2026-09-14

- `src/clayfarm_control/version.py`를 단일 버전 원천으로 만들고 pyproject metadata, CLI `--version`, API `/health`, bundled release ID가 `0.4.0.dev1`을 일치하게 광고하는지 확인했다.
- signed `control_release` manifest의 sequence·만료·신뢰키·플랫폼·artifact path·크기·SHA-256·wheel metadata 검증을 확인했다.
- FastAPI update feed의 `/v1/updates/check`와 `/v1/updates/artifacts/{release_id}`, TestClient를 통한 signed wheel 다운로드, 변조 artifact 거부를 `tests/test_updates.py`에서 확인했다.
- 회귀 실행: **162 passed, 2 skipped**. 중앙 PostgreSQL 검사는 환경변수 미설정으로 **20 skipped**했다. 현재 작업 환경의 `.venv/bin/python`에는 pip가 없어 실제 `update apply` 설치는 실행하지 않았으며, CLI는 이를 `update_installer_missing`으로 명시한다.
- 운영 update root에 wheel·manifest·서명키를 발행하지 않았으므로 운영 사용자가 이미 업데이트를 받는 상태라고 주장하지 않는다. 발행 절차는 [CLI_UPDATES](docs/CLI_UPDATES.md)에 기록했다.

## 로컬 Text-to-Sound 계약·어댑터 — 2026-09-14

- BGM `track_id`와 SFX `event_id`/`variation_count`의 분리 검증, Lobby·Preparation 등 허용 트랙, 범위·seed·알 수 없는 필드 거부를 `tests/test_audio_pipeline.py`에서 확인했다.
- PCM 16/24/32-bit 및 IEEE float32 WAV 디코드, silence trim, peak normalize, clipping/RMS/loop seam 보고서, waveform JSON·spectrogram SVG 산출물을 확인했다.
- Stable Audio 3 CPU 어댑터는 pinned snapshot·`model_config.json`·`model.safetensors`·실제 `stable_audio_3` 런타임이 없으면 `audio_model_not_cached`/`runtime_not_installed`로 실패한다. SFX 다중 variation은 bundle 계약 전까지 명시적으로 거부한다.
- 회귀 실행: **155 passed, 2 skipped** (실제 Blender가 필요한 두 검사는 환경 skip, Starlette/anyio 경고 1건). 현재 Mac 제어 venv에는 stable_audio_3, torch, torchaudio, mlx가 설치되어 있지 않아 실제 음원 생성·MPS/MLX·CUDA peak 측정은 수행하지 않았다.
- `sa3-small-music-{cpu,cuda,mlx}`를 레지스트리에 추가했지만 모델 revision/file hash, signed release, Windows CUDA 및 Mac MLX 실제 실행 증거가 없어 전부 `ready=false`다. PostgreSQL 중앙 브리지는 3D task kind/capability만 허용하므로 오디오 중앙 큐 통합 완료로 표시하지 않는다.

## 실제 MFA 복구·공개 인증 검증 — 2026-09-14

- 사용자 터미널에서 새 등록 및 현재 인증기 코드로 `mfa_verified` 성공. 실제 공개 HTTPS `/v1/me`의 admin·aal2, 관리자 요청 조회·Mac 노드 승인 성공을 확인했다. 미완료 등록 키는 검증 후 OS 저장소에서 제거됐다.
- 기존 422의 정확한 제공자 원인은 재현하지 못했다. 미완료 등록을 재사용하고, 명시한 `--restart`로만 새 설정을 요청하며, 검증된 인증기는 유지하도록 수정했다. `--verify-now`가 같은 상태 폴더에서 바로 코드를 검증한다.
- JSON·비대화형·리다이렉트 출력으로 등록 키가 나가지 않도록 실제 TTY를 요구한다. 알려진 MFA 오류만 정해진 안전한 문구로 안내하며 원문 제공자 오류를 노출하지 않는다.
- 신규 MFA 회귀 18개를 포함한 core·제어 계층·실제 Blender·journal 검사: **207 passed, 12 subtests passed**. 기존 Starlette/anyio 사용 중단 경고 1건. 로그: ignored `work/publish-preflight-20260914/mfa-regression.log`.
- Mac 키체인 잠금 해제 후 실제 OTP 세션 저장·원격 검증 성공. 공개 TLS 1.3·정상 인증서 검증·health 200 성공. 인증서 발급 대기와 키체인 잠금 상태는 아래의 과거 기록이다.
- 새 Mac 노드에 Blender만 허용한 뒤 실제 Ed25519 인증·기존 중앙 heartbeat 성공. 실행 lease가 없는 노드의 입력 Storage 읽기 403, 비로그인 읽기 401 확인. 절차용 Blender 자가 점검을 AI 실행 증거로 승격하지 않는다.

- 수정 코드 `4a1cc08ef7a4319d9b48ef003fdcaff3ae8ef6d1`의 Private GitHub push·원격 SHA 일치. 홈서버 이미지 빌드·pip check·신규 MFA 옵션 포함·Compose 검증 후 배포, healthy 확인. 배포 후 실제 AAL2 관리자·서명 노드·동일 큐 완료 결과·Storage bytes/hash 유지, 비로그인 401, 기존 HTTPS 200·Caddy 재시작 0회 확인. 배포 대상 소스 Gitleaks 노출 없음. 자동 CI는 미구성이다.

## 실제 운영 큐·노드 Storage — 2026-09-14

- 새 CLI 가입·실제 OTP·TOTP·관리자 지정·Mac 노드 승인 이후, 기존 `public.cf_jobs/cf_tasks`에 실제 TripoSR 작업 1개와 CPU revision 2개를 제출했다. **22개 task 모두 done**. 원본 job `2402105a-649b-4c07-ae77-9819e43c27e7`, 새 노드 실행 revision `776428d5-af7d-4bce-be4a-4f0567ab1151`.
- 원본 재구성은 기존 Windows 워커에서 TripoSR source `107cefdc244c39106fa830359024f6a2f1c78871`, model `5b521936b01fbe1890f6f9baed0254ab6351c04a`, mock=false. 현재 워커가 보고한 장비는 RTX 4070 Laptop이며 이번 운영 결과에는 별도 GPU peak 측정이 없다. 기존 4050 진단 수치를 대입하지 않는다.
- 새 Mac 노드의 6개 출력 객체 375,833 bytes를 gateway가 검증해 기록했다. 새 Mac Ed25519 노드는 revision의 Blender process(1.825초)와 preview 3개를 완료했다. 나머지 세 preview는 기존 Windows 워커가 같은 큐에서 완료했다. Mac Blender 5.2.1 LTS, 실제 mesh 4,850 triangles, GLB/FBX/metrics 및 6뷰 다운로드 해시 확인. 노드에는 사람 토큰·서비스 키를 전달하지 않았다.
- 입력 업로드·유효 lease의 새 노드 출력 업로드·사용자 다운로드 성공. lease 없는 노드 입력 읽기 403, 비로그인 읽기 401. paused 노드 claim 403, active 복원 및 새 프로세스 재연결 성공. 영구 철회·운영 네트워크 장애 시험은 미완료다.
- 실제 6뷰를 확인하니 원본 및 raw mesh revision에 의자 축 방향 문제가 남아 있었다. 기계 검사 hard_pass는 시각 승인이 아니므로 job 승인과 모델 release/ready 발급을 하지 않았다. 기존 Windows 0.2.2 실행기 전환 및 raw mesh 좌표 계약 전파는 남아 있다.
- 실행·다운로드·권한 receipt는 ignored `work/publish-preflight-20260914/hosted-e2e-chair/`에 보관했다. Windows 신규 CLI/노드 인증 설치 증거와 별개다.

## 인증 저장소 복구 — 2026-09-14

- 실제 사용자 OTP 검증 성공과 이메일 확인 시각을 Supabase에서 확인했다. 해당 검증 계정을 최초 관리자로 지정하고 감사 기록을 남겼다. TOTP·관리자 API 검증은 아직 완료 전이다.
- Mac의 기본 login 키체인은 unlocked=false / writable=false이며, 실제 keyring 쓰기가 OSStatus -25308로 실패했다. 이메일 코드 오류와 구분한다.
- 신규 회귀 검사에서 변경 전 10개 실패를 확인했다. 저장소 잠금 시 메일 발송·코드 입력·검증 중단, 기존 세션/노드 키 보존, 임시 항목 정리, backend 세부 오류 미노출, 성공 시 세션 저장을 검증했다. 관련 검사 27 passed.
- 기존 core·제어 계층·실제 Blender·journal 포함 회귀: **189 passed, 12 subtests passed**. 이전 중앙 PostgreSQL/Storage 및 실장비 모델 검사와 합산하지 않는다. 로그는 ignored `work/publish-preflight-20260914/vault-regression.log`다.
- 실제 Mac의 `auth check-vault`도 메일 요청 없이 vault_locked를 반환했다. 본인 키체인 잠금 해제 후 실제 저장 성공 확인은 남아 있다.
- 수정 코드 d9841324d40c110e6de3caa7bb2622a3f509cc5a의 GitHub push 후 홈서버에서 이미지 빌드·pip check·신규 CLI 명령 포함을 검증하고 갱신했다. API healthy이며 이전 이미지·설정·데이터 볼륨을 보존했다. 신규 변경 파일의 Gitleaks 검사에서 노출 없음.

## 운영 적용 검증 — 2026-09-14

- GitHub `MyKnow/clayfarm` Private 확인, main의 첫 코드 SHA `d6192476b1b0455d49f2baffd1490fb9b87ce7ed` push 및 원격 일치. 자동 CI는 미구성이다.
- 운영 DB를 별도 PostgreSQL 17에 복원하고 동일 중앙 bridge migration을 적용했다. 기존 8개 테이블 행 수·내용 해시 유지. Storage 파일 본문까지 복원한 재해 복구 시험은 아니다.
- 운영 중앙 migration `20260914041144` 적용. 기존 job/task/attempt/member/Storage 내용은 보존했고 기존 워커의 heartbeat·Auth 갱신은 계속 진행했다.
- 홈서버에서 해당 코드 SHA로 Linux amd64 이미지 빌드, CLI version·pip check 성공. `clayfarm-api-1` healthy, 같은 `public.cf_jobs/cf_tasks` 사용 및 `parallel_queue_enabled=false`.
- 전용 DB 역할과 Supabase CA의 verify-full TLS 연결, 작업 테이블 직접 INSERT 및 farm 바인딩 직접 UPDATE 거부 확인. 비로그인 사용자·관리자 API 401, 공개 config에는 publishable key만 포함한다.
- API 컨테이너에서 기존 private Storage 객체 1,836 bytes 읽기 성공. 사용자·노드별 Storage 권한 검증을 대신하지 않는다.
- 기존 Caddy 설정을 보존하고 새 호스트만 추가, 실제 사용 이미지로 설정 검증 후 reload. 기존 HTTPS 응답 200과 Caddy 재시작 0회 유지. ClayFarm 인증서는 DNS 제공 서버 간 불일치로 발급 대기다.
- Resend SMTP와 8자리 OTP 템플릿 적용. 가입 429의 잔존 기본 발송 한도(2회/시간)를 30회/시간으로 수정하고 재발송 간격 60초 유지. 실제 본인 이메일 검증·TOTP·새 노드·Windows CUDA·전체 큐/Storage 흐름은 남아 있다.
- 배포 파일 추가 후 packaging 검사 6개 통과. 이전 단위·중앙·실장비 결과와 운영 증거를 합산하지 않는다. 자세한 현재 상태는 [DEPLOYMENT_STATUS](docs/DEPLOYMENT_STATUS.md)에 기록한다.

## 추가 검증 — Private 업로드·홈서버 배포 준비, 2026-09-14

- 기존 core·제어 계층·실제 Blender·journal 회귀: **173 passed, 12 subtests passed**.
- 실제 PostgreSQL 17·Supabase Storage API·Blender 중앙 통합: **20 passed**. 사람 인증과 재구성 입력은 fixture다.
- 서버 준비 상태·배포 파일 포함 검사: **11 passed**(신규 healthcheck 5개, 기존 packaging 6개).
- Linux amd64 서버 이미지 빌드, CLI version, `pip check`, Compose 구성 검사 통과. Python 3.12 서버 wheel 33개 SHA256 고정.
- 읽기 전용 루트·UID 10001·전용 볼륨으로 실제 Linux API와 PostgreSQL 연결 시험. 동일 중앙 큐 health, 준비 상태 exit 0, 비로그인 401, DB 종료 후 준비 상태 exit 1 및 비밀 미출력 확인. Auth/Storage 주소는 fixture이므로 hosted E2E는 아니다.
- Gitleaks v8.18.4로 업로드 대상 소스만 별도 복사해 검사: **no leaks found**. 가상환경·모델·작업 저널·로그·서버 환경 파일은 업로드 대상에서 제외했다.
- 로컬 기록: ignored `work/publish-preflight-20260914/`. 아래 준비 시험 당시에는 운영 상태를 읽기만 했다. 이후 운영 변경·GitHub 업로드 결과는 위 운영 적용 검증에 구분해 기록했다.

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

2026-09-12 통합 시험 당시에는 신규 `main` 브랜치에 commit/remote/push가 없었다. 이후 업로드 상태는 위 운영 적용 검증을 따른다. 테스트 성공, 운영 배포, GPU 모델 실행 검증을 각각 별도로 기록한다.
