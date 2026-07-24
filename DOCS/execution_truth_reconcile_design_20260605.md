# 실행/회계 근본 해결 설계 — broker 단일 진실원(reconcile) 아키텍처
작성: 2026-06-05 / 목적: 실체결 0건·phantom 누적·유령 포지션의 **단일 근본** 해결 (임시 패치 종결)
상태: 설계 확정용 / 구현은 broker 가동(장중) 시 단계적·검증 후

---

## 0. 한 줄 정의
**시스템 상태(보유·카운트·캡·코드)가 "주문 의도(발행/송신/ACK)"로 만들어지고 "broker 실체결(chejan/계좌)"과 맞추는 닫힌 루프가 없다. → 의도와 현실이 드리프트하며 phantom 누적·유령·오판이 반복.**

근본 해결 = **broker 실계좌 = 단일 진실원(SoT)**. 모든 상태를 거기서 파생/reconcile.

---

## 1. 증거 (오늘 6/5 — 전부 같은 뿌리의 가지)
| 증상 | 메커니즘 | 같은 뿌리 |
|---|---|---|
| PULLBACK count phantom | rt_risk pullback_count = '발행' 셈 (체결 아님) | 의도 셈 |
| DUPLICATE phantom | daily_codes = '신호 쓴 코드' 셈 | 의도 셈 |
| daily_total 캡 phantom (rc=-95) | 송신 성공 시 가산, 미체결 해제 안 함 → 179만 점유, 실보유 0 | 의도 셈 |
| 007390 유령 | ACK 타임아웃→'실패' 오판인데 broker는 체결 → rt_open 누락 | 체결 캡처 불신뢰 |
| limbo | STEP7이 bridge 새 수락 때만 → 큐 잔류 후보 미처리 | 의도 흐름, 체결 무관 |
| chejan_events 0건 | 체결 이벤트 저장조차 안 됨 | SoT 부재 |

→ **rt_open_positions조차 broker 실계좌와 불일치** (buy_sender '인지' 기준, ACK 오판 시 드리프트).

---

## 2. 설계 — broker 단일 진실원 + 파생

### 키스톤: 계좌 동기화기 (Position Reconciler)
- 신규 `CORE/COLLECT/reconcile_positions_from_broker_v1.py` (또는 broker_gateway 내 주기 태스크)
- **broker opw00018(실보유: 코드·수량·평단) 조회 → rt_open_positions를 broker 진실로 덮어씀.**
  - broker_client.balance_tr("opw00018") 사용 (whitelist에 이미 있음).
  - strategy 라벨은 기존 rt_open 보존(merge) — broker엔 전략 메타 없음. 수량·평단은 broker 진실 우선.
- 주기: ①pipeline 매 사이클(또는 N분) ②매수/매도 발주 직후(이벤트). 09:00~15:30.
- 효과: 유령(007390류) 자동 편입, ACK 오판 드리프트 자동 치유, 미체결 송신 자동 소멸.
- 안전: broker 조회 실패 시 기존 rt_open 유지(fail-safe), 락 공유(매도엔진/buy_sender와 동시쓰기 조율).

### 모든 게이트가 SoT(=rt_open=broker 진실)에서 파생
오늘 이미 reconcile하도록 만든 부품들이 **SoT가 진실이 되면 자동 정확**:
- rt_risk pullback_count → min(발행, **실보유 PULLBACK**) (적용됨)
- DUPLICATE → **실보유** 시만 차단 (적용됨)
- daily_total 캡 → min(누적, **실보유 가치**) (적용됨)
→ 게이트 개별 재작성 불필요. **SoT 신뢰성만 확보하면 됨** (오늘 패치 = 이 구조의 부품).

### 주문 생명주기 신뢰성 (실체결 자체)
- **ACK 타임아웃 시 '실패' 단정 금지** → broker 실체결(opw00018/chejan) 확인 후 판정.
  - 체결됨 → SUCCESS로 정정(유령 방지). 미체결 → 안전 재시도/취소.
- **chejan(OnReceiveChejanData) 캡처·persist** → IPC/chejan_events 또는 fills ledger 기록 → 체결 진실의 실시간 소스.
- 동시호가(15:20+) 발주는 660s ACK 대기(어제 적용)와 정합.

### limbo (실행 흐름)
- pipeline STEP7을 bridge rc=200이어도 큐 미체결 BUY행 있으면 드레인 (오늘 적용, 내일 발효).
- 근본적으론 "큐=미체결 의도, SoT=체결"이라 큐를 SoT로 reconcile(체결분 큐 제거)도 검토.

---

## 3. 구현 단계 (broker 가동 시, 검증 우선)
1. **P1 — Position Reconciler (키스톤)**: opw00018→rt_open 동기화기. broker 살아있을 때 dry-run(조회만, 비교 로그) → 일치 확인 → 쓰기 활성. schtask 또는 pipeline STEP.
2. **P2 — ACK 생명주기**: 타임아웃 시 broker 체결조회 후 판정. 유령/중복 종결.
3. **P3 — chejan 캡처**: OnReceiveChejanData → fills ledger. 실시간 체결 소스.
4. **P4 — 게이트 SoT 일원화 점검**: count/codes/cap이 전부 reconcile된 rt_open 참조하는지 감사. 중복/누락 제거.
5. **P5 — 큐 reconcile**: 체결된 코드 큐에서 제거, limbo 구조 정리.

각 단계 독립 적용·env 토글·백업·py_compile·검증 후 다음.

---

## 4. 검증 계획
- **Reconcile 정확성**: opw00018 실보유 vs rt_open 차이 0 (dry-run 며칠 로그).
- **유령 재발 0**: ACK 오판 케이스에서 reconciler가 자동 편입하는지.
- **캡/카운트 정확**: 미체결 송신 후 실보유 0이면 캡/카운트 0으로 복원되는지.
- **실체결**: P1+P2 후 PULLBACK/EOD_PICK 첫 실체결 + 중복 0.
- **회귀**: score_eod 8·PULLBACK 선별·매도 무영향.

## 5. 리스크 / 안전장치
- broker 조회 부하/stall: 주기 조절(N분), 실패 시 fail-safe(기존 유지).
- 동시쓰기(reconciler vs buy_sender/매도): 파일 락 공유.
- broker 진실 우선이 전략 메타(strategy) 덮을 위험: 수량·평단만 broker, 메타는 merge 보존.
- 과도한 자동치유가 의도된 상태 덮을 위험: dry-run 선검증 + env 단계 활성.

## 6. 오늘 패치의 위치
오늘 적용분(count/codes/cap reconcile, stale 필터, limbo, hoga, EOD 매도 실거래, 테마 rescue/tilt)은 **버릴 게 아니라 이 구조의 부품**:
- reconcile 패치들 = "SoT에서 파생" 원칙의 선구현 (SoT 신뢰성[P1]이 받쳐주면 완성).
- limbo·hoga = 실행 신뢰성[P2/P5]의 일부.
→ 근본(P1 SoT)이 서면 임시가 정식이 됨.

## 7. 관련
- 메모리: stockbot-20260604-eodpick-ack-timeout-ghost-fill(유령), -capital-ssot-daily-cap(캡), stockbot-20260605-pullback-phantom-gates-fillreconcile(count/codes/limbo)
- broker IPC: DOCS/broker_ipc_schema.md, broker_client.balance_tr(opw00018)
- 어제 ACK 660s 동시호가 대기(ghost-fill 메모) = P2의 일부 선적용.
