# [2026-07-26] 기존 실전 골짜기를 중복주문 없이 S03 골짜기 급반등으로 교체

## 접근법
1. 기존 골짜기와 S03의 프로세스, 안전플래그, Windows 예약작업을 읽어 동시 실매수 가능성을 확인한다.
2. 기존 `valley_hunter_live_ledger.json`, 공통 포지션, S03 상태를 대조하고 브로커 잔고·미체결 조회 실패를 0으로 간주하지 않는다.
3. `valley_off.flag`를 먼저 생성하고 기존 골짜기 관련 예약작업 5개를 백업한 뒤 Disabled로 전환한다.
4. S03 승인파일을 만들거나 `strategy_03_off.flag`를 제거하지 않은 채 신호·회전 예약작업만 등록한다.
5. Windows CMD의 한글 경로 파싱과 격리형 Python의 로컬 import 차단을 ASCII 실행기 두 개로 우회한다.
6. S03·S01·S02·공통 회귀 48개와 실제 Windows 예약작업 실행을 확인하고 주문시도 0을 재검증한다.

## 하지 않은 것 + 이유
- S03 실전 승인파일 생성과 OFF 제거는 하지 않음. 이유: Codex가 실계좌 승인을 대신하지 않으며 새 호가 필드는 장중 실데이터 검증 전이기 때문이다.
- 기존 골짜기 코드와 예약작업을 삭제하지 않음. 이유: Disabled와 OFF만으로 중복주문을 차단하면서 XML 백업과 등록정보를 이용한 복구 가능성을 유지하기 위해서다.
- 주말의 `BROKER_NOT_ALIVE`를 잔고·미체결 0으로 해석하지 않음. 이유: 조회 불가는 무보유 증거가 아니므로 fail-closed 상태를 유지해야 한다.

## 재사용 규칙
실전 엔진을 교체할 때는 기존 엔진을 OFF·Disabled로 먼저 격리하고 새 엔진을 승인없음·OFF 상태에서 예약 실행 검증한 뒤 사용자 수동 승인 단계로 넘겨라.

## 관련 파일/커밋
- `config/valley_off.flag`
- `RUN/strategy_03_valley_signal_launcher_v1.py`
- `RUN/strategy_03_rotation_launcher_v1.py`
- `RUN/hidden/SAFEPLUS_STRATEGY03_SIGNAL_ASCII.cmd`
- `RUN/hidden/SAFEPLUS_STRATEGY03_LIVE_ASCII.cmd`
- `RUN/install_strategy03_tasks.ps1`
- `DOCS/새전략_목록.md`
