# 배포 상태 — 2026-09-14

[GitHub Private 저장소](https://github.com/MyKnow/clayfarm)에 코드와 사용방법을 업로드했고 MyKnow 홈서버의 중앙 API를 `v0.4.0.dev2`로 교체했다. **API 가동, 공개 HTTPS, 실제 계정·노드의 전체 작업 성공은 별도 검증이다.**

| 항목 | 확인 상태 |
|---|---|
| GitHub | MyKnow/clayfarm, Private, main. `v0.4.0.dev2` 코드 커밋 `dc120e9`와 태그를 원격에 업로드하고 SHA 일치 확인 |
| API 호스트 | MyKnow 홈서버. clayfarm-api-1 healthy, UID 10001, 읽기 전용 루트, 127.0.0.1:8765 |
| API 코드·이미지 | `dc120e9` (`v0.4.0.dev2`)를 `/opt/clayfarm/releases/dc120e9`에 배치해 빌드·교체했다. 이미지 ID `sha256:66e4f02c0a4caf70a9224147b95bbb01644df631a434429359671abeb1b66500`. 컨테이너 `clayfarm-api-1`은 2026-09-14 23:35 KST 기준 restart 0·healthy이며, 컨테이너 CLI·공개 `/health`가 모두 `0.4.0.dev2`를 보고한다. |
| 운영 데이터 | 기존 ClayFarm Supabase 프로젝트와 private clayfarm bucket 유지 |
| 중앙 DB 통합 | cf_control 초기화 후 clayfarm_control_queue_bridge 적용. 운영 migration 이력 20260914041144 |
| 동일 큐 | 기존 farm에 바인딩. health의 queue_backend=public.cf_jobs/cf_tasks, parallel_queue_enabled=false |
| 기존 데이터 보존 | migration 시점 job 17 / task 133 / attempt 117 / member 12 / Storage 객체 정보 201개 유지. 작업·실행 이력·멤버·Storage 내용 해시 일치 |
| 기존 워커 활동 | 계속 실행 중인 기존 워커의 last_seen·telemetry와 Auth updated_at은 정상 갱신됨. 해당 갱신을 덮어쓰지 않음 |
| 서버 DB 권한 | 전용 clayfarm_api 역할. superuser/BYPASSRLS/DB 생성/역할 생성 불가, 작업 테이블 직접 INSERT 및 farm_binding UPDATE 불가 |
| DB TLS | Supabase 공식 CA로 verify-full 연결. 인증서와 호스트 이름 검증 성공 |
| HTTPS | DNS 권한 서버 응답 일치 후 Let's Encrypt 인증서 발급 성공. 일반 접속에서 TLS 1.3·인증서 이름 검증·health 200. 기존 HTTPS 200 및 Caddy 재시작 0회 유지 |
| 실제 접속 주소 | https://clayfarm.myknow.xyz — CLI용 API. 사용자용 웹 UI는 아직 없으며 추후 작업 |
| 이메일 | 기존 Resend의 ClayFarm <clayfarm@ssartnership.myknow.xyz> 사용, 8자리 OTP 검증 성공. 발송 한도 30회/시간·재발송 간격 60초. Mac 키체인 잠금 해제 후 실제 로그인 세션 저장·원격 검증 성공 |
| 최초 관리자 | 사용자가 지정한 myknow000@gmail.com의 실제 이메일 검증을 확인하고 첫 admin 지정 및 감사 기록 완료. 실제 TOTP와 AAL2 관리자 요청 조회·Mac 노드 승인 성공 |
| Hosted Storage | API 컨테이너에서 기존 private 객체 1,836 bytes 읽기 성공. 이후 새 사용자 입력 업로드·새 서명 노드의 attempt 결과 업로드·사용자 결과 다운로드도 실제 bytes/hash로 확인 |
| 비로그인 접근 | 사용자 정보와 관리자 요청 API 401. 공개 config에는 publishable key만 포함 |
| 실제 로그인 권한 | 공개 HTTPS에서 관리자 계정 /v1/me 200·admin 역할 확인. AAL1의 관리자 요청 조회 403 mfa_required, TOTP 후 AAL2 관리자 경로 200. 미등록 장비 경로 401 unknown_device |
| Mac 노드 | 실제 신청·AAL2 승인·Ed25519 노드 인증·중앙 heartbeat 성공. Blender만 허용, 실제 5.2.1 자가 점검 통과. AI 모델 ready와 별개 |
| Unity | FBX Medium 고정 및 StaticMeshes 조건부 규칙 포함. Mac Unity 실제 임포트 8개 시나리오 통과 |
| CLI 업데이트 | 운영 API가 signed manifest `control-0-4-0-dev2-1-any-any`와 wheel(`e684c0e1a31d8dc2863718b947d4ebc7aca155e376e8a0d4229ef7520ab21c5a`, 138326 bytes)를 제공한다. 공개키 지문은 `f6788c70db6ec16537f7fdc116a98dbb7fe18a22a75854dc1fe3630ede6427e8`; Mac CLI에서 서명·hash 검증 후 download staging을 완료했다. 현재 버전이 동일하므로 CLI 결과의 `update_available=false`는 정상이다. |

CI 자동 실행은 아직 구성하지 않았다. Supabase 보안 진단에서 DB/RLS 오류는 없었고, 기존 비밀번호 유출 검사 비활성 경고가 남아 있다([공식 설명](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)).

## 백업과 복원 확인

운영 public·clayfarm_private·auth·storage·supabase_migrations 스키마/데이터, 역할, HTTPS 설정과 Auth 설정을 백업했다. DB dump SHA256: 5610920e30d10b1628a70927ca4780b910e3b63102e1fef36edf8aec24e11e6d.

별도 PostgreSQL에 복원한 뒤 같은 통합 migration을 실행하여 기존 8개 테이블의 행과 내용 해시가 변하지 않음을 확인했다. 복원 시험에서는 소유자를 정규화했고, Supabase 관리 플랫폼과 Storage 파일 본문까지 복원한 재해 복구 시험은 아니다. 기존 운영 Storage 파일은 보존했다. 이후 실제 작업 검증에서 새 입력·결과 객체를 추가했다.

서버 백업: /srv/backups/clayfarm/preflight-20260914/ (root 전용) 및 이번 교체의 컨테이너 메타데이터 `/srv/backups/clayfarm/pre-deploy-20260914-dev2/`. 서버 비밀 설정: /etc/myknow/secrets/clayfarm.env (root, 0600). 현재 실행 환경은 `/opt/clayfarm/config-mfa-20260914/deploy.env`와 `/opt/clayfarm/releases/dc120e9/deploy/`의 main·edge·TLS Compose 세 파일이다. 이전 `1f7cb52`, d984132 이미지와 `/opt/clayfarm/config-vault-20260914/`, 최초 d619247 이미지와 `/opt/clayfarm/config-candidate-20260914/` 설정도 복구용으로 보존했다. down -v나 큐 초기화를 사용하지 않는다.

## 실제 동일 큐·Storage 검증

실제 OTP·TOTP로 로그인한 관리자가 새 CLI로 제출한 작업 `2402105a-649b-4c07-ae77-9819e43c27e7`을 기존 Windows TripoSR/Blender 워커가 처리했다. 합성 입력 없이 공식 의자 이미지에서 재구성했고, GLB/FBX/6뷰를 공개 API를 통해 내려받아 해시를 확인했다.

같은 재구성 결과의 CPU revision `776428d5-af7d-4bce-be4a-4f0567ab1151`에서 새 Mac 서명 노드가 process와 preview 3개, 기존 Windows 워커가 나머지 preview 3개를 완료했다. 첫 revision은 기존 워커가 먼저 claim했다. 세 작업 22개 task가 기존 `public.cf_tasks`에서 모두 완료됐고, 별도 큐를 만들지 않았다. Mac 워커에는 사람 토큰·서비스 키를 전달하지 않았다.

Mac 노드를 paused로 바꾸면 claim 403, active 복원 후 새 프로세스가 정상 연결했다. lease 없는 노드의 입력 Storage 읽기 403, 비로그인 401을 확인했다. 실제 영구 철회·네트워크 장애·만료 lease 시험까지 완료한 것은 아니다.

원본 Windows 결과와 raw mesh revision 모두 미리보기에서 의자 축 방향 문제가 남아 있다. 기계 검사는 통과했으나 시각 승인은 하지 않았고 job은 approved로 바꾸지 않았다. 현재 Windows 워커는 legacy 0.2.2 인증을 사용한다. 새 Windows CLI 설치·인증 전환 및 결과 축 보정 전파는 미완료다.

## 남은 검증

실제 TOTP·관리자 승인·새 Mac 노드 인증을 확인했다. 같은 운영 큐의 실제 Windows 재구성·새 Mac 노드 후처리·Storage 다운로드까지 검증했다. Windows 새 CLI 전환, 영구 철회·장애 복구, 결과 축 방향 및 모델별 미완료 항목은 남아 있다. 기존 모델별 ready 경계는 [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md)를 따른다. 설치·모의 실행·서버 가동만으로 모델 ready나 전체 통합 완료를 선언하지 않는다.
