# ClayFarm 변경 로그

## v0.4.0.dev1 — 2026-09-14

### 추가

- `procedural-sfx` 내장 프로필에 `sword_swing` 효과를 추가했다. 고정 seed에서
  동일한 48 kHz mono PCM16 WAV를 만들며, 짧은 어택과 감쇠하는 blade whoosh
  레이어를 사용한다.
- `examples/sfx-sword-swing.json`과 CLI 생성 절차를 추가했다.
- CLI 버전 단일 원천, 서명된 wheel update check/download/apply 경로를 추가했다.

### 검증

- 실제 저장소 회귀: `177 passed, 2 skipped`.
- 검 휘두르기 후보: 0.35초, 48 kHz mono PCM16, clipping 0, peak -1 dBFS,
  RMS -19.242 dBFS.
- 고정 seed의 결정성과 기존 `beep`·`whoosh`·`impact` 출력의 바이트 동일성을
  확인했다.

### 범위

- 이 효과는 `neural: false`인 절차적 후보이며, Stable Audio 모델 출력이나
  게임 최종 승인 음원이 아니다. 사람 청취 승인 후 Unity에 연결한다.
- 중앙 PostgreSQL 작업 큐와 Storage는 현재 3D 작업 계약만 사용한다. 오디오
  산출물의 중앙 큐 연결과 실제 Stable Audio CUDA/MPS/MLX 실행 증거는 별도
  작업에서 다룬다.

사용 방법은 [README.md](README.md)의 로컬 Text-to-Sound 절을 참고한다.
