---
name: clayfarm
description: 실제 컨셉 이미지와 명세를 ClayFarm 워커에 제출하고 Blender 후처리·프리뷰 결과를 회수해 검수·수정한다. ClayFarm 요청자 연결, 워커 준비·상태 확인에도 사용한다.
---

# ClayFarm — BettingRoyal

저장소 규칙과 [운영 안내](../../../docs/clayfarm/usage.md)를 읽는다.
요구 정리와 다른 제작 경로 비교가 필요하면 [unity-asset-factory](../unity-asset-factory/SKILL.md)를 사용한다.
이 스킬은 저장소의 `tools/clayfarm/run.py`를 직접 실행한다. 전역 assetgen 설치나 이전 대화의 출력 폴더를 찾지 않는다.
Codex와 Claude가 이 공용 파일을 읽으며 별도 스킬 사본을 만들지 않는다.

## 제작 요청

1. 현재 요청·기존 답·관련 제품 스펙에서 외형·치수·폴리곤·재질·사용처를 정리한다. 실제 이미지 도구로 컨셉을 만들거나 사용자가 제공한 이미지를 사용한다. 이미지가 없으면 그 입력만 요청한다. 설명 문자열이나 mock 도형을 실제 컨셉으로 대체하지 않는다.
2. [명세](../../../docs/clayfarm/reference/SPEC.md)와 [Blender 옵션](../../../docs/clayfarm/reference/BLENDER_V02.md)을 필요한 만큼 읽고 [예시](../../../tools/clayfarm/examples/hammer.spec.json)를 참고한다. 예시는 제품 규격이 아니다. `description`은 검토 문맥이며 실행 가능한 모델링 지시가 아니다. 에셋 팩토리의 JSON과 혼용하지 않는다.
3. 실제 caller home을 확인해 `python tools/clayfarm/run.py --home <caller-home> doctor --online`을 실행한다. 요청자에는 GPU·Blender가 필요 없다. 등록이 없으면 [등록 절차](../../../docs/clayfarm/usage.md#역할과-등록)를 따른다. home은 저장소 밖이며 계정 파일 본문을 읽거나 출력하지 않는다.
4. 기존 승인에 컨셉·명세의 해당 farm 전송과 작업 실행이 포함되는지 확인하고 그 메시지 근거를 작업 기록에 남긴다. 이미 승인된 범위는 재질문하지 않는다. 내장 도입만으로 새 계정·모델 설치·비용 사용이 승인되지는 않는다. `strict_offline`/`local_only`이면 분산 요청을 하지 않는다.
5. `python tools/clayfarm/run.py --home <caller-home> submit --concept <실제-이미지> --spec <명세.json> --engine <triposr-또는-sf3d> --caller <codex-또는-claude> --session <현재-작업-ID>`를 실행한다. 준비된 엔진을 선택한다. 서로 다른 컨셉이나 엔진만 후보로 늘린다. 허구의 seed로 같은 실행을 증식시키지 않는다.
6. 반환된 job ID와 원 호출자 정보를 작업 기록에 저장한다. `result <job-id> --wait 45 --artifacts`로 결과를 회수한다. 대기 중에는 도구의 진행 세션을 유지하고 사용자에게 상태를 알린다. 반복 제출하지 않는다. 제출 응답이 불명확하면 저장된 ID의 `retry-submit <job-id>`로 기존 요청을 복구한다.
7. contact sheet를 실제로 열어 컨셉 대비 실루엣·후면·방향·색을 검사하고 report의 치수·예산·피벗을 함께 확인한다. 필요하면 개별 방향 이미지를 연다. 파일 존재나 `hard_pass`만으로 외형을 승인하지 않는다.
8. 전역 수정은 `revise <job-id> --task <process-task-id> --patch <patch.json>`으로 새 job을 만들고 회수·검토한다. 원본 raw mesh를 재사용한다. 중첩 필드는 통째로 교체하므로 유지할 옵션도 함께 쓴다. 부위 구조 수정은 컨셉을 고쳐 `submit --parent-job <job-id>`로 새 입력을 보낸다.
9. 기계 검사와 실제 시각 검토가 모두 통과한 후보만 `approve <job-id> --task <process-task-id>`로 선택한다. 이는 ClayFarm 후보 선택이며 사용자의 Unity 반영·출시 승인을 뜻하지 않는다. mock은 승인하지 않는다.

`result`의 파일·이미지·보고서는 원 호출 세션에서 확인한다. 외부 LLM 호출, 자동 재과금, 닫힌 세션 재개, 작업자에게 메시지 발송은 이 스킬의 자동 동작이 아니다.
로그는 실패 구간만 읽는다. 원본·모델 코드·캐시 전체를 읽지 않는다.

## 워커와 운영

[운영 안내의 워커 절차](../../../docs/clayfarm/usage.md#워커-준비)를 사용한다.
Blender selftest는 등록이나 CUDA 없이 가능하고, 모델 warm은 Blender 없이 가능하다.
노드 readiness, 실제 추론, Blender 실행, 복수 실장비 동시 처리, Unity 결과를 각각 보고한다.
`stop`은 새 작업 수신을 멈추고 실행 중 작업·outbox를 보존한다. 남의 프로세스나 DB를 지우지 않는다.

개인용 배포를 요청받으면 사람·역할·장비별 기존 할당을 확인한다. 관리자 접근과 명시적 발급 요청이 있을 때만 등록을 수행한다.
등록 파일은 해당 수신자 것 하나만 포함하고 역할별 home을 분리한다. 저장소나 공용 ZIP에는 계정 정보를 넣지 않는다.

## 검증과 전달

`python scripts/skill-tools.py --smoke --profile clayfarm`은 계정 없이 mock DAG를 실행한다.
Blender도 검사하려면 `--include-optional`을 붙여 준비한 도구를 명시한다.
mock, Blender, 실계정·실장비, Unity 검사와 사용자 외형 승인을 구분한다.
GLB/FBX·contact sheet·report·job ID를 전달하고 Unity 자동 교체를 하지 않는다.
관련 계약은 [S-ART-ZMPVFW](../../../docs/specs/art-animation/S-ART-ZMPVFW.md)다.
