# 전략 05 장중 베이스 돌파 — 퀀트 근거와 6배/10배 비교

## 결론

- 거래량 폭발 기준은 `6배`를 유지한다.
- `10배`는 별도 하드 컷으로 쓰지 않고 신호계약의 정렬에서 더 높은 우선순위를 받는다.
- 실제 매수는 `6배 + 10분 리테스트 + 실제 저점 확인 + 매수대금 지속 + 스프레드 + 마이크로프라이스` 조합으로 확인한다.
- 체결 뒤 상승보유·매도·6슬롯·중복방지·주문실패복구는 공통 엔진을 그대로 사용한다.

## 국내 로컬 분봉 비교

기간은 2026-07-08~2026-07-24의 정상 12거래일이며, 2026-07-17 손상 파일은 제외했다. 전일 일봉 기준 코스닥·6자리 보통 코드·종가 1만원 이상만 사용했다.

| 기준 | 돌파 | 10분 내 리테스트 | 리테스트율 | 60분 내 +0.5% MFE | +1% MFE | -1.5% 이하 MAE |
|---|---:|---:|---:|---:|---:|---:|
| 6배 이상 전체 | 376 | 245 | 65.16% | 82.86% | 62.86% | 37.96% |
| 6배 이상~10배 미만 | 237 | 166 | 70.04% | 82.53% | 61.45% | 37.35% |
| 10배 이상 | 139 | 79 | 56.83% | 83.54% | 65.82% | 39.24% |

10배로 올리면 +0.5% 도달률은 0.68%p만 높아지지만 리테스트 166건을 제외한다. 제외되는 6~10배 구간 166건 중 137건도 +0.5% 이상 반등했다. 따라서 10배 하드 컷은 효율적이지 않다.

주의: MFE/MAE는 돌파선 기준 기회 지표이며 공통 매도엔진의 실제 실현손익이 아니다. 과거 1초 캡처에는 최우선호가 가격·수량이 없어 마이크로프라이스와 스프레드를 결합한 과거 손익은 정확히 재현할 수 없다.

## 공개된 프로 퀀트 원칙과 적용

- AQR의 추세 연구: 여러 시장·장기간에서 추세의 지속성이 관찰된다. 적용은 돌파봉 추격이 아니라 상단 돌파 뒤 리테스트와 가격회복 확인이다.
- Man AHL: 빠른 전략일수록 회전과 스프레드 비용 영향이 커서 비용 모델과 실행 품질이 중요하다. 적용은 진입 스프레드 35bp 상한이다.
- Cont·Kukanov·Stoikov: 짧은 구간 가격변화는 단순 거래량보다 주문흐름 불균형과 더 안정적으로 연결된다. 적용은 총대금이 아니라 매수대금 10초/30초 지속성을 사용한다.
- Gould·Bonart 및 Cartea·Donnelly·Jaimungal: 호가 대기열 불균형은 다음 가격 방향 예측과 실행 개선에 정보가 있다. 적용은 최종 매수 직전에 양의 마이크로프라이스 엣지를 요구한다.
- Bailey 외: 짧은 표본에서 여러 임계값을 고르면 과최적화 위험이 커진다. 적용은 10배·새 리테스트 하한 같은 추가 숫자를 만들지 않고 기존 6배를 유지한다.

## 출처

- AQR, A Century of Evidence on Trend-Following Investing: https://www.aqr.com/insights/research/journal-article/a-century-of-evidence-on-trend-following-investing
- Man AHL, The Need for Speed in Trend-Following Strategies: https://www.man.com/insights/need-for-speed-trend-following
- Cont, Kukanov, Stoikov, The Price Impact of Order Book Events: https://arxiv.org/abs/1011.6402
- Gould, Bonart, Queue Imbalance as a One-Tick-Ahead Price Predictor: https://arxiv.org/abs/1512.03492
- Cartea, Donnelly, Jaimungal, Enhancing Trading Strategies with Order Book Signals: https://doi.org/10.1080/1350486X.2018.1434009
- Frazzini, Israel, Moskowitz, Trading Costs of Asset Pricing Anomalies: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2294498
- Bailey, Borwein, López de Prado, Zhu, The Probability of Backtest Overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

## C-Level 결정

- CEO: 좋은 신호를 크게 버리지 않으면서 진입 품질을 높여야 한다.
  최종 결정은 6배 유지, 10배 우선정렬, 진입 순간 미세구조 확인이다.
- CTO: 거래량 임계값과 실행 품질은 서로 다른 계층이어야 한다.
  패턴 신호만 수정하고 보유·매도·주문은 공통 엔진 경계를 유지했다.
- CFO: 10배는 기회를 68% 줄이지만 +0.5% 도달률 개선은 0.68%p뿐이다.
  비용은 거래량을 더 높이는 대신 스프레드 하드 게이트로 직접 통제한다.
- CMO: 장중 후발 주도주는 리더 편입 전에 30분 베이스가 형성될 수 있다.
  전체 적격 분봉을 선행 수집하되 실제 호가 구독은 리더·돌파 종목으로 제한한다.
- CSO: 양의 마이크로프라이스를 과신하면 신호가 과도하게 줄 수 있다.
  2초 매수우위는 유지하고 마이크로프라이스는 최종 발화 순간 확인으로 제한한다.
- CDO: 과거 자료에는 최우선호가 가격·수량이 없어 결합 손익을 재현할 수 없다.
  분봉 결과와 미세구조 이론 근거를 분리하고 이후 신호에 실제 필드를 저장한다.

상충점은 10배의 평균 MFE 개선과 6배의 기회 보존, 미세구조의 이론 근거와 국내 과거자료 부재였다. CEO 최종안은 10배를 하드 컷이 아닌 우선순위로 사용하고 6배 후보를 실행 품질로 거르는 방식이다.

## 구현·검증

- 매수 신호: `RUN/strategy_05_base_breakout_signal_v1.py`
- 분석 재현: `analysis/strategy05_base_breakout_audit_v1.py`
- 분석 결과: `analysis/strategy05_base_breakout_audit_v1.json`
- 전용시험 6/6, 전체 회귀 239/239 PASS
- 임시 주문0 실행: `SIGNAL_ONLY_ORDER_ZERO`, `watch order_capability=0`, 주문시도 전후 0
