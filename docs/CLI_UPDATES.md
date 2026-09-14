# CLI 버전·업데이트

ClayFarm Control의 버전은 [`src/clayfarm_control/version.py`](../src/clayfarm_control/version.py)의
`__version__` 하나를 기준으로 한다. 사용자에게 배포하는 기능 개선이나 버그 수정은 이 값을
올리고, 같은 커밋에서 릴리스 wheel과 서명 manifest를 만든다. `pyproject.toml`, API
`/health`, CLI `--version`, 작업 release ID는 이 값을 읽으므로 서로 다른 버전을 광고하지
않는다.

## 0.4.0.dev2 패치 노트

- SFX schema version 2에 검토 가능한 `Sound Direction Card`를 추가했다.
- `source_text`는 provenance 해시로만 보존하고, Stable Audio SFX에는 결정적으로
  컴파일된 prompt와 금지 조건만 전달한다.
- `clayfarm audio direction draft|validate|compile`과 `clayfarm audio generate`를
  추가했다. `draft` 결과는 항상 `needs_review`이며 자동 승인을 수행하지 않는다.
- 방향 카드의 hash·compiler version·seed를 `direction-manifest.json`에 기록한다.
- 이 릴리스는 로컬 계약·컴파일러 변경이며, 중앙 3D 큐·웹 UI·신경망 모델 ready 상태를
  열지 않는다. 운영 API에는 `v0.4.0.dev2` signed wheel과 manifest가 발행되어 있다.

## 사용자

업데이트 확인은 네트워크를 자동으로 호출하지 않는다.

```sh
clayfarm update check
clayfarm update download
clayfarm update apply --yes
```

서버를 아직 `control.json`에 저장하지 않았다면 각 확인·다운로드 명령에
`--server https://clayfarm.myknow.xyz`를 붙인다. 다운로드된 wheel은
`<home>/updates/`에 저장되고 manifest의 공개키, 대상 OS/아키텍처, 파일 크기와 SHA-256을
모두 확인한 뒤에만 설치한다. `update apply`는 현재 Python 환경에 `pip --no-index
--no-deps`로 설치하고 새 프로세스에서 `clayfarm_control.__version__`을 확인한다. 동의
프롬프트를 건너뛰려면 명시적으로 `--yes`를 지정해야 한다.

업데이트 서명키는 운영자에게 지문을 별도 채널로 확인한 뒤 한 번만 등록한다.

```sh
clayfarm trust add --key-id control-release --public-key-file release.pub
clayfarm trust list
```

현재 운영키의 공개 부분은 [`keys/control-release.pub`](../keys/control-release.pub)이며
SHA-256 지문은 `f6788c70db6ec16537f7fdc116a98dbb7fe18a22a75854dc1fe3630ede6427e8`이다.
지문을 별도 채널에서 확인한 뒤 다음처럼 등록한다.

```sh
clayfarm trust add --key-id control-release --public-key-file keys/control-release.pub
```

키가 등록되지 않았거나 manifest·wheel이 변조되면 CLI는 설치하지 않고 오류를 반환한다.
실패한 다운로드는 보존되며, 운영자가 보관한 이전 signed wheel을 지정해 다시 적용할 수
있다. 자동 롤백이나 백그라운드 설치는 수행하지 않는다.

## 운영자 릴리스

먼저 새 버전을 올리고 wheel을 만든다.

```sh
python scripts/bump_version.py 0.4.1
python -m build --wheel
CLAYFARM_UPDATE_PRIVATE_KEY='(보안 저장소에서 주입)' \
  python scripts/create_control_release.py dist/clayfarm_control-0.4.1-py3-none-any.whl \
  --version 0.4.1 --sequence 2 --key-id control-release \
  --artifact-path artifacts/clayfarm_control-0.4.1-py3-none-any.whl \
  --output updates/manifests/control-0.4.1.json \
  --note 'CLI 업데이트 경로 추가'
```

wheel은 manifest의 `artifact.path`와 같은 상대 경로로 API 서버의 update root에 복사한다.
기본 서버 실행 경로는 `~/.clayfarm-control/updates`이며, manifest는
`updates/manifests/*.json`, wheel은 `updates/artifacts/*.whl` 아래에 둔다. `control serve`가
시작할 때 고정 release trust를 사용해 서명과 파일 hash를 다시 검사한다. `/v1/updates/check`는
대상 플랫폼에 맞는 가장 높은 버전을 반환하고, `/v1/updates/artifacts/{release_id}`는
검증된 manifest가 가리키는 파일만 전송한다.

`CLAYFARM_UPDATE_PRIVATE_KEY`와 대응하는 공개키는 저장소·로그·채팅에 기록하지 않는다.
sequence는 감소시키지 않으며 같은 sequence에 다른 내용의 manifest를 재사용하지 않는다.
