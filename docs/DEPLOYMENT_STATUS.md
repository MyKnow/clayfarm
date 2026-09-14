# 배포 상태 — 2026-09-14

사용자는 현재 변경사항을 포함한 비공개 GitHub 저장소 업로드와 MyKnow 홈서버 운영 적용을 요청했다. 아래 표는 실행으로 확인한 상태이며 준비 파일 존재를 운영 성공으로 간주하지 않는다.

| 항목 | 확인 상태 |
|---|---|
| GitHub 대상 | 연결된 사용자 MyKnow, 저장소 이름 clayfarm. 아직 생성·업로드 전 |
| GitHub 인증 | 연결 앱 조회 성공. CLI 및 저장소 생성 MCP 인증 오류. 사용자 재인증 대기 |
| 로컬 저장소 | main 최초 커밋에 사용방법·현재 통합 코드·Unity 규칙·서버 실행 패키지 포함. 원격 연결·push 전 |
| 운영 데이터 | 기존 ClayFarm Supabase 프로젝트 ACTIVE_HEALTHY, private clayfarm bucket |
| 기존 큐 | farm 1개, 멤버 12개. task 117 done / 16 cancelled, 진행 중 task 없음(사전 조회 시점) |
| 서버 코드 기준 | 기존 dispatcher body MD5 5f236654413ae934971d9a6e27c45a61, 통합 migration의 사전 조건과 일치 |
| 새 중앙 통합 | cf_control schema 및 새 gateway 배포 전. 기존 운영 큐/Storage 미변경 |
| API 호스트 | MyKnow 홈서버, x86_64 / Python 3.12.3. 관리자 SSH 성공, 작업 계정 nologin 및 sudo 비밀번호 요구로 배포 권한 확보 전 |
| 서비스 URL | 아직 발급·검증하지 않음 |
| 서버 실행 패키지 | Linux amd64 이미지 빌드, CLI 0.3.0.dev1, pip check, Compose 구성 검사 통과. 실제 Linux API/PostgreSQL smoke에서 ready exit 0, 비로그인 401, UID 10001, DB 장애 시 ready exit 1 |
| Unity 규칙 | 소스 포함, Mac Unity 실제 FBX 임포트 8개 시나리오 통과. 게임 프로젝트 설치는 별도 |

운영 적용 전 기존 데이터·DB 함수·권한·서비스 설정의 백업과 복원 경로를 확보한다. 적용 뒤에는 서버 상태, 실제 Auth와 Storage, 동일 작업 큐, 미승인/철회된 요청의 차단을 각각 검증한다. 실제 모델 ready 판정은 [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md)의 모델별 증거 경계를 유지한다.

로컬 서버 이미지 ID: `sha256:ee447d7ea2a03727d446fa389d5cf8ba6c72d242321e6d2ff16189502eeef113`. 이는 배포 준비 이미지이며 운영 배포 또는 레지스트리 업로드를 뜻하지 않는다. API smoke는 실제 Linux API/PostgreSQL을 사용했지만 Auth/Storage 설정은 합성이므로 hosted 로그인/Storage 성공 증거로 사용하지 않는다.
