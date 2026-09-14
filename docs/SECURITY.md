# 신뢰 경계 및 운영 전 검토

- 이 개발 서버에는 공개 mock login이 없다. `demo.FixtureVerifier`는 in-process demo/test에서만 주입한다.
- Supabase `/user`를 통한 원격 검증이 먼저다. 검증되지 않은 JWT payload를 권한 근거로 쓰지 않는다.
- 사용자 수정 metadata는 ACL에 사용하지 않는다. 모든 관리 작업은 현재 DB role/status + AAL2를 확인한다.
- DB 연결 자격증명은 서버 전용이며, 일반 요청자/워커에 배포하지 않는다. 초기 bootstrap은 DB 운영자 전용 수동 단계다.
- OS keyring은 평문 fallback 없이 사용한다. 같은 OS 사용자/관리자/악성 코드에 대한 완전한 격리는 아니다.
- 장비 Ed25519 키는 nonce/timestamp/body에 서명한다. 승인 전·철회 후 claim을 허용하지 않는다. 공개키 회전 UX는 아직 없다.
- 워커가 보낸 GPU 목록·검증 수치는 원격 attestation이 아니다. 악성 승인 워커의 거짓 보고까지 방지했다고 주장하지 않는다.
- 자식 생성 프로세스에는 관리자 DB/메일/Auth 환경변수를 넘기지 않는다. 명시적 adapter만 실행한다.
- `process.py`는 취소/timeout/프로세스 그룹 정리이며 OS sandbox가 아니다. 사용자 계정 권한으로 실행된다.
- safetensors/config allowlist 및 고정 commit/hash를 사용한다. 신뢰키를 공격자가 바꾸면 안전하지 않으므로 별도 경로로 지문을 확인한다.
- signed recipe는 full TUF가 아니다. root rotation/delegation/snapshot 일관성/전체 freeze 방어와 검증된 core rollback은 후속 작업이다.
- 모델 설치용 venv·runtime를 분리하지만 설치 패키지를 신뢰하지 않아도 안전한 sandbox라고 주장하지 않는다.
- private PostgreSQL schema를 Data API에 노출하지 않는다. 운영용 least-privilege DB role·backup/migration advisor는 별도 검증한다.
- 외부 TLS proxy/rate limit·계정 abuse 대응·아티팩트 보존/용량 정책·모니터링을 적용하기 전 공개 운영하지 않는다.
- 개발 큐는 요청 body 17MiB, 아티팩트 16MiB 제한이다. 기존 Storage를 재사용하는 중앙 3D 모드는 요청 body 51MiB, 객체 50MiB 제한이며 byte-range/TUS 재개는 새 proxy에 미구현이다.
- SMTP dispatcher는 at-least-once라 crash 이후 중복 메일이 가능하다. 알림 발송 여부와 승인 처리 상태를 혼동하지 않는다.
- 키/계정 폐기는 이미 내려받은 파일을 회수하지 않는다. audit/registry/model data 보존정책을 별도 수립한다.
- 입력 ZIP의 개인 enrollment는 패키지에서 제외했다. 제공된 실제 비밀번호 등을 결과물에 반복하지 않는다.
