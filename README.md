# Instagram Radar

## 올리기
1. GitHub의 빈 `instagram-radar` 저장소에서 **uploading an existing file**을 눌러 `app.py`, `requirements.txt`를 업로드합니다.
2. Streamlit Community Cloud에서 GitHub 저장소와 `app.py`를 선택합니다.
3. **Advanced settings → Secrets**에 `APIFY_TOKEN = "실제_토큰"`을 넣습니다. 토큰은 GitHub에 업로드하지 않습니다.
4. Deploy 후 검색합니다.

## 주의
- 1회 실행에 여러 Actor 호출이 발생합니다. 호출당 비용 상한은 계정 전체 월 예산 상한이 아닙니다.
- 해시태그별 수집은 전체 인스타그램 검색, 국가 판정, 인기순 검색을 보장하지 않습니다.
- 릴스 조회수·팔로워 수를 확보하지 못하면 검증 결과에 포함하지 않습니다.
- 이미지/캐러셀은 조회수가 아닌 좋아요 대비 팔로워 비율을 사용합니다.
- Actor 입력 형식이 바뀌거나 Apify에서 차단될 수 있어, API 연동 후 소량 테스트가 필요합니다.
