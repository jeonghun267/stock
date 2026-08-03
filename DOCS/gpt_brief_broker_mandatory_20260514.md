# SAFE+ 스톡봇 — broker mandatory 화 설계 요청 (2026-05-14)

## 1. 프로젝트 개요

Windows 데스크탑 기반 한국 주식 자동매매 봇.
- 키움증권 OpenAPI+ (`KHOPENAPI.KHOpenAPICtrl.1` OCX) 사용
- Python 3.10 32bit + PyQt5 (QAxWidget)
- 다중 프로세스 구조:
  - `pipeline_runner.py` (메인 데몬, OCX 미사용)
  - `collect_prices_1m_kiwoom_opt10080_v4_16.py` (1분봉 수집기 + OCX)
  - `siga_sell_strategy.py` (SIGA 매도 엔진 + OCX, Task Scheduler)
  - `kiwoom_buy_order_sender_v4_9.py` (매수 주문 sender + OCX)
  - `rt_sell_engine_v3_19.py` (실시간 매도 엔진 + OCX)
  - `pullback_sell_strategy_v4_21_FIXED.py` (PB 매도, 현재 collector shared_ocx 경유)
  - `collect_eod_daily_bars_v2_4_SAFEPLUS_FINAL.py` (EOD 일봉 + OCX, Task Scheduler 16:05)
  - `collect_investor_daily_opt10059_v1_SAFEPLUS_FINAL.py` (투자자 일별 + OCX, 09:00 부팅 1회)
  - `broker_gateway_v1.py` (OCX Ownership Firewall 시도, 현재 부분 구현)
- 각 OCX 프로세스는 자체 `CommConnect()` 호출 → **별도 LOGIN popup 발생**

---

## 2. 핵심 문제 — LOGIN popup 폭주

키움 OpenAPI+ 정책: **각 프로세스마다 별도 OCX 인스턴스 → 별도 LOGIN 필요**. Windows COM 객체 핸들 프로세스 간 상속 불가.

### 2026-05-14 실측: popup 13회 발생

```
09:00:20 collector LOGIN (자연 부팅)
09:14:34 SIGA sell LOGIN (워치독 재시작)
09:15:40 collector ensure_login 재호출
09:06   SIGA sell 재시작
... (이후 패치 작업 + freeze 응급 처리로 누적)
12:00:16 SIGA sell PID 5904 LOGIN
12:04:27 broker LOGIN
12:??:?? collector PID 6344 LOGIN
```

### 정상 운영 시 (패치/응급 없을 때)
- 09:00 자연 부팅 시 4회 (investor / pipeline → SIGA sell / collector + 자체 ensure_login)
- 사용자가 매번 LOGIN popup 클릭 + 비밀번호 입력 필요

### AUTO 자동로그인 차단됨
- 키움 OpenAPI+ 트레이 아이콘에 "계좌비밀번호 저장" / "AUTO 로그인 설정" 메뉴가 **표시되지 않음**
- 환경 문제 추정 (메모리 [openapi_auto_setup] 5/13 검증)
- 사용자가 K1 시도했으나 트레이 메뉴 자체 접근 불가 → AUTO 영구 봉인 상태

---

## 3. 시도한 해결책 — `broker_gateway_v1.py`

### 본래 설계 철학 (코드 헤더 명시)

```
설계 철학:
  Broker는 "새 시스템"이 아니다.
  Broker는 SAFE+ 전체를 보호하는 "OCX Ownership Firewall" 역할만 수행.
  Kiwoom OCX/CommConnect는 이 프로세스만 독점 — 다른 모듈은 직접 OCX 호출 금지.
```

= **broker mandatory 화 = LOGIN 1회 = popup 영구 차단**.

### 현재 진행: STEP-1 + 부분 STEP-2 (40% 완성)

#### broker 가 **하는 것** (구현됨)

| # | 기능 | IPC 타입 | 위치 |
|---|---|---|---|
| 1 | OCX 1개 보유 + LOGIN 유지 | (자체) | L417, L436 |
| 2 | 일반 TR 위임 (SetInputValue + CommRqData + OnReceiveTrData) | `TR` | `_handle_tr_request` L979 |
| 3 | GetConnectState 위임 | `STATE` | `_handle_state_request` L744 |
| 4 | GetLoginInfo (계좌번호) 위임 | `ACCOUNT_INFO` | `_handle_account_info_request` L772 |
| 5 | Chejan 데이터 → IPC broadcast (단방향, 7개 FID) | (자동) | `_on_receive_chejan_data` L513 |
| 6 | DisconnectRealData 위임 | `DISCONNECT_SCR` | `_handle_disconnect_scr_request` L924 |
| 7 | 잔고 TR (whitelist: opw00001/4/18) | `BALANCE_TR` | `_handle_balance_tr_request` L906 |
| 8 | broker_heartbeat.json 5s 주기 작성 | (자체) | L372 write_heartbeat |
| 9 | PING / SHUTDOWN | `PING` / `SHUTDOWN` | L702 / L962 |
| 10 | IPC 폴링 500ms (`IPC/requests/*.json` glob) | (자체) | `poll_requests` L1084 |

#### broker 가 **못 하는 것** (mandatory 화 필요 미구현)

| # | 기능 | 현재 상태 | 사용자 의도 영향 |
|---|---|---|---|
| **A** | **실제 SendOrder (매수/매도 주문 집행)** | **SHADOW 모드만** — broker는 SendOrder를 호출하지 않고 단순 IPC 로깅만. 실주문은 sub-process direct OCX (`SENDORDER_SHADOW` L799 명시: "broker 가 실제 SendOrder 호출하지 않음 (중복 주문 방지)") | ★★★★★ — 매수/매도 모듈 4개 모두 자체 OCX 보유 강요 |
| **B** | **SetRealReg (실시간 시세 등록)** | 핸들러 없음. SIGA sell `register_rt()` L2073 이 자체 OCX `SetRealReg` 호출 | ★★★★★ — 매도 엔진 자체 OCX 필요 |
| **C** | **OnReceiveRealData → IPC broadcast** | 콜백 미연결 | ★★★★★ — 실시간 가격/체결 데이터 sub-process 분배 불가 |
| **D** | **GetCommRealData (실시간 데이터 추출)** | IPC 위임 없음 | ★★★★ |
| **E** | TR throughput 최적화 (batch / worker thread) | single-thread 500ms 폴링, 12s tr_loop blocking | ★★★ — 5/14 S1 rollback 사유 |
| **F** | Watchdog freeze 자동 감지 | broker 자체에 self-watchdog 없음 | ★★ |
| **G** | 다중 broker fallback / failover | 단일 broker 만 | ★★ (SPOF 위험) |

---

## 4. 메모리 정책 충돌 (재검토 필요)

### 5/13 작성된 정책 (현재 무효화 필요)

`[project_stockbot_20260513_step2i3_broker_optional_policy]`:
- "broker mandatory 화 영구 금지"
- "SAFE+ 정체성 = 개인형 direct OCX 매매 + broker 보조 관측 layer"
- 근거: SPOF 위험, OMS 거절

### 5/14 사용자 의도 (정책 정정)

- "AUTO 설정 안 돼서 broker 만든 거잖아"
- "broker 로 다 통합해서 할려고"
- = **broker mandatory 화 = popup 영구 차단** (본래 broker 설계 의도와 일치)

→ **5/13 정책이 잘못 작성됨**. broker 의 진짜 목적 (popup 차단) 보다 SPOF 위험만 강조. 5/14 popup 폭주 직접 경험 후 사용자 의도 명확화.

---

## 5. 모듈별 OCX 호출 패턴 (현재)

| 모듈 | OCX 보유 | CommConnect | SendOrder | SetRealReg | OnReceiveReal | OnReceiveChejan | TR | GetLoginInfo | DisconnectRealData |
|---|---|---|---|---|---|---|---|---|---|
| `broker_gateway_v1` | ✅ 자체 | ✅ 자체 | (SHADOW만) | ❌ | ❌ | ✅ broadcast | ✅ | ✅ | ✅ |
| `collect_prices_1m_v4_16` | ✅ 자체 | ✅ 자체 | ❌ | ✅ 자체 | ✅ 자체 | ❌ | ✅ 자체 (S1 rollback 후) + broker IPC fallback (opt10059) | ❌ | ✅ 자체 |
| `siga_sell_strategy` | ✅ 자체 | ✅ 자체 | ✅ 자체 (실주문) | ✅ 자체 | ✅ 자체 | ✅ 자체 | ❌ | ❌ | ❌ |
| `kiwoom_buy_order_sender` | ✅ 자체 | ✅ 자체 | ✅ 자체 (실주문) | ❌ | ❌ | ✅ 자체 | ❌ | broker IPC fallback | ❌ |
| `rt_sell_engine_v3_19` | ✅ 자체 | ✅ 자체 | ✅ 자체 (실주문) | ❌ | ❌ | ✅ 자체 | ❌ | broker IPC fallback | ❌ |
| `pullback_sell_strategy_v4_21` | shared_ocx (collector 경유) | (생략) | ✅ collector OCX 경유 | (collector) | (collector) | ✅ shared | ❌ | ❌ | ❌ |
| `collect_eod_daily_bars` | ✅ 자체 | ✅ 자체 | ❌ | ❌ | ❌ | ❌ | ✅ 자체 | ❌ | ❌ |
| `collect_investor_daily_opt10059` | ✅ 자체 | ✅ 자체 | ❌ | ❌ | ❌ | ❌ | ✅ 자체 | ❌ | ❌ |

**→ 동시 OCX 보유 프로세스 = 최대 7개**. 각각 LOGIN popup 1회씩.

---

## 6. 사용자 의도 (mandatory 화 완성 후 목표 상태)

| 모듈 | OCX 보유 |
|---|---|
| `broker_gateway_v1` | ✅ **유일** (1개) |
| 나머지 모든 모듈 | ❌ 모두 broker IPC 경유 |

→ **LOGIN 1회 / 일 = popup 0~1회** (AUTO 차단 환경에서 최선).

---

## 7. broker mandatory 화 풀 계획 — STEP-3 단계

| 단계 | 패치 | 코드 변경 | 위험 | 작업일 추정 |
|---|---|---|---|---|
| **STEP-3.0** | broker 미구현 기능 추가: 실제 SendOrder + SetRealReg + OnReceiveRealData broadcast + GetCommRealData | broker_gateway_v1.py +800줄 | 중 (SendOrder 중복 주문 위험 = 기존 SHADOW 정책 폐기 + idempotency key 도입) | 3~5일 |
| **STEP-3.1** | SIGA sell engine OCX 제거 → broker IPC 전환 (SendOrder + SetRealReg + Chejan broadcast 구독) | siga_sell_strategy.py ~300줄 | 중 (매도 즉사 위험) | 2~3일 |
| **STEP-3.2** | buy_order_sender OCX 제거 → broker IPC SendOrder | kiwoom_buy_order_sender_v4_9.py ~200줄 | 중 | 1~2일 |
| **STEP-3.3** | investor_daily broker IPC 전용 | ~50줄 | 낮음 | 0.5일 |
| **STEP-3.4** | collect_eod_daily_bars broker IPC | ~100줄 | 낮음 | 1일 |
| **STEP-3.5** | collector opt10080 broker IPC 재진입 (S1 rollback 해제) + IPC throughput 영구 해결 (batch TR / worker thread) | collect_prices_1m + broker 각 ~250줄 | **큼** (S1 rollback 한 이유 = throughput 병목, 영구 해결 필요) | 1주 |
| **STEP-3.6** | rt_sell_engine_v3_19 broker IPC | ~150줄 | 중 | 1~2일 |
| **STEP-3.7** | broker self-watchdog + 다중 broker fallback | ~200줄 | 중 (SPOF 완화) | 1~2일 |

**총 약 2~3주 사이클**. 단계별 검증 사이클 필요.

---

## 8. 핵심 기술 과제 (GPT 설계 요청)

### Q1: SendOrder 중복 주문 방지
- 현재 SHADOW 정책 = "broker가 SendOrder 호출 안 함, sub-process가 호출". 이게 broker 의 실 주문 회피 이유.
- mandatory 화 시 sub-process 가 SendOrder 못 함 → broker 가 호출해야 함.
- 문제: IPC 응답 timeout 시 sub-process 가 재요청 → broker 가 2번 SendOrder 호출 = 중복 주문 = 자산 손실
- 해결 후보:
  - (a) Idempotency key (request_id 기반 dedup, broker 측 TTL cache)
  - (b) Sub-process 측 "응답 못 받아도 절대 재요청 안 함" + broker 측 ACK 보장
  - (c) ?

### Q2: 실시간 데이터 IPC broadcast
- SetRealReg / OnReceiveRealData / GetCommRealData 가 broker 에 위임됨
- 실시간 시세는 초당 수십~수백건 발생 (체결 1분봉 종목별)
- File-based IPC (현재 broker 방식) 는 throughput 한계
- 해결 후보:
  - (a) Named pipe / Unix socket / TCP socket
  - (b) shared memory (mmap)
  - (c) ZeroMQ / Redis
  - (d) File-based 유지 + batch broadcast (1초 묶음)

### Q3: TR throughput 영구 해결
- 현재 broker tr_loop.exec_() blocking 12s + 500ms polling + 60종목 시 +30s overhead
- 해결 후보:
  - (a) Worker thread + queue (Python GIL 한계 — OCX 는 메인스레드 affinity 필요)
  - (b) Batch TR (`opt10080_batch codes=[...]` 1회 요청에 N종목)
  - (c) async/await Qt event loop
  - (d) 다중 broker (각 broker 다른 OCX, OCX 동시 ≥3 시 BEX 위험)

### Q4: broker SPOF 완화
- broker 1개 = 단일 실패점
- 해결 후보:
  - (a) broker watchdog (process 모니터 + 자동 재시작)
  - (b) hot-standby broker (active + standby 2개)
  - (c) sub-process 측 graceful degradation (broker dead 시 대기, 자동 복구 시 재개)

### Q5: 변경 격리 / 점진 적용
- 한 번에 모든 모듈 변경 = 검증 사이클 어려움
- 단계별 적용 + 각 단계 rollback 가능해야 함
- 단계별 우선순위 권장:
  - 1순위: STEP-3.0 (broker 미구현 기능 추가) — 모든 sub-process 변경의 전제
  - 2순위: STEP-3.3 / STEP-3.4 (작고 안전한 모듈 먼저)
  - 3순위: STEP-3.1 / STEP-3.2 / STEP-3.6 (매도/매수 엔진)
  - 4순위: STEP-3.5 (collector throughput 병목 영구 해결)
  - 5순위: STEP-3.7 (SPOF 완화)

---

## 9. 환경 / 제약

| 항목 | 값 |
|---|---|
| OS | Windows 10 Pro 19045 |
| Python | 3.10 32bit (`C:\Python310-32\python.exe`) — 키움 OCX 32bit 강제 |
| Qt | PyQt5 (QAxWidget for OCX) |
| 작업 디렉토리 | `C:\stock_bot` |
| Git | 5/6 초기화, baseline 커밋 3ea2676 |
| 사용자 환경 | 키움 OpenAPI+ AUTO 자동로그인 미설정 (트레이 메뉴 접근 불가) |
| 매수 chain 현황 | 15일 연속 매수 0건 (funnel collapse) |
| 매도 엔진 | SIGA sell freeze 재현성 100% (5/14 G1+G4 패치로 진단 강화 + crash 변환) |

---

## 10. GPT 에 요청

### 요청 사항
1. **STEP-3 풀 설계** — 각 단계별 코드 변경 위치 + 의존 관계 + 검증 절차
2. **Q1~Q4 기술 과제 해결책** — 위의 후보 중 선택 + 구체 구현 방식
3. **broker IPC 프로토콜 정의** — 새 IPC 타입 (SETREAL_REG / SEND_ORDER / REAL_DATA_SUB / GET_COMM_REAL) payload schema
4. **SendOrder idempotency 보장 방식**
5. **단계별 적용 순서 + rollback 전략**
6. **위험 평가 + 검증 체크리스트**

### 제공 가능한 추가 정보 (요청 시)
- broker_gateway_v1.py 전수 (1201줄)
- siga_sell_strategy.py 전수 (2932줄)
- 각 sub-process 코드
- 메모리 누적 (5/14 28번째 패치까지)
- 키움 OpenAPI+ API 문서 (요청 시 검색)

---

## 11. 협업 흐름 (사용자 지시)

1. 이 브리핑 → 사용자가 GPT 에 전달
2. GPT 설계 답변 → 사용자가 Claude (나) 에 전달
3. Claude 가 코드 구현 + 문제 설명
4. Claude 가 의문 사항 → 사용자가 GPT 에 재질의
5. 반복

---

## 부록 A. 현재 가동 중인 프로세스 (5/14 12:05 기준)

| PID | 모듈 | 시작 시각 | 상태 |
|---|---|---|---|
| 5904 | siga_sell_strategy.py | 11:59:56 | ✅ polling (G1+G4 발효) |
| 5208 | watchdog_siga_sell (P3+G1+G4) | 11:59:26 | ✅ 정상 |
| 11276 | broker_gateway_v1.py | 12:04:27 | ✅ LOGIN 완료 |
| 6344 | collect_prices_1m_v4_16 (P2+Q1+Q4+S1+G5) | 12:03:?? | LOGIN 대기/완료 |

## 부록 B. 적용된 패치 (5/14 누적 28건)

| # | 패치 | 종류 |
|---|---|---|
| 24 | S1-ROLLBACK (broker IPC 우회) | 임시방편 |
| 25 | P2-LOGIN-CLAMP (popup 9→1) | 임시방편 |
| 26 | P3-FREEZE-KILL (워치독 사후 kill) | 임시방편 |
| 27 | Q1+Q4 (TOP_N 30 + dead_pool 자동 리셋) | 임시방편 |
| 28 | G1+G4+G5 근본 진단 + ensure_login 빈도 감소 | 영구 (부분) |
| H1+H2 | SIGA polling 30s + 워치독 timeout 90s | 영구 |
| P4 | broker 부팅 체인 추가 (ps1) | 영구 |
| P5 | collector / SIGA 워치독 Task Repetition 15분 | 영구 |
| F1 | SIGA sell 응급 kill | 운영 |
