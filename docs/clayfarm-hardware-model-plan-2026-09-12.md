# ClayFarm 하드웨어 적응형 모델 레지스트리

검토일: 2026-09-12 / 상태: 설계 초안 / 워커 코드 변경 없음

## 요구사항

RTX 4050를 포함한 여러 성능의 컴퓨터와 Apple Silicon Mac을 워커로 수용한다. 에셋 유형 × 모델 × 백엔드 × 실행 설정을 하나의 프로필로 관리한다. 웹뿐 아니라 Windows/macOS CLI로 가입·로그인·신청·승인·설치·관리·검증·업데이트가 가능해야 한다.

**이 파일과 YAML은 배포용 lockfile이나 실행기 구현이 아니다.** 모델 revision, 파일 해시, 실행기·환경 lock 및 실장비 검증을 채운 뒤에만 서명·배포한다. `null`은 근거없음/미측정이며 0이 아니다. 지금 포함한 프로필은 어느 것도 현장 ready로 표시하지 않았다.

## 구간 정의

구간은 공칭 메모리를 기준으로 후보를 찾는 출발점이다. 실제 실행은 백엔드, OS, 시스템 RAM, 여유 메모리, 입력 범위와 실측 결과를 함께 검사한다. 통합 메모리를 전용 VRAM으로 환산하지 않는다. 4GB 장비나 GPU가 없는 장비도 검증된 CPU/경량 작업에 참여할 수 있다.

|구간|대상|목적|
|---|---|---|
|CPU|GPU가 없거나 호환 실행기가 없는 장비|CPU RAM·실측 처리시간에 따라 개별 허용|
|C4|CUDA 전용 메모리 4GB급|초경량 2D와 CPU 작업 중심|
|C6|CUDA 전용 메모리 6GB급|RTX 4050 Laptop 예시; 낮은 메모리 설정 검증|
|C8|CUDA 전용 메모리 8GB급|RTX 4070 Laptop 예시; 표준 경량 생성|
|C12|CUDA 전용 메모리 12GB급|중형 shape/리깅 후보|
|C16|CUDA 전용 메모리 16GB급|중대형 2D 및 2.0 texture 후보|
|C24|CUDA 전용 메모리 24GB급|고메모리 단일 단계; Lite motion은 경계 시험|
|C32|CUDA 전용 메모리 32GB 이상|전체 고메모리 파이프라인 후보|
|A16|Apple Silicon 통합 메모리 16GB급|CPU/MPS/MLX 프로필별 시험|
|A24|Apple Silicon 통합 메모리 24GB급|사용자 M5 Pro; 상위 이미지·SFX GPU 경로 포함|
|A32|Apple Silicon 통합 메모리 32GB 이상|상위 GPU 모델 후보; CUDA 등급과 동일시 금지|

## 성능 구간별 초기 후보 목록

각 행의 후보는 자동 설치 확정 목록이 아니다. `experimental`/`research_port`는 미검증 실행 또는 별도 이식이 필요한 경로다. 상위 노드는 필요한 하위 모델도 실행할 수 있으며, 목록 전체를 동시에 설치하지 않는다.

### CPU — GPU가 없거나 호환 실행기가 없는 장비

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate)|
|texture|`procedural-material` (candidate)|
|vfx|`procedural-vfx` (candidate)|
|ui|`deterministic-ui` (candidate)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate)|
|rigging|실행 경로 미정; 다른 노드에 배정하거나 대기|
|animation|`retarget-and-bake` (candidate)|

### C4 — CUDA 전용 메모리 4GB급

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate)|
|texture|`procedural-material` (candidate); `sd-turbo-cuda` (candidate)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-cuda` (candidate)|
|ui|`deterministic-ui` (candidate); `sd-turbo-cuda` (candidate)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-cuda` (candidate)|
|rigging|실행 경로 미정; 다른 노드에 배정하거나 대기|
|animation|`retarget-and-bake` (candidate)|

### C6 — CUDA 전용 메모리 6GB급

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate); `triposr-lowmem` (experimental); `sf3d-lowmem` (experimental); `hunyuan2-mini-lowmem` (experimental)|
|texture|`procedural-material` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental)|
|ui|`deterministic-ui` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-cuda` (candidate)|
|rigging|실행 경로 미정; 다른 노드에 배정하거나 대기|
|animation|`retarget-and-bake` (candidate)|

### C8 — CUDA 전용 메모리 8GB급

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate); `triposr-lowmem` (experimental); `triposr-cuda` (candidate); `sf3d-lowmem` (experimental); `sf3d-cuda` (candidate); `hunyuan2-mini-lowmem` (experimental); `hunyuan2-shape` (candidate)|
|texture|`procedural-material` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate)|
|ui|`deterministic-ui` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-cuda` (candidate); `sa3-medium-cuda` (candidate)|
|rigging|`unirig-c8-boundary` (experimental)|
|animation|`retarget-and-bake` (candidate)|

### C12 — CUDA 전용 메모리 12GB급

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate); `triposr-lowmem` (experimental); `triposr-cuda` (candidate); `sf3d-lowmem` (experimental); `sf3d-cuda` (candidate); `hunyuan2-mini-lowmem` (experimental); `hunyuan2-shape` (candidate); `hunyuan21-shape` (candidate)|
|texture|`procedural-material` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental)|
|ui|`deterministic-ui` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-cuda` (candidate); `sa3-medium-cuda` (candidate)|
|rigging|`unirig-cuda` (candidate); `skintokens-profile-test` (research_port)|
|animation|`retarget-and-bake` (candidate)|

### C16 — CUDA 전용 메모리 16GB급

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate); `triposr-lowmem` (experimental); `triposr-cuda` (candidate); `sf3d-lowmem` (experimental); `sf3d-cuda` (candidate); `hunyuan2-mini-lowmem` (experimental); `hunyuan2-shape` (candidate); `hunyuan21-shape` (candidate)|
|texture|`procedural-material` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate); `hunyuan2-paint` (candidate)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate)|
|ui|`deterministic-ui` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-cuda` (candidate); `sa3-medium-cuda` (candidate)|
|rigging|`unirig-cuda` (candidate); `skintokens-profile-test` (research_port)|
|animation|`retarget-and-bake` (candidate)|

### C24 — CUDA 전용 메모리 24GB급

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate); `triposr-lowmem` (experimental); `triposr-cuda` (candidate); `sf3d-lowmem` (experimental); `sf3d-cuda` (candidate); `hunyuan2-mini-lowmem` (experimental); `hunyuan2-shape` (candidate); `hunyuan21-shape` (candidate); `trellis2-linux` (experimental)|
|texture|`procedural-material` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate); `hunyuan2-paint` (candidate); `hunyuan21-paint` (candidate); `trellis2-linux` (experimental)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate)|
|ui|`deterministic-ui` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-cuda` (candidate); `sa3-medium-cuda` (candidate)|
|rigging|`unirig-cuda` (candidate); `skintokens-profile-test` (research_port)|
|animation|`retarget-and-bake` (candidate); `hymotion-lite-cuda` (experimental)|

### C32 — CUDA 전용 메모리 32GB 이상

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate); `triposr-lowmem` (experimental); `triposr-cuda` (candidate); `sf3d-lowmem` (experimental); `sf3d-cuda` (candidate); `hunyuan2-mini-lowmem` (experimental); `hunyuan2-shape` (candidate); `hunyuan21-shape` (candidate); `trellis2-linux` (experimental)|
|texture|`procedural-material` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate); `hunyuan2-paint` (candidate); `hunyuan21-paint` (candidate); `trellis2-linux` (experimental)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate)|
|ui|`deterministic-ui` (candidate); `sd-turbo-cuda` (candidate); `sdxl-lowmem-cuda` (experimental); `sdxl-cuda` (candidate); `flux2-q4-cuda` (experimental); `flux2-bf16-cuda` (candidate)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-cuda` (candidate); `sa3-medium-cuda` (candidate)|
|rigging|`unirig-cuda` (candidate); `skintokens-profile-test` (research_port)|
|animation|`retarget-and-bake` (candidate); `hymotion-lite-cuda` (experimental); `hymotion-cuda` (experimental)|

### A16 — Apple Silicon 통합 메모리 16GB급

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate)|
|texture|`procedural-material` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental)|
|ui|`deterministic-ui` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-mlx` (experimental)|
|rigging|실행 경로 미정; 다른 노드에 배정하거나 대기|
|animation|`retarget-and-bake` (candidate)|

### A24 — Apple Silicon 통합 메모리 24GB급

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate); `sf3d-mps-a24` (experimental); `hunyuan2-mini-mps-port` (research_port)|
|texture|`procedural-material` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental); `flux2-q4-mlx` (experimental)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental); `flux2-q4-mlx` (experimental)|
|ui|`deterministic-ui` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental); `flux2-q4-mlx` (experimental)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-mlx` (experimental); `sa3-medium-mlx` (experimental)|
|rigging|실행 경로 미정; 다른 노드에 배정하거나 대기|
|animation|`retarget-and-bake` (candidate); `hymotion-lite-split-rnd` (research_port)|

### A32 — Apple Silicon 통합 메모리 32GB 이상

|에셋|후보 실행 프로필|
|---|---|
|3d_model|`procedural-static-mesh` (candidate); `sf3d-mps-a32` (experimental); `hunyuan2-mini-mps-port` (research_port)|
|texture|`procedural-material` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental); `flux2-q4-mlx` (experimental); `flux2-q8-mlx` (experimental)|
|vfx|`procedural-vfx` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental); `flux2-q4-mlx` (experimental); `flux2-q8-mlx` (experimental)|
|ui|`deterministic-ui` (candidate); `sd-turbo-mps` (experimental); `sdxl-mps` (experimental); `flux2-q4-mlx` (experimental); `flux2-q8-mlx` (experimental)|
|sfx|`procedural-sfx` (candidate); `sa3-small-cpu` (candidate); `sa3-small-mlx` (experimental); `sa3-medium-mlx` (experimental)|
|rigging|실행 경로 미정; 다른 노드에 배정하거나 대기|
|animation|`retarget-and-bake` (candidate); `hymotion-lite-split-rnd` (research_port)|

## 모델별 공식 근거와 설치 제한

|모델|용도|권리 검토|근거|
|---|---|---|---|
|SD-Turbo|image|Stability 원문·가중치·상업 사용 조건 검토 필요|[sd-turbo](https://huggingface.co/stabilityai/sd-turbo)|
|SDXL Base 1.0|image|CreativeML Open RAIL++-M; 사용 제한 검토|[sdxl](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)|
|FLUX.2 klein 4B|image|본체 Apache-2.0; encoder/변환본/의존성 별도 검토|[flux2-klein](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B), [mflux](https://github.com/mflux-community/mflux)|
|TripoSR|shape|MIT 표기; 체크포인트와 의존성의 정확한 조건 고정|[triposr](https://github.com/VAST-AI-Research/TripoSR)|
|Stable Fast 3D|shape, texture|Stability 가중치 조건과 gated 접근 승인 확인|[sf3d](https://github.com/Stability-AI/stable-fast-3d)|
|Hunyuan3D 2mini Turbo|shape|Tencent 모델별 라이선스 검토; 묵시적 승인 금지|[hunyuan2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)|
|Hunyuan3D 2.0 Shape|shape|Tencent 모델별 라이선스 검토|[hunyuan2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)|
|Hunyuan3D 2.0 Paint|texture|Tencent 모델별 라이선스 검토|[hunyuan2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)|
|Hunyuan3D 2.1 Shape|shape|Tencent 모델별 라이선스 검토|[hunyuan21](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)|
|Hunyuan3D 2.1 Paint|texture|Tencent 모델별 라이선스 검토|[hunyuan21](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)|
|TRELLIS.2 4B|shape, texture|모델·코드 MIT; 렌더 의존성별 조건 확인|[trellis2](https://github.com/microsoft/TRELLIS.2)|
|Stable Audio 3 Small-SFX|sfx|Stable Audio Community + Gemma 구성요소 조건; 접근 승인 필요|[sa3-small](https://huggingface.co/stabilityai/stable-audio-3-small-sfx), [sa3-runtime](https://github.com/Stability-AI/stable-audio-3)|
|Stable Audio 3 Medium|sfx|가중치·구성요소 조건, gated 접근 확인|[sa3-medium](https://huggingface.co/stabilityai/stable-audio-3-medium), [sa3-runtime](https://github.com/Stability-AI/stable-audio-3)|
|UniRig|rigging|실제 배포 checkpoint와 코드·의존성 조건 검토|[unirig](https://github.com/VAST-AI-Research/UniRig), [unirig-weights](https://huggingface.co/VAST-AI/UniRig)|
|SkinTokens / TokenRig|rigging|코드 MIT 표기; 실제 모델 가중치와 모든 구성요소 조건 검토|[skintokens](https://github.com/VAST-AI-Research/SkinTokens)|
|HY-Motion 1.0 Lite|motion|Tencent custom 조건 및 skeleton/후처리 의존성 검토|[hymotion](https://github.com/Tencent-Hunyuan/HY-Motion-1.0)|
|HY-Motion 1.0|motion|Tencent custom 조건 및 skeleton/후처리 의존성 검토|[hymotion](https://github.com/Tencent-Hunyuan/HY-Motion-1.0)|

## 반드시 분리할 경계

1. 4050 Laptop 6GB와 4070 Laptop 8GB의 차이를 제품명 문자열 분기로 구현하지 않는다. 탐지한 자원과 프로필 검증으로 판정한다.

2. TripoSR/SF3D 기본 약 6GB는 6GB 노트북에서 안전 여유가 있다는 의미가 아니다. 6GB 구간은 3D 저메모리 설정을 개별 시험한다.

3. Hunyuan3D 2.1은 shape 10GB/texture 21GB/full 29GB다. 12GB 노드의 shape 성공을 textured 전체 생성 성공으로 표시하지 않는다.

4. HY-Motion은 Lite 최소24GB/Standard26GB라는 공식 표를 기준으로 둔다. 본체 가중치 크기만으로 4GB/6GB 실행을 약속하지 않는다. text encoder 분리·양자화·CPU offload는 독립적인 연구 프로필이다.

5. Stable Audio 3 공식 H200 메모리 측정은 목표 노트북의 총 GPU 사용량이나 wall time이 아니다. Small은 CPU/MLX, Medium은 CUDA/MLX 경로를 각각 검증하며 Windows 의존성도 별도 검사한다.

6. VFX용 이미지와 완성된 VFX, UI 이미지와 실제 UI, 리깅과 모션 생성, 애니메이션 영상과 skeleton clip을 서로 혼동하지 않는다. 생성 후 typed pipeline 및 엔진 QA가 필요하다.

7. Mac 24GB에서 FLUX.2 klein 4B의 MLX 양자화, Stable Audio 3의 MLX 실행을 우선 GPU 생성 후보로 둔다. SF3D MPS는 공식 32GB 미만 CPU 권고를 표시하면서 24GB 저메모리 실험을 유지한다. CUDA 모델이 자동 이식되는 것은 아니다.

8. TRELLIS.2 공식 경로는 Linux/CUDA/24GB 이상이다. CLI는 Windows에서도 관리할 수 있어야 하지만 native 실행 또는 WSL2는 별도 설치·검증 프로필이며 사용자 동의 없이 활성화하지 않는다.

## 자동 적용 흐름

가입·로그인 → 참여 승인 → hardware probe → 허용 역할 선택 → 레지스트리 후보 계산 → 필요한 모델만 설치 → smoke test → 대표 입력 행렬 시험 → node-ready capability 보고 → 계약을 만족하는 작업만 수락

예약 여유가 부족하면 다른 노드 또는 대기 상태를 선택한다. 숨겨진 모델 교체·해상도 축소·유료 클라우드 fallback은 금지한다. 모델 변경은 승인된 대체 후보로 기록하며 재시도에서도 입력·모델·환경 해시를 보존한다.

## 신규 CLI 계약 예시

아래 명령은 설계안이며 현재 워커에 존재한다고 보장하지 않는다.

```text
clayfarm node probe --json
clayfarm models plan --auto --kinds 3d_model,texture,vfx,ui,sfx,animation
clayfarm models sync --approved-plan PLAN_ID
clayfarm models benchmark --installed
clayfarm node capabilities --json
clayfarm admin model-profiles list
clayfarm admin model-profiles approve PROFILE_ID
clayfarm releases promote RELEASE_ID --channel stable
```

## 검증 기준

정적 검증: YAML parsing 및 source/model/profile/band 참조 무결성. 실제 검증 미실행: 모델 다운로드, CUDA/MPS/MLX, Windows/macOS 설치, 라이선스 최종 승인, 생성 품질, 메모리 peak, 노드 장애·복구, 서버 게시.

## 출처

- [nvidia-laptop](https://www.nvidia.com/en-us/geforce/laptops/compare/) — RTX 4050 Laptop 6GB; RTX 4070 Laptop 8GB. 제품명은 매칭 조건이 아닌 설명용. (확인 2026-09-12)
- [sd-turbo](https://huggingface.co/stabilityai/sd-turbo) — 512x512 선호, 1~4 step 계열. 상업 사용은 별도 원문 조건 검토. (확인 2026-09-12)
- [sdxl](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) — Base 단독 실행 가능. CreativeML Open RAIL++-M. (확인 2026-09-12)
- [flux2-klein](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) — 4B Apache-2.0; 공식 소개 약 13GB VRAM. 저메모리 양자화 프로필은 별도 검증. (확인 2026-09-12)
- [mflux](https://github.com/mflux-community/mflux) — MLX 이미지 모델 구현, FLUX.2 및 양자화 지원. ClayFarm 연동 검증과 별개. (확인 2026-09-12)
- [diffusers-memory](https://huggingface.co/docs/diffusers/en/optimization/memory) — 지원 파이프라인의 offload/tiling 등. 모델마다 지원 여부·속도 차이 검증. (확인 2026-09-12)
- [diffusers-mps](https://huggingface.co/docs/diffusers/en/optimization/mps) — MPS 실행 및 메모리 관련 지침. 모든 모델의 호환 보장은 아님. (확인 2026-09-12)
- [triposr](https://github.com/VAST-AI-Research/TripoSR) — 기본 단일 이미지 실행 약 6GB VRAM. 6GB 카드의 안전 실행 보장이 아님. (확인 2026-09-12)
- [sf3d](https://github.com/Stability-AI/stable-fast-3d) — 기본 CUDA 약 6GB. MPS 실험 지원, 통합 메모리 32GB 미만에서는 CPU 권고. (확인 2026-09-12)
- [hunyuan2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) — Mini/Turbo 가중치 공개; 2.0 설명: shape 6GB, shape+texture 16GB. Mini 각 설정의 실측은 별도. (확인 2026-09-12)
- [hunyuan21](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) — shape 10GB, texture 21GB, full 29GB. 단계별 수치와 전체 수치를 혼동하지 않음. (확인 2026-09-12)
- [trellis2](https://github.com/microsoft/TRELLIS.2) — 최소 NVIDIA 24GB, Linux에서 시험. 모델·코드 MIT, 일부 의존성 별도 조건. (확인 2026-09-12)
- [sa3-small](https://huggingface.co/stabilityai/stable-audio-3-small-sfx) — SFX 특화. 접근 승인, Stable Audio Community 및 Gemma 구성요소 조건 검토. (확인 2026-09-12)
- [sa3-medium](https://huggingface.co/stabilityai/stable-audio-3-medium) — 상위 오디오 생성·편집 후보. 정확한 가중치 및 구성요소 조건을 함께 검토. (확인 2026-09-12)
- [sa3-runtime](https://github.com/Stability-AI/stable-audio-3) — CPU/TFLite, CUDA 및 MLX 경로. H200 공개 peak allocated: Small 5s 1.69GB; Medium 5s 5.07GB. 해당 노드/전체 프로세스 예산으로 그대로 사용 금지. (확인 2026-09-12)
- [unirig](https://github.com/VAST-AI-Research/UniRig) — Skeleton+skinning. README CUDA >=8GB; 8GB 경계 시험, 12GB급부터 우선 도입 제안. (확인 2026-09-12)
- [unirig-weights](https://huggingface.co/VAST-AI/UniRig) — 모델 카드에는 >8GB 표현, 공개 체크포인트 상태는 실제 revision에서 재확인. (확인 2026-09-12)
- [skintokens](https://github.com/VAST-AI-Research/SkinTokens) — TokenRig: skeleton+skinning 후속 후보. CUDA/flash-attn 설치 경로; 최소 VRAM 미확인. (확인 2026-09-12)
- [hymotion](https://github.com/Tencent-Hunyuan/HY-Motion-1.0) — 공식 표 Lite 최소24GB/Standard26GB. humanoid 대상; seamless loop/in-place 기본 미지원. 저메모리 분할 이식은 R&D. (확인 2026-09-12)
- [vfxgraph](https://docs.unity3d.com/Packages/com.unity.visualeffectgraph@17.0/manual/System-Requirements.html) — Compute/SSBO 등 실행 조건. 생성용 GPU 사양과 게임 런타임 플랫폼 지원 분리. (확인 2026-09-12)
