# ClayFarm 0.3.0.dev1 — 검증 보고서

검증일: 2026-09-12. 환경: **Linux x86_64, Python 3.13.5**.
이 보고서는 실제 로그와 결과 파일에 근거한다. 실제 사용자 Work/Git/Supabase/장비를 수정한 결과가 아니다.

## 결과

**79 tests passed / 0 failed / 0 skipped**. 최종 전체 실행 시간 로그: 27.16초.
`python -m pytest -q --junitxml=evidence/pytest.xml`로 실행했다.

| 항목 | 실행 결과 | 증거/한계 |
|---|---|---|
| 레지스트리 | 17개 모델, 39개 프로필, 11개 구간 참조 검사 통과 | 메모리 후보 ≠ 실제 모델 실행 |
| 장비 분류 | 4050/4070/Mac 및 메모리 예산 분기 시험 | NVIDIA/Apple 하드웨어는 fixture |
| 승인·ACL | 중복 신청/승인, 관리자 AAL2, 소유자 격리, 철회 시험 통과 | 실제 API+SQLite, 사람 Auth는 fixture |
| 장비 서명 | Ed25519 실제 서명/검증, 변조/replay/과거 nonce 거부 | 하드웨어 attestation은 아님 |
| 작업 복구 | lease 만료/재claim/과거 attempt 차단, 취소, single-slot 통과 | 실제 대규모 WAN·전원 차단 시험 아님 |
| 프로세스 | 자식 env의 민감 변수 제외, 실제 timeout 종료 통과 | OS sandbox 아님 |
| 산출물 | 실제 SVG 300바이트, WAV 33,644바이트 생성·업로드·다운로드 | 신경망 생성 아님; 제한된 UI source/DSP |
| Supabase Auth | OTP signup/login 분리, verify, 위조세션·service key 거부 등 | httpx mock 계약 시험; 실제 메일/Auth 미실행 |
| 릴리스 | 실제 Ed25519 서명, 변조/만료/rollback/경로/비고정 lock 거부 | 모델 가중치 다운로드·full TUF 미실행/미구현 |
| CLI | JSON 출력, noninteractive 입력 오류 반환 | 소스 subprocess 경로를 명시하여 시험 |
| Work 보조기 | Git root dry-run, 새 폴더 적용, 기존 파일 보존, 중복 적용 거부 | 임시 Git 저장소에서 실행; 사용자 저장소 아님 |
| 원본 유지 | legacy 소스 15개 byte-identical | evidence/legacy-source-integrity.json |
| legacy demo | 별도 실제 실행, task failures 빈 목록 | 원본 synthetic mock executor; GPU 아님 |
| wheel | 빌드 및 --no-index --no-deps 임시 target 설치/import 통과 | 기존 환경의 의존성 사용; clean online install 아님 |
| Bash 설치기 | bash -n 및 공백 경로 dry-run 통과 | 실제 새 환경 pip install 미검증 |
| macOS/Windows 서비스 | plist·XML 구조·명령 인자 시험 | 실제 두 OS의 설치/로그인 자동 시작 미실행 |

## 재현

```bash
python -m pytest -q
clayfarm demo --out ./new-demo-output --json
```

실제 demo 로그는 `evidence/demo-report.json`, 파일은 `evidence/asset.svg`, `evidence/asset.wav`다.
`demo-report` 내 runtime 경로는 이 실행 환경 경로일 뿐 사용자 Mac의 파일 경로가 아니다.

## 결함 발견 후 수정

초기 시험에서 `/sys/class/power_supply`가 없는 Linux의 배터리 probe 예외를 발견해 미확인 값으로 처리했다.
소스 설치 없이 CLI subprocess를 시험할 때 PYTHONPATH가 전달되지 않는 테스트 harness 문제도 수정한 뒤 전체 시험을 재실행했다.
테스트를 통과시키기 위해 인증·준비 상태 검사를 제거하지 않았다.

## 실패·미실행을 숨기지 않는 기록

- `uv pip compile --universal --generate-hashes ...`는 PyPI DNS 실패로 완료하지 못했다. 출력: `evidence/dependency-lock-attempt.log`.
- 전이 의존성 해시 lock을 만들어졌다고 주장하지 않는다. 원격 다운로드를 포함한 새 환경 설치는 검증되지 않았다.
- macOS Keychain/Windows Credential Locker, 실제 OTP·MFA·SMTP, PostgreSQL/Supabase private schema·RLS·Storage는 실장비/실서비스 검증 전이다.
- CUDA/MPS 이미지 어댑터 5개는 코드 구현만 완료했고 GPU 추론 미실행이다. MLX·대형 3D·리깅·모션 어댑터는 미구현이다.
- 자동 core self-update/canary rollout/full TUF/자동 neural-model 배포와 기존 cf_rpc의 인증·큐 bridge는 미구현이다.
- 외부 작업 결과의 미적 품질, 게임용 에셋 채택률, GPU 처리량/유휴율/토큰 절감률은 **근거없음 / 미측정**이다.

## 배포 전

`WORK_HANDOFF.md`와 `docs/IMPLEMENTATION_STATUS.md`의 미완료 범위를 먼저 확인한다.
이 패키지는 개인 enrollment를 포함하지 않는다. `evidence/sanitization.json`은 실제 원본 자격증명 값과 출력 파일의 일치 검사 결과다.
