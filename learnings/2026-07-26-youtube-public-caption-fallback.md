# [2026-07-26] YouTube 공개 자동자막 빈 응답 우회

## 접근법
1. 채널 RSS에서 제목이 정확히 일치하는 영상 ID를 확인한다.
2. 영상 페이지의 `captionTracks`로 자동자막 존재 여부와 언어를 확인한다.
3. 웹용 `api/timedtext`가 HTTP 200과 빈 본문을 반환하면 같은 요청을 반복하지 않는다.
4. 공개 Innertube `player` 응답을 IOS 클라이언트 문맥으로 조회해 새 자막 URL을 얻는다.
5. 자막 URL에 `fmt=json3`를 붙여 시간 구간별 텍스트만 추출하고, 요약에는 원문 전체가 아니라 매매 조건과 한계만 사용한다.

## 되지 않은 것 + 이유
- 웹 페이지에서 얻은 `api/timedtext` URL 직접 호출: 자막 트랙은 있었지만 본문이 0바이트였다.
- `get_transcript` 엔드포인트 직접 호출: 공개 파라미터를 사용해도 `FAILED_PRECONDITION`이 반환됐다.
- 동일 URL의 포맷만 XML/JSON/VTT로 변경: 접근 조건이 같아 모두 빈 본문이었다.

## 재사용 규칙
YouTube 웹 자막 URL이 200/빈 본문이면 포맷 변경을 반복하지 말고, 공개 플레이어의 다른 클라이언트 문맥에서 자막 URL을 새로 받아라.

## 관련 파일/명령
- 영상: https://www.youtube.com/watch?v=8j-C8Ec_OLk
- PowerShell `Invoke-RestMethod`
- YouTube 공개 `youtubei/v1/player` 응답
