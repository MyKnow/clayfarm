# 구현 상태 — 2026-09-12 / 0.3.0.dev1

원본 v0.2.2 + 별도 관리 계층의 개발 패키지다. 전체 요구사항 완료판이 아니다.

| 영역 | 구현 | 이번에 검증한 범위 | 남은 작업 |
|---|---|---|---|
| CLI | setup, auth, access, node, admin, catalog, models, trust, releases, notify, jobs, service, control, demo, doctor, legacy | Python CLI 파싱/출력·일부 subprocess | 전체 실사용 UX·OS별 통합 시험 |
| 가입/로그인 | Supabase 이메일 OTP, refresh, user 조회, logout | Mock HTTP 계약 + API 인증 경계 | 실제 프로젝트/SMTP/이메일 세션 |
| MFA | TOTP 등록/검증; 관리 API AAL2 검사 | fixture aal1 거부/aal2 통과 | 실제 인증 앱·계정 관리/복구 |
| 계정 운영 | 초기 관리자 bootstrap, 회원 상태/권한 조정, 로컬 세션 철회 | 실제 SQLite 상태 변화 | 일반 계정 삭제·이메일 변경·전체 세션 관리·관리자 위임 UI/CLI |
| 신청/승인 | 멱등 신청·승인/거절·ACL·감사 이벤트 | 실제 API/트랜잭션 | 실제 기존 운영 DB 마이그레이션 |
| 노드 인증 | 로컬 생성 Ed25519 키, 승인된 공개키, timestamp/nonce/body 서명 | 위조/재전송/미승인/철회 차단 | 키 분실·회전·운영 복구 절차, 하드웨어 원격 attestation 없음 |
| 중앙 DB | SQLite 및 private cf_control PostgreSQL 경로 | SQLite만 실제 실행 | PostgreSQL migration 및 권한 회귀/백업 검증 |
| 알림 | 내장 inbox, CLI watch, STARTTLS SMTP dispatcher | DB 이벤트와 조회 | SMTP 실제 전송, OS toast·웹 push, 상주 알림 전용 서비스 |
| 장비 분류 | CUDA device별 메모리, unified 구분, RAM, 배터리, 선택 Python MPS/MLX 탐지 | Linux 실제 probe + 4050/4070/Mac 모의 장비 | NVIDIA/Apple 실물 탐지·권장 working-set 별도 정밀 측정 |
| 레지스트리 | 17모델·39프로필·11구간, 에셋별 계획 | 참조/밴드/준비 상태 테스트 | 새 registry 원격 서명 배포/호환성 협상 |
| CPU 생성 | 제한된 SVG UI source, DSP beep/impact/whoosh WAV | 실제 생성·파일 형식·hash·E2E | 완성형 UI/복잡한 SFX 품질 보증 아님 |
| GPU 이미지 | SD-Turbo CUDA/MPS, SDXL CUDA/lowmem-CUDA/MPS = 5프로필 | 입력 계약·실행 분기 코드 | 가중치/공식 lock recipe/실제 CUDA·MPS 실행 |
| MLX | 후보 메타데이터 및 탐지 | 계획 게이트만 | MFLUX/오디오 MLX 실제 어댑터 미구현 |
| 3D | 기존 SF3D/TripoSR/Blender 코드를 그대로 보존 | legacy 로컬 demo만 별도 확인 대상 | 신규 인증/큐로 기존 3D worker 통합; Mac 3D GPU 이식 |
| 리깅·모션·VFX | 레지스트리 후보 | 미구현 실행 거부 | 실제 UniRig/HY-Motion/파티클·베이크 어댑터 |
| 모델 설치 | signed recipe, commit/hash pin, isolated venv, license/download opt-in | 서명/rollback/path/lock validation | 실제 대형 모델 설치, 다운로드 중단/복구의 현장 시험 |
| 모델 승격 | pending→실제 검증→current, 이전 state 보존 | CPU 실제 경로 | GPU OOM/메모리 측정 정확도, 전체 임의 release rollback |
| 작업 실행 | pinned profile/release, 단일 slot, lease renew, attempt fencing, outbox | 실제 CPU E2E + 실패 주입 시험 | 전송 byte-range 재개/유휴 GPU 최적화/대규모 부하 |
| 릴리스 | 관리자+release-manager, 고정 신뢰키의 서명·만료·sequence 검사 | 변조/만료/rollback 거부 | full TUF/root rotation, core self-update, canary rollout, 자동 전 노드 배포 |
| 설치/자동 시작 | Bash/PowerShell 설치기, launchd/Task Scheduler template | Bash 구문, plist/XML 생성 | Python 없는 장비 bootstrap, 실제 설치·OS 서비스 등록 |
| 웹 | 동일 API를 쓸 수 있는 서버만 | API 시험 | 웹 UI 미구현 |

## 프로필 지원을 표현하는 규칙

- 레지스트리에 있음 = 후보. 어댑터 없음이면 `adapter_not_implemented`.
- 실행 어댑터가 있음 ≠ 모델 설치됨 ≠ 실제 실행 검증됨.
- 현재 새 실행 계층: 2 CPU + 5 이미지 GPU 프로필에 실행 코드. 총 7개.
- CPU 두 프로필은 2개의 제한된 절차적 생성기다. 17개 AI 모델을 구현했다고 표현하지 않는다.
- Apple Silicon은 계획·MPS 이미지 adapter에서 실제 GPU 경로를 갖지만, Mac GPU 시험은 미실행.
- 4050/4070/M5 Pro의 성능·품질·대형 모델 가용성은 **근거없음 / 실장비 미검증**.

## 기존 큐와의 경계

새 `jobs` API는 개발 단계의 별도 큐다. 기존 Supabase `cf_rpc`, `cf_members`, 기존 password enrollment와 자동 연결하지 않는다.
원본 worker ZIP에는 현재 운영 서버 전체 소스와 SQL migration 내역이 없으므로 기존 schema를 추측해 변경하지 않았다.
원본 코드/상태를 남겨 둔 채 명시적 migration adapter를 작성하고 실제 3D 작업을 끝까지 검증해야 한다.
