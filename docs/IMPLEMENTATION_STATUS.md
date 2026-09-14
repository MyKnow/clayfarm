# 구현 상태 — 2026-09-14 / 0.4.0.dev1 Work 통합

이 문서는 현재 저장소 상태다. 첨부 패키지 작성 당시 상태는 [IMPLEMENTATION_STATUS_UPSTREAM](IMPLEMENTATION_STATUS_UPSTREAM.md)에 보존했다. **운영 통합과 전체 모델 검증 완료를 선언하지 않는다.**

| 영역 | 현재 구현과 증거 | 남은 경계 |
|---|---|---|
| 저장소 | 첨부 SHA256SUMS 79개 확인, Mac 기존 소스 우선 반영, Windows/Mac 원본 15개가 동일 origin/dev revision과 일치. 사용방법·Unity 규칙·서버 실행 패키지를 포함한 로컬 main 최초 커밋 | GitHub Private 생성·push 완료. [배포 상태](DEPLOYMENT_STATUS.md) |
| 중앙 큐 | 새 승인 계정과 서명 노드가 기존 public.cf_jobs/tasks/attempts/workers와 동일 dispatcher 사용. 양방향 old/new claim, 동시 claim, lease/fencing, revocation 시험 | 운영 migration·기존 데이터 보존 및 실제 새 사용자 제출/기존 Windows 실행/새 Mac 서명 노드 처리/다운로드 확인 |
| 승인·인증 | 실제 관리자 이메일·OTP·Mac 키체인·공개 HTTPS·TOTP·AAL2 관리자 조회 및 Mac 노드 승인·서명 인증 성공. AAL1 관리자 접근 거부 확인 | MFA 등록 재개 및 한 명령 내 검증 경로 추가. 새 Mac 서명 노드 작업·일시 중지/재활성화 검증 완료. 영구 철회·Windows 새 CLI 전환은 미완료 |
| Storage | 실제 Storage API v1.60.4의 private bucket에서 bytes/hash/멱등 업로드/다운로드 확인. 입력·현재 attempt 출력으로 권한 제한 | hosted 사용자 입력·새 노드 attempt 출력·사용자 다운로드 bytes/hash 성공. lease 없는 노드 403 확인. byte-range/TUS 재개·운영 장애 검증은 미완료 |
| 3D 실행 | 기존 실행기를 새 노드 인증에 연결. Windows TripoSR 고정 소스/가중치 CUDA 추론·CPU mesh extraction 온라인/새 오프라인 실행 성공 | SF3D gated 접근 차단. Windows 새 CLI/운영 큐 end-to-end 미검증 |
| 축 계약 | 실제 생성 의자가 누워도 기존 hard_pass가 통과하는 결함 재현. 공식 viewer 변환을 적용한 exact executor로 Windows 재구성·process·6뷰·legacy 호환·CPU revision 통과 | 의미상 앞뒤와 색감은 caller 시각 검토 필요. hard_pass는 시각 승인 아님 |
| Unity 임포트 규칙 (2026-09-14) | ClayFarm FBX Medium 고정, 세 기능 미사용으로 명시 분류한 StaticMeshes만 BlendShapes/Rig/Animation 끄기. [적용 규칙](UNITY_IMPORT_POLICY.md), Mac Unity 6000.3.22f1 실제 임포트 8개 시나리오 통과 | 게임 프로젝트 설치, 실제 에셋 시각/로딩 품질 및 Windows Unity 검증은 별도 |
| CUDA 메모리 | RTX 4050 Laptop 6141MiB에서 TripoSR torch/PDH GPU·RSS/OS peak 측정. 엔진별 현재 메모리 capability/claim 검사 | 단일 입력 calibration. 생산 부하·다양한 입력 최대값 미검증 |
| Blender DAG | 실제 Mac Blender로 후처리·GLB/FBX·여섯 뷰·Storage·caller 결과 다운로드 성공 | 재구성 입력은 합성 fixture. neural 모델/미학 품질 증거가 아님 |
| 합성 결과 | mock ancestry 보존·승인/revision 승격 차단. 합성/기계검사실패는 diagnostic_candidates로 분리하고 ready에서 제외 | 악의적인 하드웨어 원격 attestation은 미구현 |
| Mac GPU | M5 Pro 24GB, PyTorch 2.14.0 MPS 및 MLX 0.32.2 GPU 실제 행렬 연산·OOM 후 재사용 확인 | tensor 성공은 모델 성공 아님 |
| SD-Turbo MPS | 고정 upstream commit의 실제 fp16 가중치 설치·hash 대조, 모델 로드/실행 3회 시도 | 현재 작업 부하와 MPS 예산에서 OOM. 마지막 적용 예산 916,570,112B. ready=false |
| 기타 이미지 | SD-Turbo CUDA 실제 생성·cold-load peak 측정·제한 OOM→메모리 회수→새 프로세스 동일 이미지 재생성 통과 | signed release/운영 ready 미발급 |
| SDXL | 고정 fp16 파일 메타데이터·UNet safetensors header 및 whole-model offload 구현 확인. CUDA/MPS 현재 예산보다 UNet tensor 하한이 커 설치 전 차단 | 실제 설치·forward·OOM 실행 아님. ready=false |
| MLX 모델 | 런타임 GPU 사용 가능 확인 | Flux/오디오 MLX 모델 어댑터 미구현, ready=false |
| 대형 3D·rigging·motion | 후보 레지스트리 보존, 미구현 실행 거부 | 실제 모델 구현·설치·실행 미완료 |
| 모델 준비 상태 | 환경 fingerprint·adapter/profile digest·artifact hash·메모리 증거 없거나 변경되면 광고/plan ready 차단 | 신경망 signed release 미발행 |
| 설치 | Mac 제어 계층 신규 가상환경 설치 및 해시 lock, Windows 제어 계층 lock 생성, Mac 모델 진단 lock | Windows 신규 환경 설치 미검증 |
| 복구 | task/attempt/outbox 보존, 현재 lease만 publish. Mac OOM 후 GPU 재사용. Windows 설치 빌드 복구 및 실제 CUDA 제한 OOM 후 메모리 회수·정상 모델 재실행 통과 | 운영 장애·장시간 부하·다중 입력의 자원 최대값 미검증 |
| 운영 전환 | 최신 dispatcher hash 불일치 시 변경 전 중단하는 migration, 전용 gateway 권한, 문서화. 운영 migration·홈서버 API·공개 TLS·DB 복원 시험 완료 | 실제 MFA·Mac 노드 승인 완료. 동일 큐 실제 작업 완료. 기존 legacy 계정 cutover·시각 품질·장애 검증 필요 |
| 홈서버 실행 패키지 (2026-09-14) | Linux amd64 서버 이미지와 wheel hash lock, loopback Compose, DB/farm/RPC readiness 검사. 홈서버 healthy·공개 HTTPS·실제 DB TLS/권한·hosted Storage 서버 읽기 확인 | 사용자/노드 전체 E2E는 별도 |

## CLI 버전·업데이트 (2026-09-14)

`src/clayfarm_control/version.py`를 버전의 단일 원천으로 두고 API health, CLI
`--version`, 작업의 bundled release ID와 패키지 metadata가 같은 값을 읽도록 했다.
기능 개선 릴리스는 signed wheel manifest(`control_release`)로 고정하며, 서버는
`/v1/updates/check`와 검증된 artifact 경로를 제공한다. CLI는 `update check`,
`update download`, 명시적인 `update apply --yes`를 제공하고 서명·플랫폼·크기·SHA-256·
wheel metadata를 모두 확인한다. 현재 저장소에는 update feed 코드와 생성 도구만 있으며,
운영 feed에 올릴 wheel과 서명키는 아직 발행하지 않았다. 따라서 이 변경으로 운영
업데이트가 이미 활성화됐다고 표시하지 않는다. 상세 절차는 [CLI_UPDATES](CLI_UPDATES.md)를 따른다.

## 로컬 Text-to-Sound 확장 (2026-09-14)

`sa3-small-music-*` BGM 프로필 3개와 기존 Stable Audio SFX 프로필을
등록했다. BGM은 `track_id`(`lobby`, `preparation`, `combat`, `result`)를
반드시 지정하고 SFX는 `event_id`·`variation_count`를 사용한다. 두 계약은
서로 다른 필드 집합으로 검증되며 로컬 제어 큐의 입력 경계를 공유한다.
기존 PostgreSQL 중앙 브리지는 여전히 3D task kind/capability만 허용하므로
오디오 중앙 큐 통합 완료로 표시하지 않는다.

현재 구현된 것은 표준 WAV 디코더, silence trim/peak normalize, clipping·RMS·
loop seam 보고서, waveform/spectrogram 미리보기, 그리고 Stable Audio 3
Python 어댑터의 실패 폐쇄 경로다. CPU/CUDA/MLX 모델 가중치·의존성 lock·
서명 release와 실제 장비 실행 증거가 없으므로 세 BGM 프로필과 SFX 모델은
모두 candidate이며 `ready=false`다. Stable Audio 어댑터가 실제 생성한
출력도 사람 청취 승인 전에는 Unity에 연결하지 않는다. 상세 계약과 명령은
[AUDIO_PIPELINE](AUDIO_PIPELINE.md)에 기록했다.

## 하나의 큐라는 의미

중앙 API에 승인된 계정은 기존 `public.cf_jobs`에 제출한다. 기존 워커가 그 작업을 claim할 수 있고, 새 노드도 기존 caller가 제출한 작업을 claim한다. 둘은 동일 task/attempt 상태를 본다. 중앙 모드에서는 개발용 `cf_control.jobs` 경로를 실행할 수 없다.

2026-09-14 운영 DB에 migration을 적용하고 MyKnow 홈서버에 gateway를 배포했다. 실제 Auth·새 CLI 제출·기존 Windows TripoSR·새 Mac 노드 Blender·Storage 결과 다운로드를 같은 운영 큐에서 확인했다. Windows 워커는 기존 인증이며 새 CLI 전환과 모델 전체 검증은 미완료다. 실제 legacy 결과 및 raw mesh revision의 의자 축 방향이 잘못돼 시각 승인하지 않았다. 자세한 작업 ID와 경계는 [배포 상태](DEPLOYMENT_STATUS.md)를 따른다.

## 하드웨어 판정

`candidate`, `installed_unverified`, 실제 실행 증거, 현재 메모리 admission을 구분한다. 합성 장비·fixture 출력·tensor 연산·패키지 설치만으로 모델 ready를 만들지 않는다. Mac 진단은 승인된 release가 아닌 별도 진단 상태로 저장했고, 성공 여부와 무관하게 모델 자동 활성화/신뢰키 발급을 하지 않는다.

SD-Turbo는 [공식 모델](https://huggingface.co/stabilityai/sd-turbo)의 fp16 variant를 사용했다. MPS CPU fallback을 비활성화하고 현재 가용 메모리에서 host 여유를 남기는 상한을 적용했다. [공식 MPS 안내](https://huggingface.co/docs/diffusers/optimization/mps).

현재 코드·검증 절차는 [CENTRAL_OPERATIONS](CENTRAL_OPERATIONS.md), 구체적인 테스트 결과는 [TEST_REPORT](../TEST_REPORT.md)를 참고한다.
