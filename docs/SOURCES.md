# 출처와 증거

## 사용자 제공 입력

- `ClayFarm_워커_조영운_v0.2.2_20260911-103838.zip`의 pyz 소스.
- `clayfarm-hardware-model-plan-2026-09-12.md`.
- `clayfarm-model-registry-2026-09-12.yaml`.

모델별 메모리/라이선스 후보 정보는 사용자 제공 레지스트리의 출처 ID를 보존한다.
이번 작업에서 17개 모델 전체의 최신 성능/라이선스를 다시 검증한 것이 아니므로 등록값을 운영 승인의 대체로 사용하지 않는다.
모든 nominal band는 후보 탐색 용도이며 최종 readiness는 실장비 시험이 필요하다.

## 구현에 참고한 공식 문서

- Supabase 이메일 OTP: https://supabase.com/docs/guides/auth/auth-email-passwordless
- Supabase OTP 검증: https://supabase.com/docs/reference/python/auth-verifyotp
- Supabase MFA: https://supabase.com/docs/guides/auth/auth-mfa
- Supabase TOTP: https://supabase.com/docs/guides/auth/auth-mfa/totp
- Supabase rate limits/endpoint: https://supabase.com/docs/guides/auth/rate-limits
- Supabase Auth SMTP: https://supabase.com/docs/guides/auth/auth-smtp
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
- Diffusers MPS: https://huggingface.co/docs/diffusers/en/optimization/mps
- Diffusers memory: https://huggingface.co/docs/diffusers/en/optimization/memory
- Hugging Face pinned snapshot: https://huggingface.co/docs/huggingface_hub/guides/download
- PyTorch MPS: https://docs.pytorch.org/docs/stable/mps.html
- keyring storage/security: https://keyring.readthedocs.io/en/stable/
- cryptography Ed25519: https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/
- TUF architecture (미구현 추가 목표): https://theupdateframework.io/docs/metadata/

Supabase changelog.md 조회는 도구 content type 문제로 전문을 읽지 못했다.
PyPI dependency lock 생성은 DNS 오류로 실패했다. 이를 모델 설치/호환성 검증 성공으로 표시하지 않는다.

## 실행 증거

TEST_REPORT.md, evidence/pytest.log, evidence/pytest.xml, evidence/demo-report.json,
evidence/legacy-source-integrity.json, evidence/sanitization.json을 확인한다.
외부 서비스 호출은 mock 계약 테스트와 실제 연결을 구분해 보고한다.
