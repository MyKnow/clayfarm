# 구현 구조와 장애 의미론

## 흐름

```text
Codex / Claude -- 실제 concept + 고정 spec --> assetgen CLI
  --> Supabase Auth + cf_rpc + private Storage
  --> 준비된 task를 각 Worker가 Pull
       reconstruction (CUDA)
         --> process (Blender CPU + geometry QA + GLB/FBX)
           --> front / right / back / three_quarter (독립 CPU render task)
  --> caller가 result를 호출하여 contact sheet + report 수신
  --> 같은 caller가 approve 또는 새 revision job 제출
```

세션이 살아 있는 상태에서 CLI 결과가 호출자에게 반환됩니다. 종료된 Codex/Claude 세션을 자동 재개하거나 웹훅으로 임의 메시지를 주입하지 않습니다. 호출 도구의 대기 시간 제한이 `--wait`보다 짧으면 job ID를 보존해 나중에 같은 CLI로 조회합니다. 하나의 이미지 입력에서 다음 단계의 실제 데이터가 나올 때까지 종속 단계는 실행할 수 없습니다.

## 스케줄러 없이 큐를 사용한다

Postgres 트랜잭션이 후보 선택과 claim을 한 번에 수행합니다. `FOR UPDATE SKIP LOCKED`로 이미 다른 consumer가 잠근 행을 건너뜁니다. 우선순위는 preview 100, process 90, reconstruct 80입니다. 최종 검토가 준비되는 경로를 앞당기려는 초기 정책이며 최적값을 측정한 것은 아닙니다. 같은 우선순위에서는 부모 결과를 만든 노드를 선호합니다.

노드는 capability와 CPU/GPU slot을 제공합니다. 큰 GPU 추론은 노드당 1개, CPU task는 노드당 1개입니다. CPU task는 기본 2개 스레드를 사용합니다. VRAM/온도/메모리/배터리 조건을 확인한 후 claim합니다. 자원이 부족하면 다른 사용자의 프로세스를 죽이는 대신 새 작업을 받지 않습니다. 순간적인 telemetry는 외부 앱과 자원을 완전히 예약하는 수단이 아니므로 OOM을 완벽히 예방하지는 못합니다.

`compute_done`은 계산 완료와 전송 완료를 분리합니다. 로컬 결과를 durable하게 저장하고 compute slot을 비운 뒤 별도 uploader가 Storage 전송과 commit을 수행합니다. 그래서 네트워크 전송 중 같은 GPU가 다른 준비된 task를 처리할 수 있습니다. 미전송 결과가 기본 4개에 도달하면 새로운 계산을 제한해 디스크 폭주를 막습니다.

## 장애 처리

**at-least-once 실행 + 임대 토큰으로 보호된 단일 결과 확정**입니다. 중복 연산은 생길 수 있습니다. 성공한 task의 결과 포인터는 같은 task ID에 대해 덮어쓰지 않습니다.

- `attempt_id`는 새 claim마다 발급되는 UUID fencing token입니다.
- lease는 서버 시각으로 기본 120초, worker는 주기적으로 갱신합니다.
- heartbeat와 lease는 다릅니다. heartbeat가 오더라도 개별 작업의 lease가 갱신되지 않으면 만료됩니다.
- 오래된 attempt, 만료된 lease, 다른 owner, 취소된 job의 결과는 commit할 수 없습니다.
- 실행 중 전원이 꺼지면 그 단계는 다른 가용 노드에서 재실행합니다. SF3D 내부 연산을 중간 checkpoint부터 이어가는 기능은 없습니다.
- 업로드 후 DB commit 응답만 잃어버린 경우 다음 동기화가 이미 확정된 결과를 확인하고 outbox를 정리합니다.
- 로컬 완료 후 업로드 전 죽으면 SQLite journal과 result marker에서 복구합니다.
- Storage 키는 farm/user/task/attempt/content-hash 기반으로 분리합니다. 실패한 attempt의 파일이 남아도 확정 포인터는 바뀌지 않습니다.
- 기본 최대 시도 3회를 넘으면 실패하고 하위 종속 작업도 실패로 표시합니다. 데이터가 없는데 무한 재시도하지 않습니다.

동일 노드에서 worker 프로세스를 중복 시작하는 것은 OS 파일 잠금으로 차단합니다. 잠금은 프로세스 종료 시 OS가 해제합니다. PID 파일의 존재만으로 생존을 판정하지 않습니다.

## 전송과 캐시

입력은 SHA-256 캐시로 저장하고 검증합니다. 생성한 mesh도 같은 캐시에 넣어 같은 노드에서 이어지는 단계가 다시 내려받지 않도록 합니다. 다운로드 중단 시 `.part`와 HTTP Range, 업로드 중단 시 TUS 서버 offset과 로컬 업로드 URL을 사용합니다. 파일을 모두 업로드하기 전에는 task를 done으로 확정하지 않습니다.

Prefetch는 lease가 아닙니다. 미리 받은 task 때문에 다른 워커가 막히지 않습니다. `offline_speculation`을 켜면 최근에 입력을 완전히 받은 일부 task를 네트워크 없이 계산할 수 있습니다. 재연결 후 같은 불변 입력의 task를 정식 claim할 수 있을 때에만 결과를 채택합니다. 다른 노드가 이미 완료했다면 로컬 superseded로 남기고 canonical output을 덮어쓰지 않습니다.

모든 노드와 중앙 서비스 사이의 연결이 끊기면 새로운 전역 스케줄링, 최종 승인, 다른 노드의 최신 상태 확인은 불가능합니다. 캐시된 계산만 할 수 있습니다. 모든 장비가 꺼져 있으면 아무 연산도 할 수 없습니다. 이 제한을 “항상 100% 자원 활용”으로 포장하지 않습니다.

## 이 버전에서 제외한 복잡도

동적 critical-path ETA 최적화, straggler hedging, 학습 기반 노드 가용성 예측, 다중 중앙 서비스 quorum, 네트워크 단절 중 DAG 전체의 자율 진행, content-addressed 중앙 dedup/GC, 자동 cost optimizer는 없습니다. 별도 scheduler daemon을 만들지 않고 SQL claim과 로컬 admission, 제한된 prefetch만 사용합니다. 이것이 v0.1의 단순화 경계입니다.

중앙 Supabase 자체의 장애에서는 워커 outbox가 결과를 보관합니다. 중앙 DB나 Storage가 영구 소실되는 재난을 자동 복구하지는 않습니다. 운영 DB/Storage 백업과 요금제의 가용성 조건은 별도로 관리해야 합니다.
