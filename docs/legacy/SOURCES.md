# 근거 및 외부 의존성

확인일: 2026-09-10. 기능 판단에는 공식 문서와 공식 repository를 사용했습니다. 소스/모델의 실제 최신 상태, 라이선스, 서비스 제한은 설치 시 다시 확인해야 합니다.

- PostgreSQL SELECT / FOR UPDATE SKIP LOCKED: https://www.postgresql.org/docs/current/sql-select.html
  - 동시 consumer가 queue-like table을 claim하는 근거. 임대 토큰, 재시도, outbox는 이 프로젝트가 추가 구현한 정책입니다.
- Supabase API key / Auth 구분: https://supabase.com/docs/guides/getting-started/api-keys
  - publishable과 secret, user JWT, RLS 권한의 구분.
- Supabase private bucket: https://supabase.com/docs/guides/storage/buckets/fundamentals
- Supabase TUS resumable uploads: https://supabase.com/docs/guides/storage/uploads/resumable-uploads
  - 6 MiB chunk, 업로드 URL/offset 및 중단 후 재개. 프로젝트의 custom Python 전송 구현은 별도로 테스트해야 합니다.
- Supabase admin create user: https://supabase.com/docs/reference/python/auth-admin-createuser
- SF3D 공식 README: https://github.com/Stability-AI/stable-fast-3d
- SF3D 실제 CLI: https://github.com/Stability-AI/stable-fast-3d/blob/main/run.py
- SF3D 라이선스: https://github.com/Stability-AI/stable-fast-3d/blob/main/LICENSE.md
  - CUDA/MPS/설치 요구, 단일 이미지 입력, GLB 출력의 근거. 동일 이미지에서 임의 seed 후보 다양성을 보장하지 않음.
- TripoSR 공식 README: https://github.com/VAST-AI-Research/TripoSR
- TripoSR 실제 CLI: https://github.com/VAST-AI-Research/TripoSR/blob/main/run.py
  - GLB export, chunk size와 이미지 입력 경로를 어댑터에 사용. 소스·모델 라이선스는 upstream에서 확인.
- PyTorch 기존 버전 공식 설치표: https://pytorch.org/get-started/previous-versions/
  - recipe의 torch 2.5.1 / torchvision 0.20.1 / CUDA 12.4 배포 조합. 이것이 모든 Windows native extension의 설치 성공을 보장하지 않음.
- uv 프로젝트 / lockfile: https://docs.astral.sh/uv/guides/projects/
- uv 공식 설치: https://docs.astral.sh/uv/getting-started/installation/
- Blender command line: https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html
- Apple LaunchAgent: https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html
- Microsoft ScheduledTasks: https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/
- Codex skills 문서 진입점: https://developers.openai.com/codex/skills/
  - 설치 버전에 따라 스킬 탐색 경로가 다르면 에이전트 공식 문서를 따라 조정. 동봉 스킬은 일반 Markdown이며 API 권한을 부여하지 않음.

## 이 프로젝트에서 직접 측정한 근거

`TEST_REPORT.md`, `tests/test_core.py`, `tests/test-log.txt`를 확인하세요. 테스트용 coordinator와 실행기를 사용한 결과이며 실장비 생성 속도·메모리·품질 결과가 아닙니다.

처리량 최적성, 유휴율 0%, 특정 Codex 토큰 절감률, 4070/M5의 실제 성능 우위는 아직 측정하지 않았으며 근거없음입니다. 설계 선택과 실측 결과를 혼동하지 않습니다.
