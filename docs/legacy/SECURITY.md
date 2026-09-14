# 보안 범위와 운영 기준

1. 관리자 secret/service_role은 `admin-init` 터미널 입력에만 사용합니다. 등록 파일에는 publishable key와 노드별 Auth 계정이 들어갑니다. 노드는 secret key를 인자로 받은 경우 거부합니다.
2. 등록 파일은 일회용 초대 코드가 아닙니다. 노드별 장기 비밀번호가 들어 있습니다. 파일을 채팅, 공개 GitHub, 프로젝트 에셋 폴더에 넣지 마세요. 안전하게 전송한 후 복사본을 삭제하고 장비 디스크 암호화를 사용하세요.
3. 공개 테이블에 RLS를 켜고 일반 사용자는 read-only로 둡니다. 쓰기는 authenticated public invoker wrapper → 비공개 schema의 제한된 함수만 통과합니다. 해당 함수는 매 호출마다 auth.uid와 active membership, 역할, farm을 확인합니다. user_metadata를 권한 근거로 쓰지 않습니다.
4. Storage는 private입니다. 읽기는 같은 farm의 active 회원, 쓰기는 자신의 farm/user prefix만 가능합니다. 일반 노드의 overwrite/delete 정책은 없습니다. 확정할 파일은 해당 task/attempt prefix에 있어야 하며, upload가 끝나야 commit합니다.
5. 이 시스템은 같은 팀의 노드를 기본적으로 신뢰합니다. 악성 워커가 가짜 기하/리포트를 만드는 비잔틴 공격까지 증명으로 막는 시스템이 아닙니다. 그래서 최초 caller의 시각 검토가 여전히 필요합니다. 팀 밖 임의의 공용 연산 노드를 바로 붙이지 마세요.
6. 허용된 실행기는 설치된 SF3D/TripoSR와 번들 Blender adapter뿐입니다. 원격 spec에는 명령어·임의 Python·shell script를 넣을 수 없습니다. subprocess는 shell=False이며 Blender는 --disable-autoexec로 실행합니다. 이것이 Blender/GPU 드라이버의 모든 취약점을 막는다는 뜻은 아닙니다.
7. 모든 원격 요청은 HTTPS입니다. Authorization을 다른 서버로 보내는 redirect와 임의 TUS URL은 거부합니다. 내려받은 파일은 SHA-256/크기를 확인합니다. 해시가 맞는다는 사실은 제작자를 신뢰할 수 있다는 증명이 아닙니다.
8. `warm --install`은 공식 repository의 requirements와 빌드 스크립트를 해당 노드 권한으로 실행합니다. 읽고 신뢰한 upstream revision을 사용하세요. 원본 코드는 revision을 기록하고 모델은 snapshot을 고정하지만, 첫 설치의 native dependency 전체가 완벽하게 재현된다는 보장은 없습니다.

## 노드 분실 / 계정 폐기

Supabase SQL Editor에서 해당 노드의 membership을 먼저 inactive로 바꿉니다.

```sql
update public.cf_members set active = false where user_id = '<해당_노드_UUID>'::uuid;
```

RLS/RPC가 membership을 직접 읽으므로 이후 요청은 차단됩니다. 이미 저장된 로컬 파일은 원격으로 회수할 수 없습니다. Auth 세션과 계정도 별도로 정리하되, 기존 task의 audit reference를 삭제하는 데 따른 FK를 확인하세요. 단순히 Auth 계정을 삭제하면 이미 발급된 JWT가 즉시 사라진다고 가정하지 않습니다.

## 운영 확인

Supabase Security Advisor와 데이터 접근 로그를 검토하세요. 기존 다른 서비스의 광범위한 Storage 정책이 같은 bucket에 적용되면 여기의 좁은 정책만으로 막을 수 없습니다. 이 때문에 전용 프로젝트를 기본 절차로 잡았습니다. public signup은 필요하지 않습니다. 팀 외 가입이 필요 없는 프로젝트라면 운영 설정에서 비활성화하세요.

SQL 스크립트는 채팅 실행 환경에서 실제 hosted Supabase에 적용/검증하지 않았습니다. 동봉된 PostgreSQL smoke fixture와 실제 소규모 등록·업로드 시험을 거친 뒤 팀 전체에 배포하세요.
