# Unity 임포트 규칙 검증

Unity 6000.3.22f1과 Blender 5.2.1에서 확인했다. 이 시험은 리그·블렌드셰이프·클립을 가진 합성 FBX를 실제 Unity ModelImporter로 가져온다. 신경망 실행 또는 에셋 시각 품질 시험이 아니다. 기존 게임 프로젝트 대신 새 프로젝트에서만 실행한다.

저장소 루트에서 아래 준비 코드를 실행한다. `work/unity-policy-check`가 이미 있으면 새 이름을 사용한다.

```sh
python3 - <<'PY'
from pathlib import Path
import shutil
root = Path('work/unity-policy-check')
root.mkdir(parents=True, exist_ok=False)
project = root / 'project'
(project / 'Assets/Editor').mkdir(parents=True)
(project / 'Packages').mkdir()
(project / 'ProjectSettings').mkdir()
(project / 'Packages/manifest.json').write_text('{"dependencies":{}}\n')
(project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.3.22f1\n')
(project / '.clayfarm-policy-test-project').touch()
for name in ('examples/unity/Editor/ClayFarmModelImportPolicy.cs',
             'tests/unity/Editor/ClayFarmImportPolicyVerification.cs'):
    shutil.copyfile(name, project / 'Assets/Editor' / Path(name).name)
PY

/opt/homebrew/bin/blender --background --factory-startup --disable-autoexec \
  --python-exit-code 1 --python tests/unity/create_fixture.py \
  -- work/unity-policy-check/animated.fbx

CLAYFARM_UNITY_FIXTURE="$PWD/work/unity-policy-check/animated.fbx" \
  /Applications/Unity/Hub/Editor/6000.3.22f1/Unity.app/Contents/MacOS/Unity \
  -batchmode -nographics -quit -projectPath "$PWD/work/unity-policy-check/project" \
  -executeMethod ClayFarm.Editor.Tests.ClayFarmImportPolicyVerification.Run \
  -logFile "$PWD/work/unity-policy-check/unity.log"
```

Windows에서는 해당 장비의 Blender/Unity 실행 파일 경로와 환경변수 설정 방식을 사용한다. Windows Unity에서 이 검사는 아직 실행하지 않았다.

성공 조건은 Unity exit 0, 로그의 `CLAYFARM_IMPORT_POLICY_PASS 8 scenarios`, 프로젝트의 `policy-verification.txt`다. 소스 fixture의 실제 클립·블렌드셰이프 존재, 공통/정적/중첩/유사 이름/대소문자 경로, 재임포트 Medium 강제, 외부 클립용 Generic 리그 보존 및 무관한 설정 보존을 검사한다.
