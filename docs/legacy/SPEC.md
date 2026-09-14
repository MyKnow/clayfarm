# AssetSpec v0.2

`examples/hammer.spec.json`을 복사해서 사용합니다. JSON은 UTF-8입니다. 전송 가능한 것은 데이터이며 명령어/Python 코드/Blender script가 아닙니다.

| 필드 | 의미 / 제한 |
|---|---|
| name | 1~64자의 영문·숫자·하이픈·밑줄 |
| description | 최초 호출자가 검토할 설명. 로컬의 언어 이해/부위 편집 명령이 아님 |
| height_m | 최종 Blender Z축 높이. 0.001~100 m |
| axis_scale | Blender XYZ 방향 상대 비율. 각 0.1~10. 적용 후 height_m으로 전체 정규화 |
| target_triangles | 100~200,000. decimate를 적용하고 실제 개수로 다시 검증 |
| pivot | bottom_center / center |
| material.mode | preserve / clay_single |
| material.color | RGBA 0~1. clay_single일 때 전체를 한 색으로 변경 |
| material.roughness | 0~1. clay_single에 적용 |
| views | front/three_quarter/right/back/top/bottom의 중복 없는 부분 집합, 최대 6개 |
| preview_size | 128~768. 방향별 정사각 PNG 해상도 |

GLB는 glTF export의 Y-up 변환을 적용합니다. FBX는 Blender exporter를 통해 Y-up 방향으로 보냅니다. Unity에서 최종 스케일, 방향, 재질 매핑은 한 번 검증해야 합니다. `height_m` 기준은 후처리 시 Blender Z축입니다.

`material=clay_single`은 단순한 matte 공통 재질이지 고급 점토 셰이더나 스타일 변환 AI가 아닙니다. 손잡이와 망치 머리의 다른 색도 모두 덮어씁니다. 색상 구분이 중요하면 preserve를 유지하고 게임의 재질 규칙으로 정리하세요.

경계가 있는 mesh / non-manifold edge는 경고로 남깁니다. 의도된 구멍이나 열린 그릇까지 일괄 실패 처리하지 않습니다. `hard_pass`는 비어 있지 않은 유한 기하, 예산, 치수 같은 기계적 조건입니다. 캐릭터 리깅, 손에 잡히는 위치, 애니메이션 변형은 이 버전의 자동 검증/생성 범위가 아닙니다.

수정은 새 job으로 저장합니다. 원본 raw mesh에 변경된 전역 spec을 다시 적용하므로 반복 수정할 때 decimate가 누적되는 것을 피합니다. 부위 단위/의미 기반 편집은 지원하지 않아 unknown field로 거부합니다. 원본 컨셉이나 입력이 바뀌어야 하는 요구는 `submit --parent-job`으로 새 컨셉을 전달합니다.

프리뷰 contact sheet의 행은 후보, 열은 보고서의 `columns` 순서입니다. 모든 이미지에 정답 점수를 붙이지 않으며 로컬 테스트용 MOCK 출력은 final approval이 금지됩니다.

## v0.2 추가 필드

`geometry`, `material.preset`, `lod_ratios`, `collider`의 범위와 실제 동작은 [Blender v0.2 안내](BLENDER_V02.md)를 참고하세요. `examples/hammer.spec.json`은 클레이 프리셋, LOD 2개와 box collider를 사용합니다. remesh는 선택 사항이며 기본값은 none입니다.
