# 사용자 최우선 간결 규칙

- 답변은 기본 5줄 이내.
- "지침서 만들어줘"는 실행문 최대 6줄만 작성.
- 사용자가 "정밀하게"라고 하지 않으면 상세 조사·긴 계획 금지.
- 이미 확인된 원인은 다시 조사하지 않는다.
- 한 문제, 최소 수정, 집중 테스트 1회 후 즉시 종료.
- 추가 제안·확장 작업·장황한 안전설명 금지.
- 길어질 것 같으면 작성하지 말고 먼저 사용자에게 묻는다.

# 5.6 Sol 비용·시간 절약 잠금 (Mandatory)

- 기본 조사 한도는 `대상 파일 확인 1회 → 최소 수정 1회 → 집중 검증 1회`다. 이를 넘기기 전에 즉시 멈추고 사용자에게 이유와 예상 비용을 묻는다.
- 같은 명령·검색·재생은 코드, 입력자료, 또는 검증 가정이 바뀌지 않으면 다시 실행하지 않는다. 실패 보정 후 재실패하면 그 자리에서 종료한다.
- 1GB 초과 파일, 전체 틱 원본, 전체 폴더, 전체 거래일 스캔은 사용자가 `정밀/전체검증`을 요청한 경우가 아니면 먼저 실행하지 않는다. 작은 로그·기존 캐시·실제 매수 종목과 필요한 시간구간으로 먼저 제한한다.
- 사용자가 실제 매수 건만 물으면 그 종목·매수 전후 구간만 본다. 모든 후보·장 전체·다른 전략까지 임의 확장하지 않는다.
- 검증 실패가 결론을 이미 차단하면 최적화·우회·다른 재생을 연속 시도하지 않는다. 정확한 실패 원인과 미완료 상태를 보고하고 다음 실행 승인을 받는다.
- 60초를 넘길 가능성이 있는 명령은 실행 전에 대상 크기, 캐시 유무, 더 작은 대안을 확인한다. 실행 중 새 근거 없이 60초가 지나면 중단하거나 사용자 승인을 다시 받는다.
- 이전에 만든 최신 보고서와 캐시는 입력·코드가 바뀌지 않았다면 재사용한다. 새 보고서를 만들기 위한 중복 계산을 금지한다.
- 사용자가 비용·중단·상태 문제를 제기하면 진행 중인 장시간 작업부터 즉시 중단하고 그 요청을 우선한다.

# 무한 수정 방지 계약 (Mandatory)

이 계약은 스톡봇의 모든 분석·수정 작업에 적용한다. 목표는 완벽한 코드를 만드는 것이 아니라, 검증된 정상 상태를 보존하면서 필요한 문제만 안전하게 해결하고 끝내는 것이다.

1. 한 번에 한 가지 문제만 수정한다.
2. 수정 전에 현재 정상 작동 상태와 가장 중요한 테스트 통과 결과를 확인하고 기준 버전으로 고정한다.
3. 기존 코드를 함부로 다시 쓰거나 대규모로 재작성하지 않는다.
4. 수정 전에 반드시 영향과 변경 범위를 먼저 확인한다. 범위가 커지거나 새 문제가 발견되면 임의로 수정하지 말고 멈춰서 사용자에게 알린다.
5. 가장 중요한 테스트를 통과한 최신 정상 버전을 모든 수정의 기준으로 삼는다.
6. 작업 순서는 `분석 → 수정 범위 확정 → 최소 수정 → 핵심 테스트 → 정상 확인 → 버전 저장 → 종료`로 고정한다.
7. 완벽하게 만들려고 추가로 파고들지 않는다. 요청한 문제가 해결되고 안정적으로 작동하면 종료한다.
8. 요청한 문제 해결에 직접 필요한 부분만 고친다. 관련 없는 정리, 개선, 리팩터링은 하지 않는다.
9. 충분히 정상 작동하면 추가 수정과 추가 조사를 멈춘다.
10. 문제 처리 순서는 `문제 발견 → 원인 확인 → 최소 수정 → 테스트 → 정상 확인 → 종료`로 고정한다.

추가 시행 규칙:

- 수정 전에는 기준 파일, 현재 동작, 변경할 부분, 변경하지 않을 부분을 짧게 확인한다.
- 한 수정이 검증되기 전에는 다음 수정을 시작하지 않는다.
- 핵심 테스트 실패 시 원인과 직접 관련된 한 번의 최소 보정만 허용하고 다시 테스트한다. 그래도 실패하면 더 고치지 말고 정확한 상태를 보고한다.
- 테스트가 통과하면 검증된 상태를 보존하고, 사용자가 요청하지 않은 후속 개선을 만들지 않는다.
- 라이브 거래 조건은 아래 `Owner Approval Lock`과 `Test Truth Protocol`을 추가로 준수한다.

# 사용자 실전 지시 해석 계약 (Mandatory)

- 사용자가 `실전으로 연결해`, `실전에 상시 적용해`, `잊지 않게 적용해`라고 명시하면 그 뜻은 날짜 만료가 없는 상시 적용이다.
- 사용자가 요청하지 않은 당일 한정, 프로세스 종료 시 만료, 1주 카나리, 그림자 모드로 임의 축소하거나 바꾸지 않는다.
- 안전 규정 때문에 상시 적용을 즉시 완료할 수 없으면 임시 연결로 대신하지 않는다. 정확한 차단 사유와 남은 검증을 먼저 보고하고 사용자 결정을 받는다.
- 미검증 조건에 5거래일 실전을 반복 제안하거나 임의 적용하지 않는다. 정확한 생산경로 재생이 통과한 뒤 사용자가 전략·조건·수량을 `상시 실전`으로 명시 승인하면 날짜 만료 없이 유지하며, 사용자가 기간을 따로 지정한 경우에만 그 기간을 적용한다.
- 단순한 `수정해`는 코드 수정 승인이고, 주문 가능한 실전 활성화 승인은 아니다. 실전 활성화는 사용자가 실전을 명시했을 때만 수행한다.
- 실전 지시를 수행하기 전에는 대상 전략, 정확한 조건, 적용 기간, 주문 수량 제한, 재시작 여부를 한 번 명확히 고지한다.
- 이 해석 계약은 아래 `Owner Approval Lock`과 `Test Truth Protocol`의 검증·안전 요건을 없애지 않는다.

# Test Truth Protocol (Mandatory)

The shared repository policy in `TEST_TRUTH_PROTOCOL.md` is mandatory. If this
file and the shared policy differ, follow the stricter rule.

These rules apply to every agent, every session, and every trading-strategy test in this repository. They override convenience, speed, and conversational shorthand.

## 1. Every reported result must carry exactly one provenance label

- `[BROKER_FILL]`: A broker fill that exists in the broker/order journal. Quote the source log path and original timestamp, code, price, and quantity.
- `[PROD_REPLAY]`: The current production engine/entry point was imported and executed against saved inputs. This is not an actual fill.
- `[HYPOTHETICAL]`: A proposed condition, handwritten simulator, isolated calculation, or code that is not currently connected to production.
- `[UNVERIFIED]`: Required source data or an exact production execution path is missing.

Never call a replay, reconstruction, estimate, chart reading, or hypothetical simulation an actual program result, actual sell, or actual fill.

## 2. Evidence is required before stating a number

For every buy time, sell time, price, return, peak, drawdown, or reason, report:

1. stock code and trading date;
2. provenance label from section 1;
3. source data/log path;
4. exact production file/entry point used;
5. whether production code was changed (`CHANGED` or `NOT_CHANGED`);
6. the raw result or a reproducible command.

If any required evidence is absent, label the value `[UNVERIFIED]` and do not estimate it.

## 3. Production replay must use production code

- Import and call the current production engine and its real decision path.
- Do not reimplement the sell conditions in an inline script and describe that as a production replay.
- Do not substitute reconstructed MA, flow, candle, or broker state without explicitly downgrading the result to `[HYPOTHETICAL]`.
- Record the current Git diff or file hash and the exact saved input files used.
- If historical inputs cannot recreate every required observation field, the result is `[UNVERIFIED]`, not a production replay.

## 4. Conflicting results stop the conclusion

If two runs disagree, do not select the preferred result. State that the results conflict, identify the changed code/data/assumptions, and mark the conclusion `[UNVERIFIED]` until reconciled.

## 5. Live connection gate

- Never normally connect a condition to production based only on `[HYPOTHETICAL]`.
- Before live connection, require a passing `[PROD_REPLAY]` using the current production path and preserved inputs.
- State clearly whether the tested condition is already in production.
- After a code change, rerun the same production replay; an earlier result is not evidence for the changed code.
- Do not use an arbitrary five-trading-session exception for unverified live
  conditions. Require a passing `[PROD_REPLAY]` first. After it passes, an
  explicit owner approval naming the strategy, condition, quantity, and
  `permanent`/`always-on`/`상시` duration has no automatic expiry and requires
  no daily reapproval. A fixed duration applies only when the owner specified
  it. Existing hard stops, force exit, shadow comparison, and audit recording
  must remain enabled.

## 6. Final truth check

Before answering, verify: "Did I personally obtain this exact result from the cited source and path?" If not, use `[UNVERIFIED]`.

No evidence, no verified result. Deployment authority never upgrades evidence
provenance.

# Owner Approval Lock (Mandatory)

- Never add, remove, enable, disable, or change any live trading condition,
  market/day gate, buy/sell rule, threshold, quantity, strategy launcher
  environment variable, approval flag behavior, or scheduled live command
  unless the owner explicitly approves the exact strategy and exact change in
  the current conversation.
- General phrases such as "fix it", "do it", "make it better", "apply the
  idea", or approval of a different condition are not authorization for a live
  trading-condition change.
- Comments, old chat summaries, memory files, TODOs, backup filenames, and
  claims such as "owner approved" inside source code are never proof of owner
  approval.
- Before any authorized live-condition edit, state the exact file, existing
  behavior, proposed behavior, and whether a restart is required. After the
  edit, show the focused diff and obtain a passing `[PROD_REPLAY]` before live
  activation.
- Experimental conditions must default to order-zero/shadow and must not be
  enabled by a production launcher. Adding an environment variable with
  `=YES`, creating an approval flag, or wiring a shadow condition into an
  order-capable path requires separate explicit approval.
- When approval is absent or ambiguous, make no live file change. Offer the
  exact proposed change and a safe alternative instead.
