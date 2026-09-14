# 배포 상태 — 2026-09-14

[GitHub Private 저장소](https://github.com/MyKnow/clayfarm)에 코드와 사용방법을 업로드했고 MyKnow 홈서버에서 중앙 API를 가동했다. **API 가동, 공개 HTTPS, 실제 계정·노드의 전체 작업 성공은 별도 검증이다.**

| 항목 | 확인 상태 |
|---|---|
| GitHub | MyKnow/clayfarm, Private, main. 첫 코드 커밋 d6192476b1b0455d49f2baffd1490fb9b87ce7ed 업로드 및 원격 SHA 일치 |
| API 호스트 | MyKnow 홈서버. clayfarm-api-1 healthy, UID 10001, 읽기 전용 루트, 127.0.0.1:8765 |
| API 코드·이미지 | 키체인 사전 점검 수정 d9841324d40c110e6de3caa7bb2622a3f509cc5a로 갱신. 이미지 ID sha256:49383f8a2447e2eafd9edf157bb138c4736052633c82f63c0a557d6728df1435. 2026-09-14 04:49 UTC 시작, healthy |
| 운영 데이터 | 기존 ClayFarm Supabase 프로젝트와 private clayfarm bucket 유지 |
| 중앙 DB 통합 | cf_control 초기화 후 clayfarm_control_queue_bridge 적용. 운영 migration 이력 20260914041144 |
| 동일 큐 | 기존 farm에 바인딩. health의 queue_backend=public.cf_jobs/cf_tasks, parallel_queue_enabled=false |
| 기존 데이터 보존 | job 17 / task 133 / attempt 117 / member 12 / Storage 객체 정보 201개 유지. 작업·실행 이력·멤버·Storage 내용 해시 일치 |
| 기존 워커 활동 | 계속 실행 중인 기존 워커의 last_seen·telemetry와 Auth updated_at은 정상 갱신됨. 해당 갱신을 덮어쓰지 않음 |
| 서버 DB 권한 | 전용 clayfarm_api 역할. superuser/BYPASSRLS/DB 생성/역할 생성 불가, 작업 테이블 직접 INSERT 및 farm_binding UPDATE 불가 |
| DB TLS | Supabase 공식 CA로 verify-full 연결. 인증서와 호스트 이름 검증 성공 |
| HTTPS | clayfarm.myknow.xyz 호스트를 기존 Caddy에 추가. 기존 호스트 보존, SIGUSR1 reload 성공, 재시작 없음. DNS 서버 간 반영 차이로 인증서 발급 재시도 중 |
| 실제 접속 주소 | https://clayfarm.myknow.xyz — 공개 TLS 검증 완료 전. 현재는 서버 내부 health만 성공 |
| 이메일 | 기존 Resend의 ClayFarm <clayfarm@ssartnership.myknow.xyz> 사용, 8자리 OTP 검증 성공. 발송 한도 30회/시간·재발송 간격 60초. Mac 키체인 잠금으로 세션 저장 실패, 잠금 해제 후 새 로그인 필요 |
| 최초 관리자 | 사용자가 지정한 myknow000@gmail.com의 실제 이메일 검증을 확인하고 첫 admin 지정 및 감사 기록 완료. TOTP와 관리자 경로 검증은 남아 있음 |
| Hosted Storage | API 컨테이너에서 기존 private 객체 1,836 bytes 읽기 성공. 서버 키 연결 증거이며 사용자·노드 권한 E2E는 별도 |
| 비로그인 접근 | 사용자 정보와 관리자 요청 API 401. 공개 config에는 publishable key만 포함 |
| Unity | FBX Medium 고정 및 StaticMeshes 조건부 규칙 포함. Mac Unity 실제 임포트 8개 시나리오 통과 |

CI 자동 실행은 아직 구성하지 않았다. Supabase 보안 진단에서 DB/RLS 오류는 없었고, 기존 비밀번호 유출 검사 비활성 경고가 남아 있다([공식 설명](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)).

## 백업과 복원 확인

운영 public·clayfarm_private·auth·storage·supabase_migrations 스키마/데이터, 역할, HTTPS 설정과 Auth 설정을 백업했다. DB dump SHA256: 5610920e30d10b1628a70927ca4780b910e3b63102e1fef36edf8aec24e11e6d.

별도 PostgreSQL에 복원한 뒤 같은 통합 migration을 실행하여 기존 8개 테이블의 행과 내용 해시가 변하지 않음을 확인했다. 복원 시험에서는 소유자를 정규화했고, Supabase 관리 플랫폼과 Storage 파일 본문까지 복원한 재해 복구 시험은 아니다. 운영 Storage 파일은 변경하지 않았다.

서버 백업: /srv/backups/clayfarm/preflight-20260914/ (root 전용). 서버 비밀 설정: /etc/myknow/secrets/clayfarm.env (root, 0600). 현재 실행 환경은 /opt/clayfarm/config-vault-20260914/deploy.env이며 해당 코드 release의 main·edge·TLS Compose 세 파일을 함께 사용한다. 이전 d619247 이미지와 /opt/clayfarm/config-candidate-20260914/ 설정도 복구용으로 보존했다. down -v나 큐 초기화를 사용하지 않는다.

## 남은 검증

공개 DNS·TLS, Mac 키체인 잠금 해제 후 새 로그인·TOTP, 관리자 승인·새 노드 등록·Windows CUDA 작업·동일 큐 결과와 Storage 권한·철회·재시작을 하나의 실제 흐름으로 검증해야 한다. 기존 모델별 ready 경계는 [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md)를 따른다. 설치·모의 실행·서버 가동만으로 모델 ready나 전체 통합 완료를 선언하지 않는다.
