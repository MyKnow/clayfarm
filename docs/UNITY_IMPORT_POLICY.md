# Unity FBX 임포트 규칙

2026-09-14 사용자 결정: ClayFarm FBX의 **Mesh Compression은 Medium으로 고정**한다. 품질 문제를 발견해도 자동으로 Low/Off로 변경하지 않고 해당 에셋의 검토 항목으로 남긴다.

| 범위 | 탭 | 설정 | 값 |
|---|---|---|---|
| ClayFarm FBX 공통 | Model | Mesh Compression | **Medium** |
| 블렌드셰이프를 사용하지 않는 에셋 | Model | Import BlendShapes | 끄기 |
| 리그·아바타 기반 애니메이션을 사용하지 않는 에셋 | Rig | Animation Type | None |
| 해당 FBX의 애니메이션 클립을 사용하지 않는 에셋 | Animation | Import Animation | 끄기 |

각 기능의 사용 여부는 독립적으로 판단한다. 코드·물리로 이동하거나 회전하는 상자·무기는 세 기능을 사용하지 않을 수 있다. 제자리에 있어도 표정·체형 변경에 블렌드셰이프를 사용하면 이를 유지한다. 외부 클립으로 움직이는 캐릭터는 해당 FBX의 Import Animation을 끄더라도 필요한 Generic/Humanoid 리그를 유지한다. Unity GameObject의 Static 플래그는 이 규칙으로 변경하지 않는다.

## 적용 방법

1. `examples/unity/Editor/ClayFarmModelImportPolicy.cs`를 대상 Unity 프로젝트의 `Assets/Editor/ClayFarmModelImportPolicy.cs`로 추가한다.
2. ClayFarm FBX는 `Assets/ClayFarm/` 아래에 둔다. 해당 FBX는 최초 임포트와 재임포트마다 Medium을 적용한다.
3. **리그·블렌드셰이프·FBX 내부 애니메이션을 모두 사용하지 않는 것으로 확인한 에셋만** `Assets/ClayFarm/StaticMeshes/` 아래에 둔다. 이 경로에서는 세 옵션도 함께 끈다. 현재 ClayFarm의 메시 전용 출력이 이 분류에 해당한다.
4. 그 외 에셋은 `Assets/ClayFarm/Models/` 등 StaticMeshes 밖에 둔다. Medium만 강제하고 세 옵션은 기존 값을 보존한다. 개별 기능이 불필요한 경우 위 표에 따라 Inspector에서 각각 끈다. 용도를 모르면 이 분류를 사용한다.
5. 이미 들어온 FBX에는 Unity의 Reimport를 실행한다. StaticMeshes에서 다른 폴더로 옮겨 애니메이션 용도로 전환할 때는 필요한 Rig/BlendShapes/Animation 설정을 다시 지정한다. 꺼진 값을 임포터가 추측해 복원하지 않는다.

폴더 이름은 전체 경로 경계로 구분한다. `Assets/ClayFarmOther/`와 `Assets/ClayFarm/StaticMeshesBackup/`는 각각 공통 규칙 밖, 세 옵션 끄기 규칙 밖이다. 대소문자 차이는 동일하게 처리한다. ClayFarm 밖의 FBX와 GLB/GLTF 전용 임포터에는 적용하지 않는다. 스케일·축·재질·Read/Write·Collider 설정은 변경하지 않는다.

이 저장소는 Python 기반 독립 ClayFarm 저장소이므로 게임 프로젝트를 포함하지 않는다. 위 Editor 스크립트는 소스 패키지에 포함되며 게임 프로젝트에서 설치해야 활성화된다. 다른 프로젝트의 기존 에셋을 자동 이동하거나 교체하지 않는다.

## 검증 경계

Medium은 저장 용량을 위한 정밀도 손실 압축이다. 실제 에셋의 실루엣·음영·UV와 로딩을 검토한다. 임포트 옵션 적용 성공은 시각 품질 승인, 리깅/애니메이션 모델 구현 또는 모델 ready의 증거가 아니다.

Unity API와 설정 근거:

- [OnPreprocessModel](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/AssetPostprocessor.OnPreprocessModel.html)
- [Model 설정](https://docs.unity3d.com/6000.3/Documentation/Manual/FBXImporter-Model.html)
- [Rig 설정](https://docs.unity3d.com/6000.3/Documentation/Manual/FBXImporter-Rig.html)
- [Animation 설정](https://docs.unity3d.com/6000.3/Documentation/Manual/class-AnimationClip.html)
- [메시 압축의 효과와 제약](https://docs.unity3d.com/6000.3/Documentation/Manual/types-of-mesh-data-compression.html)
