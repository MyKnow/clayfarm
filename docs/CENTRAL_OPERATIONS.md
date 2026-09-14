# Central gateway operations

## 현재 적용 경계

기존 Supabase dispatcher를 확인한 뒤 작성한 마이그레이션과 gateway다. 2026-09-14 사용자 요청에 따라 운영 DB migration, MyKnow 홈서버 API 및 Resend OTP 메일 설정을 적용했다. 현재 접속 가능 여부와 실제 사용자 검증의 남은 조건은 [DEPLOYMENT_STATUS](DEPLOYMENT_STATUS.md)를 따른다. 첨부 문서 자체는 운영 변경 권한이 아니다.

기존 프로젝트 DB와 `clayfarm` bucket을 사용한다. 새 프로젝트/farm/노드용 Auth 계정을 만들지 않는다. `cf_control.jobs`는 원본 개발 모드 호환을 위해 존재할 수 있지만 중앙 모드의 submit/claim/조회에 사용하지 않는다.

## 적용 순서

1. 기존 dispatcher, RLS, jobs/tasks/attempts/workers/members, Storage 정책과 운영 Auth를 백업한다. 활성 lease와 FK 변경의 잠금 영향을 고려해 작업 시점과 lock timeout을 정한다.
2. 관리자 DB 연결에서 `control init`으로 private 메타데이터를 초기화한다. 실제 이메일 검증을 끝낸 Auth UUID로 `control bootstrap`을 수행한다. 첫 가입자가 자동 관리자가 되지 않는다.
3. `supabase/migrations/20260912101300_control_queue_bridge.sql`을 검토·적용한다. 기존 dispatcher body MD5가 `5f236654413ae934971d9a6e27c45a61`과 다르면 변경 전에 중단한다. 이 hash는 확인한 소스 버전을 구분하는 값이며 보안 서명이 아니다. 달라졌으면 최신 코드와 비교·병합한 새 migration을 만든다.
4. 관리자 연결에서 `control bind-farm --farm-id EXISTING_FARM_UUID`를 실행한다. 기존 cf_members가 있는 farm만 바인딩한다.
5. 서버 전용 로그인 역할에 `clayfarm_gateway` 멤버십을 부여한다. migration 소유자 연결과 런타임 연결을 분리한다. 런타임은 public 작업 테이블을 직접 갱신하지 않고 제한된 private 함수를 호출한다.
6. 서버 secret 관리 수단으로 `CLAYFARM_DATABASE_URL`, `CLAYFARM_FARM_ID`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_KEY`를 공급한다. 키를 소스·ZIP·로그에 넣지 않는다. 모델/Blender subprocess에도 SUPABASE_*와 CLAYFARM_* 환경값을 전달하지 않는다.
7. `clayfarm control serve`를 loopback에서 실행하고 HTTPS 프록시 뒤에 둔다. 기본값은 중앙 모드다. 별도 개발 큐가 필요할 때만 `--development-queue`를 명시한다.
8. 실제 OTP → AAL2 관리자 승인 → 새 키 등록 → 엔진 허용 → CUDA warm → 3D 작업 → Blender 여섯 뷰 → caller 다운로드·검토·승인을 수행한다. 기존 worker와 새 node가 같은 job을 중복 처리하지 않는지 확인한다.

Storage service key는 RLS를 우회한다. 따라서 gateway가 PostgreSQL 승인·소유자·lease를 검사하고 전송 중 관련 행 잠금을 유지한다. 노드에 키나 signed URL을 내려주지 않는다. [공식 Storage 접근 제어](https://supabase.com/docs/guides/storage/security/access-control).

## Storage와 복구

- 입력은 `farm/caller/job/inputs/sha256-name`이다. 새 caller는 자기 입력을 올리며 제출된 job의 입력을 변경할 수 없다.
- 출력은 `farm/node/task/attempt/sha256-name`이다. 현재 유효 임대에서만 쓰며, gateway가 저장한 hash/크기를 완료 manifest와 대조한다.
- 응답을 잃으면 동일 key/bytes로 재시도한다. 이미 저장됐으면 bytes를 비교한다. 완료 재시도는 동일 attempt와 전체 manifest일 때만 멱등 처리한다.
- 취소·임대 만료·노드 철회·소유자 정지는 이후 전송/완료를 차단한다. 서명은 method/path/query/body/time/nonce를 묶는다.
- 새 proxy는 최대 50 MiB 전체 객체 재시도다. byte-range/TUS 재개는 새 인증 proxy에 미구현이다. 기존 legacy TUS는 보존했다.
- 기존 Auth 멤버십/Storage 정책은 명시적 cutover 전 유지된다. 새 control grant 철회가 별도 legacy 계정까지 자동 철회하지 않는다. cutover 때 계정별 기존 권한을 함께 점검한다.
- 새 node가 이력에 들어간 뒤 Auth FK를 임의로 되돌리지 않는다. rollback은 코드 전환과 DB 복구를 구분하며 journal/outbox와 job/attempt ID를 보존한다.

## 재현과 미검증 항목

`python scripts/test_central.py --real-storage --blender /absolute/path/to/blender`는 실제 PostgreSQL 17과 Storage API v1.60.4를 사용한다. 사람 인증과 재구성 입력은 fixture이고, Blender 실행·Storage bytes는 실제다. [Supabase 공식 Docker 구성](https://github.com/supabase/supabase/blob/master/docker/docker-compose.yml)을 참고했다. hosted Storage와 버전이 같다는 주장은 하지 않는다.

운영 DB의 선택 스키마 backup/restore와 migration 보존 시험은 완료했다. 실제 이메일 수신·TOTP, 공개 TLS·요청 횟수 제한·운영 부하, Windows 새 CLI/운영 큐 end-to-end, 기존 계정 cutover는 별도 미검증 항목이다. fixture 통과로 이를 완료 처리하지 않는다.

## 실제 TripoSR 출력과 엔진별 메모리

Windows RTX 4050 Laptop에서 고정 TripoSR 모델의 CUDA 추론과 CPU mesh extraction을 온라인/네트워크 차단 오프라인으로 실행했다. 상세 수치는 `WINDOWS_HARDWARE_RESULT.json`에 있으며, 단일 입력 calibration 결과다. 새 제어 CLI와 운영 큐의 Windows end-to-end 성공을 뜻하지 않는다.

TripoSR 원본은 Z-up 좌표를 GLB로 직접 내보낸다. 재구성 경계에서 [고정 upstream의 공식 viewer 변환](https://github.com/VAST-AI-Research/TripoSR/blob/107cefdc244c39106fa830359024f6a2f1c78871/tsr/utils.py)의 Rx(-90°)·Ry(+90°), 즉 `(x,y,z) → (-y,z,-x)`를 scene 루트에 적용해 glTF Y-up으로 표준화한다. 바이너리 geometry/normal/material과 기존 node 변환은 보존한다. 새 Blender 노드는 기존 TripoSR parent 출력도 staging 파일에서 보정한다. 보정 marker로 중복 회전을 막고, SF3D·일반 입력·Blender revision/preview는 일괄 회전하지 않는다. 이전 실행 증거는 adapter 변경으로 무효화되므로 새 `node warm`을 수행한다. `hard_pass`는 크기·pivot·polygon 계약이며 upright·silhouette·미학적 승인을 보장하지 않는다. 카메라의 front 명칭과 생성물의 의미상 정면이 일치하는지는 실제 여섯 뷰에서 검토한다.

`execution.json`의 `engine_limits`는 엔진별 `min_free_vram_mb`와 `gpu_min_ram_mb`를 받는다. 예시는 `examples/triposr-calibration-limits.json`이며 기존 실행 설정에 병합할 값이다. `node configure`는 설정 전체를 교체하므로 예시만으로 기존 설정을 덮어쓰지 않는다. TripoSR 3840/8192 MiB는 이번 process GPU peak 약3157 MiB, Python OS peak RSS 약4262 MiB와 여유를 기준으로 정한 calibration 정책이다. 다양한 입력의 최대값이나 생산 보장값은 아니다.

새 worker는 엔진별 현재 여유를 heartbeat와 claim 직전에 검사한다. TripoSR에 낮은 기준을 지정해도 SF3D의 기본 VRAM 7000 MiB를 낮추지 않는다. RAM 미확인, 배터리 정책 위반, pause, GPU 과부하/고온에서는 CUDA capability를 광고하지 않는다. 예시는 실행 증거·준비 상태·관리자 승인을 발급하지 않는다.

이미지 model manager의 첫 CUDA calibration도 현재 free VRAM에서 512MiB를 뺀 예산을 runtime request로 전달한다. 자식 runtime은 모델 로드 전에 allocator 상한을 설정한다. host 여유 2GiB 감시는 별도로 유지한다. 정상 실행 기록이 있어도 현재 예산이 부족하면 운영 dispatch/ready를 허용하지 않는다.

SDXL은 [공식 fp16 variant와 model CPU offload 방식](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)을 고정 프로필에 명시했다. 해당 offload는 UNet 전체를 GPU로 옮기므로 더 작은 sequential offload와 동일하지 않다. 이번 RTX4050의 예산은 UNet tensor만으로도 부족해 설치 전 차단했고, Mac non-offload MPS도 같은 tensor 하한을 충족하지 못했다. 자세한 숫자는 `SDXL_PREFLIGHT.json`에 기록했으며 이 사전점검을 실행 성공/실패로 부풀리지 않는다.
