# broker_gateway_v1 IPC Schema (2026-05-14)

`C:\stock_bot\RUN\broker_gateway_v1.py` 의 IPC request/response payload 정의.

## 공통 구조

### Request payload (client → broker)

모든 request 는 `IPC/requests/{request_id}.json` 에 작성. broker 가 500ms 폴링.

공통 필드:
- `request_id` (str, uuid4) — client 가 생성
- `ts` (ISO8601) — client 가 작성 시각
- `ttl_sec` (int, optional, default 30) — TTL, broker 측 만료 검사
- `type` (str) — IPC type (아래 16종)
- 그 외 type 별 추가 필드

### Response payload (broker → client)

`IPC/responses/{request_id}.json` 에 작성. client 가 200ms 폴링.

공통 필드:
- `request_id` (str)
- `ts` (ISO8601)
- `status` (str): `"OK"` | `"ERROR"` | `"TIMEOUT"`
- `data` (dict | null) — status=OK 시 채워짐
- `error` (str | null) — status≠OK 시 채워짐

---

## IPC Type 정의 (17종)

### 1. `PING` — broker 생존 확인

| Request | Response |
|---|---|
| `{"type": "PING"}` | `{"data": {"pong": true, "state": "<BrokerState>"}}` |

### 2. `STATE` — GetConnectState 위임

| Request | Response |
|---|---|
| `{"type": "STATE"}` | `{"data": {"connected": true/false, "raw": <int>, "broker_state": "..."}}` |

### 3. `ACCOUNT_INFO` — GetLoginInfo 위임

| Request | Response |
|---|---|
| `{"type": "ACCOUNT_INFO", "tag": "ACCNO"}` | `{"data": {"tag": "ACCNO", "value": "6502...", "accounts": "..."}}` |

`tag`: `"ACCNO"` (계좌목록) / `"USER_ID"` / `"USER_NAME"` / `"GetServerGubun"` 등.

### 4. `TR` — 일반 TR 위임 (SetInputValue + CommRqData + OnReceiveTrData)

| Field | Type | 비고 |
|---|---|---|
| `tr_code` | str | 필수 (예: "opt10081") |
| `rqname` | str | optional (default `{tr_code}_req`) |
| `screen_no` | str | optional (default "0001") |
| `next_flag` | int | 0=첫 페이지, 2=연속 조회 (Z2/N2) |
| `input` | dict | SetInputValue 호출 인자 (key=한글필드명, value=값) |
| `output_fields` | list[str] | 응답 추출할 컬럼 한글명 |

Response data:
```json
{
  "tr_code":      "opt10081",
  "screen_no":    "0101",
  "record_name":  "...",
  "prev_next":    "0" | "2",
  "record_count": <int>,
  "records":      [{<field>: <value>, ...}, ...],
  "ts":           "..."
}
```

### 5. `BALANCE_TR` — 잔고/미체결 TR (whitelist 5종)

Whitelist: `opw00001` / `opw00004` / `opw00018` / `opt10075` / `opw00009`

payload schema = `TR` 와 동일. broker 가 whitelist 검사 후 `_handle_tr_request` 위임.

### 6. `MASTER_INFO` — 마스터 함수 위임 (whitelist 4종)

Whitelist: `GetCodeListByMarket` / `GetMasterCodeName` / `GetMasterStockInfo` / `GetMasterETF`

| Request | Response |
|---|---|
| `{"type": "MASTER_INFO", "func": "<func>", "arg": "<value>"}` | `{"data": {"func": "...", "arg": "...", "value": "..."}}` |

`GetMasterETF` 의 경우 `value` 는 int (0=비ETF, 1=ETF).

### 7. `KOA_FUNCTIONS` — KOA_Functions 위임 (whitelist 6종)

Whitelist:
- `GetServerGubun` (arg="") — 서버 구분
- `GetCodeListByMarket` (arg=market) — MASTER_INFO 와 중복
- `ShowAccountWindow` (arg="") — **계좌비밀번호 저장창 호출 (K1 우회 시도)**
- `GetMasterStockState`
- `GetUpjongCode`
- `GetAPIModulePath`

| Request | Response |
|---|---|
| `{"type": "KOA_FUNCTIONS", "func": "<func>", "arg": "<value>"}` | `{"data": {"func": "...", "arg": "...", "value": "..."}}` |

### 8. `SETREAL_REG` — SetRealReg 위임 (실시간 시세 등록)

| Field | 비고 |
|---|---|
| `screen_no` | 필수 |
| `code_list` | 필수 (세미콜론 구분) |
| `fid_list` | 필수 (세미콜론 구분, 예: "10;13;15;16;27;28") |
| `real_type` | "0"=신규, "1"=추가 |

Response: `{"data": {"screen_no": "...", "code_list": "...", "fid_list": "...", "real_type": "...", "ret": <int>}}`

성공 시 broker 측 `broker_state.json` 영속 저장 (Z2 state replay 용).

### 9. `SET_REAL_REMOVE` — SetRealRemove 위임

| Request | Response |
|---|---|
| `{"type": "SET_REAL_REMOVE", "screen_no": "9001", "code": "035720" \| "ALL"}` | `{"data": {"screen_no": "...", "code": "...", "removed": true}}` |

`code="ALL"` 시 화면 전체 해제 + `broker_state.json` 갱신.

### 10. `SET_REAL_REMOVE_ALL` — SetRealRemove("ALL","ALL") 단축

| Request | Response |
|---|---|
| `{"type": "SET_REAL_REMOVE_ALL"}` | `{"data": {"removed": "ALL"}}` |

`broker_state.json` 전체 초기화.

### 11. `GET_COMM_REAL_DATA` — GetCommRealData 단건 풀

| Request | Response |
|---|---|
| `{"type": "GET_COMM_REAL_DATA", "code": "035720", "fid": 10}` | `{"data": {"code": "...", "fid": 10, "value": "..."}}` |

### 12. `GET_REAL_REG_GRP` — GetRealRegGroup (등록 화면 목록)

| Request | Response |
|---|---|
| `{"type": "GET_REAL_REG_GRP"}` | `{"data": {"value": "9001;9002;..."}}` |

### 13. `DISCONNECT_SCR` — DisconnectRealData 위임

| Request | Response |
|---|---|
| `{"type": "DISCONNECT_SCR", "screen_no": "0001"}` | `{"data": {"screen_no": "...", "disconnected": true}}` |

### 14. `SENDORDER_SHADOW` — SHADOW only (실 SendOrder 미호출)

Field:
- `account`, `code`, `qty`, `price`, `order_type`, `screen_no`, `rqname`, `hoga_gb`, `origin_order_no`, `engine`

Response: `{"data": {"shadow": true, "engine_to_broker_ms": <float>, "broker_write_ms": <float>}}`

Side effect: `IPC/order_shadow/{request_id}.json` 작성. 실 SendOrder 호출 안 함.

**용도**: sub-process direct OCX SendOrder 가 이미 발화한 상태에서 latency 진단 + 감사 로그.

### 15. `SENDORDER_REAL` — 실 SendOrder 집행 + idempotency (Z1)

| Field | Type | 비고 |
|---|---|---|
| `idempotency_key` | str | **필수**. 같은 key 재요청 시 broker cache 응답 |
| `rqname` | str | optional |
| `screen_no` | str | 필수 |
| `account` | str | 필수 |
| `order_type` | int | 1=매수 / 2=매도 / 3=매수취소 / 4=매도취소 / 5=매수정정 / 6=매도정정 |
| `code` | str | 필수 |
| `qty` | int | 필수 (>0) |
| `price` | int | optional (시장가=0) |
| `hoga_gb` | str | "00"=지정가 / "03"=시장가 / ... (14종 whitelist) |
| `origin_order_no` | str | 정정/취소 시 원주문번호 |

Response:
```json
{
  "status": "OK",
  "data": {
    "ret": <int>,       // 0=정상, ≠0=키움 거부
    "code": "035720",
    "qty": 10,
    "order_type": 1,
    "rqname": "...",
    "screen_no": "...",
    "ts": "..."
  }
}
```

**Idempotency**: 같은 `idempotency_key` 로 5분 내 재요청 시 broker 가 cache 응답 즉시 반환 (실 SendOrder 미호출). 중복 주문 자산 손실 방지.

### 16. `BATCH_TR` — 다종목 일괄 TR (Phase 1.1 2026-05-14)

**목적**: collector opt10080 의 IPC overhead 영구 해결.
단일 TR 호출 시 IPC write+poll = ~350~500ms 종목당. 60종목 = +30s 사이클.
BATCH_TR 시 IPC 1회만 (request 1 + response 1) + broker 측에서 N회 OCX 호출 직렬.
**효과**: IPC overhead = N × 350ms → 1 × 350ms = 사이클당 ~20s 절감 추정.

| Field | Type | 비고 |
|---|---|---|
| `tr_code` | str | 필수 (예: "opt10080") |
| `codes` | list[str] | 필수, 종목 코드 리스트 (non-empty) |
| `rqname_template` | str | optional (default `{tr_code}_req`) |
| `screen_no_rotate` | list[str] | optional 화면번호 rotate (default `["0001"]`) |
| `input_template` | dict | SetInputValue dict. value 에 `"{CODE}"` 포함 시 종목 코드 자동 치환 |
| `output_fields` | list[str] | 응답 추출 컬럼 한글명 |
| `next_flag` | int | 0=첫, 2=연속 (모든 종목 일관) |
| `per_request_timeout_sec` | float | 종목당 timeout (default 5.0) |
| `batch_timeout_sec` | float | batch 전체 timeout (default 60.0) |

Response data:
```json
{
  "results": [
    {"code": "035720", "status": "OK", "data": {<TR data>}, "error": null},
    {"code": "005930", "status": "TIMEOUT", "data": null, "error": "per_request_timeout 5.0s"},
    ...
  ],
  "summary": {
    "total":       60,
    "ok":          55,
    "timeout":     3,
    "error":       2,
    "elapsed_sec": 38.2,
    "aborted":     false
  }
}
```

**Heartbeat 보호**: `BATCH_TR_HB_INTERVAL=5` 종목당 1회 broker write_heartbeat() 강제 호출 → batch 중 broker dead 오판 차단.

**Partial result**: batch_timeout 발생 시 처리분 + 미처리분 (status=ERROR) 모두 반환.

**사용 예** (collector opt10080 Phase 3):
```python
res = bc.batch_tr(
    tr_code="opt10080",
    codes=top_n_codes,
    input_template={"종목코드": "{CODE}", "틱범위": "1", "수정주가구분": "0"},
    output_fields=["체결시간", "시가", "고가", "저가", "현재가", "거래량", "거래대금"],
    screen_no_rotate=["2001","2002","2003","2004","2005"],
    per_request_timeout_sec=5.0,
    batch_timeout_sec=60.0,
)
```

### 17. `SHUTDOWN` — Graceful shutdown

| Request | Response |
|---|---|
| `{"type": "SHUTDOWN"}` | `{"data": {"shutdown": true, "state": "SHUTDOWN"}}` |

broker 측: 응답 작성 후 100ms 후 `QApplication.quit()` 호출 + lock 제거.

---

## Broadcast (단방향, sub-process 구독)

broker → IPC 디렉토리에 신규 event 파일 작성. sub-process 가 폴링 후 자기 등록 종목/event만 처리.

### A. `IPC/chejan_events/{event_id}.json` — Chejan (체결/잔고)

```json
{
  "event_id":            "uuid",
  "ts":                  "ISO8601 (broker write 완료)",
  "ts_broker_callback":  "ISO8601 (OnReceiveChejanData 진입)",
  "ts_subscriber_consume": "" (subscriber 가 채움),
  "gubun":               "0",
  "fid_data": {
    "9203": "주문번호",
    "913":  "주문상태",
    "9001": "종목코드",
    "911":  "체결수량",
    "910":  "체결가",
    "902":  "미체결수량",
    "905":  "주문구분"
  }
}
```

### B. `IPC/real_data/{event_id}.json` — 실시간 시세

```json
{
  "event_id":  "uuid",
  "ts":        "ISO8601",
  "code":      "035720",
  "real_type": "주식체결" | "주식호가잔량" | ...,
  "fid_data": {
    "10": "현재가",
    "11": "전일대비",
    "12": "등락율",
    "13": "누적거래량",
    "15": "거래량",
    "16": "시가",
    "17": "고가",
    "18": "저가",
    "27": "(최우선)매도호가",
    "28": "(최우선)매수호가"
  }
}
```

**Throttle**: 종목당 100ms (GPT-FIX-2). 초과 콜백 drop.

### C. `IPC/msg_events/{event_id}.json` — 시스템 메시지

```json
{
  "event_id":  "uuid",
  "ts":        "ISO8601",
  "screen_no": "...",
  "rqname":    "...",
  "tr_code":   "...",
  "msg":       "주문 가능 시간이 아닙니다"
}
```

### D. `IPC/order_shadow_ack/{event_id}.json` — Order ACK/FILL relay

```json
{
  "event_id":           "uuid",
  "ts_broker_relay":    "ISO8601",
  "ts_broker_callback": "ISO8601",
  "gubun":               "0",
  "fid_data":            {...},
  "order_no":            "...",
  "state":               "접수" | "체결" | ...,
  "code":                "035720",
  "filled_qty":          "...",
  "filled_price":        "...",
  "remain_qty":          "...",
  "order_direction":     "1=매수 / 2=매도"
}
```

### E. `IPC/order_shadow/{event_id}.json` — SendOrder SHADOW mirror

SENDORDER_SHADOW payload 그대로 저장 + `ts_broker_receive` + `engine_to_broker_ms` 추가.

---

## 청소 정책 (N1)

| 디렉토리 | TTL |
|---|---|
| `IPC/chejan_events/` | 300s |
| `IPC/order_shadow/` | 300s |
| `IPC/order_shadow_ack/` | 300s |
| `IPC/responses/` | 300s |
| `IPC/requests/` | 300s |
| `IPC/msg_events/` | 300s |
| `IPC/real_data/` | 300s |

`broker_heartbeat.json` 5s 주기로 `_cleanup_old_chejan_events()` 자동 호출.

---

## rqname → request_id Mapping (Phase 1.2 2026-05-14)

broker `self.tr_pending_rqname` dict — 관측/진단 + 미래 worker thread 확장 base.

```
{
  "opt10081_req": {"request_id": "<uuid>", "start_ts": <epoch>},
  "opt10059_req": {"request_id": "<uuid>", "start_ts": <epoch>},
  ...
}
```

- `_handle_tr_request` 진입 시 등록
- 동일 rqname 이미 pending 시 `[RQMAP]` WARN 로그 (현 single-thread 라 발생 불가)
- `_handle_tr_request` 끝 시 finally 블록에서 정리 (해당 request_id 일치 시만)

**현재 효과**: race detect 진단 (single-thread 라 실 race 0).
**미래 효과**: worker thread 확장 시 buffer key 를 `(rqname, request_id)` 로 마이그레이션 base.

---

## 상태 머신 (BrokerState)

```
DISCONNECTED → CONNECTING → LOGIN_WAIT → CONNECTED
                                    ↓
                                SHUTDOWN (graceful)
                                    ↓
                                (process exit)

CONNECTED ⇄ RATE_LIMIT (현재 미사용)
```

set_state 시 reason 인자 (N20) 로 변화 이유 명시 가능:
- `set_state(BrokerState.SHUTDOWN, reason="signal:SIGTERM")`
- `set_state(BrokerState.CONNECTING, reason="connect_kiwoom 진입")`

---

## broker_state.json (Z2 state replay)

```json
{
  "realreg": {
    "9300": {
      "code_list": "035720;005930",
      "fid_list":  "10;13;15;16;27;28",
      "real_type": "0",
      "ts":        "ISO8601"
    },
    ...
  },
  "ts": "ISO8601"
}
```

broker 재시작 시 LOGIN 성공 후 자동 `_replay_realreg()` 실행 → sub-process 측 변경 없이 SetRealReg 복원.

---

## 관련 파일

- 서버: `C:\stock_bot\RUN\broker_gateway_v1.py` (~1700줄)
- 클라이언트: `C:\stock_bot\RUN\broker_client.py` (~400줄, broker_client.BrokerClient class)
- 상태 영속: `C:\stock_bot\DATA\broker_state.json` (Z2)
- 단일 실행 lock: `C:\stock_bot\DATA\broker_gateway.lock`
- heartbeat: `C:\stock_bot\IPC\broker_heartbeat.json`
- 로그: `C:\stock_bot\LOG\broker_journal.log` (10MB × 5 backup)
