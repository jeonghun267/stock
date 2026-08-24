# STEP-3 sub-process 마이그레이션 사이클 사전 설계 (2026-05-15+)

## 개요

5/14 broker_gateway_v1 100% 완성 (read-only + Z1 SendOrder + Z2 state replay). sub-process 5개가 자체 OCX 보유 = LOGIN popup 매 spawn 시 발생. 본 사이클 목표 = **모든 sub-process broker IPC 경유 + popup 0~1회/일 달성**.

## 목표

| 지표 | 5/14 baseline | 5/15+ 마이그레이션 후 |
|---|---|---|
| OCX 보유 프로세스 | 6개 (broker + collector + SIGA sell + buy + rt_sell + investor/EOD) | **1개 (broker 만)** |
| LOGIN popup / 일 | 11회 (5/14 실측) → 3회 (5/15 부팅 체크리스트 예상) | **1회 (broker)** |
| broker mandatory 화 | 0% (전 sub-process direct OCX) | **100%** |
| funnel collapse 회복 | 미회복 | TBD (S1 rollback 사유 = broker IPC throughput 병목, 본 사이클에서 영구 해결) |

## sub-process 분석

### 1. SIGA sell engine (`siga_sell_strategy.py`, 2932줄)

| 항목 | 위치 | broker IPC 대체 |
|---|---|---|
| QAxWidget 생성 | L2047 | **제거** (broker 보유) |
| CommConnect | L2088 | **제거** (broker LOGIN) |
| OnReceiveChejanData connect | L2064 | broker `IPC/chejan_events/` 폴링 구독 |
| OnReceiveRealData connect | L2065 | broker `IPC/real_data/` 폴링 구독 (100ms throttle) |
| OnReceiveMsg connect | L2066 | broker `IPC/msg_events/` 폴링 구독 |
| GetConnectState | L2080/2092 | `bc.state()` |
| **SetRealReg** | L2110 `register_rt()` | `bc.setreal_reg(screen_no, code, fid_list, "0")` |
| GetCommRealData | L2190 | broker `IPC/real_data/` event 의 fid_data 또는 `bc.get_comm_real_data()` |
| GetChejanData | L2247/2299/2301 | broker Chejan event 의 fid_data |
| **SendOrder** L2361/2368 (`_sell()`) | 매도 주문 | `bc.send_order_real(idempotency_key, ..., order_type=2)` |
| **SendOrder** L2409 (T1 분할) | 분할 매도 | 동일 |
| **SendOrder** L2431 (취소/정정) | 취소 | `order_type=4 / 6` |

**변경 규모**: ~400줄 (engine.__init__/login/register_rt/Chejan handler/SendOrder 8곳)
**위험**: ★★★★★ — 매도 즉사 직결, 잘못된 idempotency_key 시 자산 손실
**검증 필수**: 모의계좌 + 단계별 1주

### 2. buy_order_sender (`kiwoom_buy_order_sender_v4_9.py`, 3990줄)

| 항목 | 위치 | broker IPC 대체 |
|---|---|---|
| QAxWidget 생성 | L3458 | **제거** |
| OnReceiveChejanData | L3460/3472 | broker IPC 구독 |
| OnReceiveTrData | L3461/3473 | broker `bc.tr()` 응답 |
| CommConnect | L3517 | **제거** |
| **SendOrder** (`send_order()` 추정) | 매수 주문 | `bc.send_order_real(..., order_type=1)` |
| SetInputValue / CommRqData | L3596~ | `bc.tr()` 또는 `bc.balance_tr()` (잔고 조회) |
| GetCommData | (TR 응답) | broker response.records |

**변경 규모**: ~250줄
**위험**: ★★★★ — 매수 차단 위험 (단 5/14 매수 0건 = 회복 chain 시점에 발효 시도)

### 3. rt_sell_engine (`rt_sell_engine_v3_19.py`, ~1500줄)

| 항목 | 위치 | broker IPC 대체 |
|---|---|---|
| QAxWidget 생성 | L1240 | **제거** (단 shared_ocx 옵션 보존) |
| CommConnect | L1245 | **제거** |
| OnReceiveChejanData | L1227/1242 | broker IPC 구독 |
| GetChejanData | L1264/1270 | broker Chejan event fid_data |
| GetConnectState | L1243/1286 | `bc.state()` |
| GetLoginInfo | L1307 | `bc.account_info()` |
| **SendOrder** | L1335 | `bc.send_order_real(..., order_type=2)` |

**변경 규모**: ~200줄
**위험**: ★★★★ — 매도 (PullbackSell 이중 백업)

### 4. collector opt10080 (`collect_prices_1m_v4_16.py`, 3300줄)

| 항목 | 위치 | broker IPC 대체 |
|---|---|---|
| QAxWidget 생성 | L1111 | **제거** (단 PB sell unified 호스트라 이 부분이 핵심 위험) |
| CommConnect | L2367 | **제거** |
| broker_tr_request 호출 | L2470 (opt10080) / L1558 (opt10059) | **이미 구현** — S1 rollback 만 해제 |
| ensure_login | L2312~ | **제거** (broker IPC mode 시) |
| **PB sell shared_ocx** | L3025/3168 | **★ 핵심 충돌** — PB sell 이 collector OCX 공유 중. broker mandatory 화 시 PB sell 도 broker IPC 로 마이그레이션 필수 |

**변경 규모**: ~300줄 (S1 rollback 해제 + ensure_login 제거 + PB sell hosting 제거)
**위험**: ★★★★★ — broker IPC throughput 병목 영구 해결 필요 (S1 rollback 한 이유). 본 사이클에서 동시 해결:
- Batch TR (opt10080_batch codes=[...]) — broker 측 신규 IPC type
- 또는 worker thread (broker)
- 또는 client 측 parallel request (file IPC 한계로 어려움)

### 5. PB sell (`pullback_sell_strategy_v4_21.py`)

| 항목 | 현재 | broker IPC 대체 |
|---|---|---|
| OCX | shared_ocx (collector 호스트, STEP-2H-1) | broker IPC 로 변경 (collector 변경과 동시) |
| SendOrder | collector OCX 경유 L1335 | `bc.send_order_real(..., order_type=2)` |
| Chejan | shared_ocx | broker IPC 구독 |

**변경 규모**: ~150줄
**위험**: ★★★ — 매도 (SIGA + rt_sell 백업 존재)

## 단계별 적용 순서

### Phase 1: 인프라 준비 (5/15~5/17, 2~3일)

| Step | 작업 | 위험 | 효과 |
|---|---|---|---|
| 1.1 | broker `BATCH_TR` IPC type 신규 — collector opt10080 multi-code 처리 (~150줄 broker 측) | 중 | throughput 영구 해결 기반 |
| 1.2 | broker `OnReceiveTrData` rqname mapping table (GPT 9번) — 동시 다중 rqname race 차단 | 중 | 다중 client 지원 |
| 1.3 | broker_client.py 에 batch_tr / chejan_subscribe / realdata_subscribe / msg_subscribe wrapper 추가 | 저 | sub-process 측 마이그레이션 단순화 |
| 1.4 | **Paper load test** — broker RealData broadcast 60종목 1시간 부하 측정 | 저 (실시간 X) | 실측 throughput / disk I/O 검증 |

### Phase 2: 저위험 sub-process 마이그레이션 (5/18~5/19, 2일)

| Step | 작업 | 위험 | 발효 |
|---|---|---|---|
| 2.1 | **PB sell engine — collector shared_ocx → broker IPC** (먼저 변경) | 중 (매도 백업 SIGA + rt_sell) | 5/19 09:00 자연 부팅 |
| 2.2 | PB sell paper trade 1일 검증 (모의계좌) | 0 | — |

### Phase 3: collector opt10080 (5/20~5/24, 1주)

| Step | 작업 | 위험 | 발효 |
|---|---|---|---|
| 3.1 | collector `_is_broker_alive` S1 rollback 해제 (1줄 제거) | ★★★★ | — |
| 3.2 | collector `_request_1m_once` broker `BATCH_TR` 사용으로 전환 (배치 단위) | ★★★★★ | — |
| 3.3 | collector PB sell hosting 코드 제거 (PB sell 이미 broker IPC 사용 가정) | 중 | — |
| 3.4 | collector ensure_login 제거 (broker mandatory 모드) | 중 | — |
| 3.5 | **단계별 검증 사이클 3일** — 매일 EOD 후 funnel collapse / dead_pool / popup / cycle 시간 측정 | 0 | — |

### Phase 4: 매도 엔진 마이그레이션 (5/25~5/27, 3일)

| Step | 작업 | 위험 | 발효 |
|---|---|---|---|
| 4.1 | **SIGA sell engine 마이그레이션** | ★★★★★ | 5/26 09:06 자연 부팅 |
| 4.2 | SIGA sell paper trade 2일 검증 (모의계좌) | 0 | — |
| 4.3 | **rt_sell_engine 마이그레이션** | ★★★★ | 5/27 09:00 |
| 4.4 | rt_sell paper trade 1일 검증 | 0 | — |

### Phase 5: 매수 엔진 마이그레이션 (5/28~5/29, 2일)

| Step | 작업 | 위험 | 발효 |
|---|---|---|---|
| 5.1 | **buy_order_sender 마이그레이션** | ★★★★ | 5/29 09:00 |
| 5.2 | buy_order_sender paper trade 1일 검증 | 0 | — |
| 5.3 | 실 계좌 첫 매수 검증 (소액) | ★★★★★ | 5/30 09:00 |

## 의존 관계

```
broker BATCH_TR 추가 (1.1)
  └─→ collector opt10080 broker IPC (3.1~3.4)
        └─→ PB sell broker IPC (2.1) — collector hosting 제거 전제
  └─→ SIGA sell 마이그레이션 (4.1)
  └─→ rt_sell 마이그레이션 (4.3)
  └─→ buy_sender 마이그레이션 (5.1)
```

→ **broker BATCH_TR 신규 IPC type 이 모든 후속 작업의 전제**. Phase 1 부터 시작.

## 위험 평가 + rollback 전략

| 위험 | 대응 | rollback |
|---|---|---|
| 매도 즉사 (idempotency 버그) | broker dedup cache + client side uuid4 유일성 보장 + paper trade 2일 | `_is_broker_alive()` False 반환 1줄로 즉시 direct OCX 복귀 |
| 매수 차단 | buy_order_sender 자체 OCX path 보존 (fallback) | 동일 |
| collector funnel collapse 회귀 | S1 rollback 즉시 적용 (1줄) | 1줄 변경 |
| broker crash → 매매 정지 | Z2 state replay + broker self-watchdog (별도 진행 항목) | broker 외부 모니터링 강화 |
| broker IPC throughput 한계 | Phase 1.1 BATCH_TR + 1.4 paper load test 로 사전 검증 | direct OCX fallback |

## 검증 계획

### 매 Phase 마다
- py_compile 필수
- 모의계좌 paper trade (실거래 X)
- 부팅 popup 카운트 측정
- broker_journal / sell_log / collector_log tail
- broker_state.json (Z2 replay) 검증

### Phase 별 KPI

| Phase | KPI |
|---|---|
| 1 | broker BATCH_TR 60종목/사이클 처리 시간 < direct OCX 의 1.5배 |
| 2 | PB sell paper 100% 정상 호출 |
| 3 | collector funnel collapse 미발생 / dead_pool 안정 / popup 1회 (broker LOGIN 만) |
| 4 | SIGA + rt_sell paper 100% 정상 매도 (가상 포지션) |
| 5 | buy_sender paper 100% 정상 매수 |

### 전체 종료 KPI (5/30 시점)
- popup 1회/일 (broker LOGIN 만)
- 매매 정상 (매수 + 매도)
- broker_journal tr_count + sendorder_count 일일 통계 정상

## Timeline 요약

| 일자 | 작업 |
|---|---|
| 5/14 (오늘) | broker 100% 완성 ✅ |
| 5/15 | 5/14 패치 자연 발효 검증 |
| 5/15~5/17 | Phase 1 (broker BATCH_TR + rqname mapping + broker_client wrapper + paper load test) |
| 5/18~5/19 | Phase 2 (PB sell) |
| 5/20~5/24 | Phase 3 (collector opt10080) |
| 5/25~5/27 | Phase 4 (SIGA sell + rt_sell) |
| 5/28~5/29 | Phase 5 (buy_sender) |
| 5/30 | 실 계좌 첫 매수 검증 |

**총 사이클: 약 2주 (5/15~5/30)**

## 미해결 / 추가 검토

| 항목 | 비고 |
|---|---|
| broker SPOF 완화 (다중 broker hot-standby) | 5/30 이후 별도 사이클 |
| file IPC 장기 한계 → shared memory / named pipe | 6/15 이후 (필요 시) |
| OMS state machine 강화 (현 단순 dedup) | 5/30 이후 |
| KOA_FUNCTIONS ShowAccountWindow 실측 (AUTO 자동로그인 우회) | Phase 1 중 실측 |
| broker_client.py 의 모든 client 마이그레이션 후 sub-process 측 코드 정리 (dead path 제거) | 6/1 이후 |

## 사용자 결정 위임 항목

1. **모의계좌 사용 가능 여부** — Paper trade 단계에서 필수
2. **Phase 별 검증 사이클 길이 조정** (현재 2일~1주 추정)
3. **첫 실 계좌 매수 시 소액 한도** (현재 미정)
4. **broker SPOF 위험 수용도** — 다중 broker 도입 여부

---

## 관련 메모리

- [[project-stockbot-20260515-boot-checklist]]
- [[project-stockbot-20260514-broker-scope-policy]]
- [[project-stockbot-20260514-step33-34-broker-ipc]]
- [[project-stockbot-broker-v1-step1]]
