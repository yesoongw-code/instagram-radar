import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import streamlit as st

st.set_page_config(page_title='Instagram Radar', page_icon='📸', layout='wide')
st.title('📸 Instagram Radar · 숨은 떡상 찾기')
st.caption('Apify에서 공개 게시물·릴스 후보를 수집하고 작은 계정의 높은 반응을 찾아요. 인스타그램 전체 검색이나 국적 판정은 아니에요. · v3.0')

SCRAPER = 'apify~instagram-scraper'
PROFILE = 'apify~instagram-profile-scraper'
BASE = 'https://api.apify.com/v2'

def token():
    try:
        return st.secrets.get('APIFY_TOKEN', '')
    except Exception:
        return os.getenv('APIFY_TOKEN', '')

KEY = token()
if not KEY:
    st.error('Apify 토큰이 아직 연결되지 않았어요. Streamlit 앱의 Secrets에 APIFY_TOKEN = "..."를 설정해 주세요.')
    st.stop()


def execute(actor, data, max_cost=0.10):
    url = f'{BASE}/acts/{actor}/run-sync-get-dataset-items'
    response = requests.post(url, params={'token': KEY, 'timeout': 180, 'maxItems': 250, 'maxTotalChargeUsd': max_cost}, json=data, timeout=205)
    if not response.ok:
        raise RuntimeError(f'Apify 응답 오류 ({response.status_code}). 요청 설정과 Apify 사용량을 확인해 주세요.')
    items = response.json()
    return items if isinstance(items, list) else []


def num(item, *names):
    for name in names:
        x = item.get(name)
        if isinstance(x, (int, float)) and x >= 0:
            return int(x)
    return None


def date(item):
    raw = item.get('timestamp') or item.get('takenAt')
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace('Z', '+00:00')).astimezone(timezone.utc)
        except ValueError:
            pass
    return None

PRESETS = {
    '한국': ['일상', '웃긴영상', '고양이', '육아'],
    '미국': ['funny', 'cats', 'satisfying', 'parenting'],
    '일본': ['猫', '日常', '面白い', '子育て'],
}

with st.sidebar:
    st.header('검색 설정')
    mode = st.radio('검색 방식', ['🌍 자동 떡상 발견', '🔎 주제 직접 검색'], horizontal=False)
    if mode.startswith('🌍'):
        regions = st.multiselect('탐색할 국가별 해시태그 묶음', list(PRESETS), default=['한국'])
        st.caption('국가는 검색어 묶음 이름일 뿐, 작성자의 실제 국적을 인증하지 않습니다.')
        all_tags = list(dict.fromkeys(tag for region in regions for tag in PRESETS[region]))
        st.write('검색 후보:', ', '.join('#'+x for x in all_tags) if all_tags else '국가를 선택해 주세요')
        max_tags = st.slider('이번 검색에 사용할 해시태그 수', 1, 4, 2)
        words = all_tags[:max_tags]
    else:
        query = st.text_input('검색 주제/해시태그 (쉼표로 구분)', 'cat, funny')
        words = list(dict.fromkeys(x.strip().lstrip('#') for x in query.split(',') if x.strip()))[:4]
        st.caption('최대 4개 주제까지 사용할 수 있어요. 키워드가 아니라 해시태그를 기준으로 탐색합니다.')
    kinds = st.multiselect('콘텐츠 종류', ['Reels', 'Posts'], default=['Reels'])
    per_tag = st.slider('해시태그별 콘텐츠 수집 개수', 5, 30, 10, 5)
    days = st.number_input('최근 며칠', 1, 90, 7)
    followers_limit = st.number_input('최대 팔로워', 1, 1000000, 1000)
    min_views = st.number_input('릴스 최소 조회수', 0, 100000000, 100000, 10000)
    min_ratio = st.number_input('릴스 최소 조회수/팔로워 배율', 1, 10000, 20)
    min_eng = st.number_input('이미지·캐러셀 최소 좋아요', 0, 1000000, 100, 10)
    max_accounts = st.slider('팔로워 조회 계정 상한', 1, 10, 3)
    max_usd = st.select_slider('Actor 호출 1회 비용 상한 (USD)', options=[0.01, 0.03, 0.05, 0.10], value=0.03)
    calls = len(words) * len(kinds) + max_accounts
    st.warning(f'이번 검색의 최대 요청 수: {calls}회 (게시물 {len(words)*len(kinds)}회 + 프로필 최대 {max_accounts}회). 호출별 상한을 단순 합산하면 최대 ${calls*max_usd:.2f}입니다. 실제 청구액이나 월별 계정 한도가 아닙니다.')
    run = st.button('🔎 지금 검색하기', type='primary', use_container_width=True)
    st.caption('버튼을 눌러야 수집을 시작합니다. 이 버전은 정기 자동 실행을 하지 않아요. 실행할 때마다 Apify 크레딧이 차감될 수 있어요.')

st.info('자동 발견은 미리 지정한 해시태그를 버튼 한 번으로 탐색합니다. 인기순·전체 인스타그램 검색이나 작성자 국가 검증은 제공하지 않아요.')

if run:
    if not words or not kinds:
        st.warning('최소 하나의 해시태그와 콘텐츠 종류를 선택해 주세요.')
        st.stop()
    result = []
    problems = []
    for tag in words:
        for kind in kinds:
            source = f'https://www.instagram.com/explore/tags/{tag}/'
            data = {'directUrls': [source], 'resultsType': kind.lower(), 'resultsLimit': per_tag}
            try:
                with st.spinner(f'#{tag} · {kind} 수집 중…'):
                    rows = execute(SCRAPER, data, max_usd)
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if row.get('error'):
                        problems.append(f'{tag}/{kind}: {row.get("errorDescription", row.get("error"))}')
                    else:
                        row['_kind_search'] = kind
                        row['_search_tag'] = tag
                        result.append(row)
            except Exception as e:
                problems.append(f'{tag}/{kind}: 요청 실패 ({str(e)[:150]})')
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records = {}
    for item in result:
        posted = date(item)
        if not posted or posted < cutoff:
            continue
        username = item.get('ownerUsername') or item.get('username')
        if not username:
            continue
        code = item.get('shortCode')
        url = item.get('url') or (f'https://www.instagram.com/p/{code}/' if code else '')
        if not code and not url:
            continue
        key = code or url
        if key in records:
            continue
        kind = item.get('type', '')
        plays = num(item, 'videoPlayCount', 'igPlayCount', 'videoViewCount')
        likes = num(item, 'likesCount')
        is_video = item.get('_kind_search') == 'Reels' or kind == 'Video'
        if is_video and (plays is None or plays < min_views):
            continue
        if not is_video and (likes is None or likes < min_eng):
            continue
        thumb = item.get('displayUrl') or item.get('thumbnailUrl') or item.get('display_url') or ''
        if not isinstance(thumb, str) or not thumb.startswith('https://'):
            thumb = ''
        source_tag = item.get('_search_tag', '')
        label = next((region for region, tags in PRESETS.items() if source_tag in tags), '직접 검색') if mode.startswith('🌍') else '직접 검색'
        records[key] = {'region': label, 'thumbnail': thumb, 'username': username, 'url': url, 'kind': '릴스' if is_video else ('캐러셀' if kind == 'Sidecar' else '이미지'), 'plays': plays, 'likes': likes, 'comments': num(item, 'commentsCount'), 'posted': posted.strftime('%Y-%m-%d'), 'caption': item.get('caption', '') or ''}
    candidates = list(records.values())
    candidates.sort(key=lambda x: x['plays'] if x['kind'] == '릴스' else (x['likes'] or 0), reverse=True)
    unique_users = list(dict.fromkeys(x['username'] for x in candidates))[:max_accounts]
    profiles = {}
    for user in unique_users:
        try:
            with st.spinner(f'@{user} 팔로워 확인 중…'):
                rows = execute(PROFILE, {'usernames': [user], 'resultsLimit': 1}, max_usd)
            for p in rows:
                if isinstance(p, dict) and p.get('username', '').lower() == user.lower():
                    profiles[user] = num(p, 'followersCount')
        except Exception:
            problems.append(f'프로필 @{user}: 조회에 실패했어요.')
    hits = []
    unchecked = 0
    for r in candidates:
        followers = profiles.get(r['username'])
        if followers is None:
            unchecked += 1
            continue
        if followers > followers_limit:
            continue
        base = r['plays'] if r['kind'] == '릴스' else r['likes']
        ratio = base / max(1, followers)
        if r['kind'] == '릴스' and ratio < min_ratio:
            continue
        r['followers'] = followers
        r['ratio'] = ratio
        hits.append(r)
    hits.sort(key=lambda r: r['ratio'], reverse=True)
    st.session_state['hits'] = hits
    st.session_state['unchecked'] = unchecked
    st.session_state['count'] = len(result)
    st.session_state['problems'] = problems
    st.session_state['mode_used'] = mode

if 'hits' in st.session_state:
    if st.session_state.get('problems'):
        with st.expander(f"수집되지 않은 요청 {len(st.session_state['problems'])}건"):
            for err in st.session_state['problems']:
                st.write(err)
    st.subheader(f"수집된 원본 {st.session_state['count']}건 · 확인된 조건 충족 {len(st.session_state['hits'])}건")
    st.caption(f"팔로워 정보를 확인하지 못해 판정에서 제외한 후보: {st.session_state['unchecked']}건. 상한에 걸려 조회하지 않은 계정도 포함될 수 있어요.")
    hits = st.session_state['hits']
    if hits:
        st.caption('TOP 10은 확인된 조건 충족 결과 내 순위입니다. 인스타그램 전체 순위가 아니며, 검색 표본과 계정 조회 상한에 따라 달라집니다.')
        region_options = ['전체'] + sorted({r.get('region', '미분류') for r in hits})
        col_filter, col_sort = st.columns(2)
        with col_filter:
            region_selected = st.selectbox('결과 구분', region_options)
        with col_sort:
            sort_selected = st.selectbox('정렬', ['떡상 배율 높은 순', '조회수/좋아요 많은 순', '최신 게시일 순'])
        visible = [r for r in hits if region_selected == '전체' or r.get('region') == region_selected]
        if sort_selected == '조회수/좋아요 많은 순':
            visible = sorted(visible, key=lambda r: r['plays'] if r['kind']=='릴스' else (r['likes'] or 0), reverse=True)
        elif sort_selected == '최신 게시일 순':
            visible = sorted(visible, key=lambda r: r['posted'], reverse=True)
        else:
            visible = sorted(visible, key=lambda r: r['ratio'], reverse=True)
        st.subheader('🏆 떡상 TOP 10')
        for position, r in enumerate(visible[:10], 1):
            with st.container(border=True):
                left, right = st.columns([1, 3], gap='medium')
                with left:
                    if r.get('thumbnail'):
                        try:
                            st.image(r['thumbnail'], use_container_width=True)
                        except Exception:
                            st.caption('썸네일 표시 불가')
                    else:
                        st.caption('썸네일 미제공')
                with right:
                    st.markdown(f"**{position}위 · {r['kind']} · @{r['username']}**")
                    st.caption(f"검색 묶음: {r.get('region', '미분류')} · 게시일: {r['posted']}")
                    st.markdown(f"**{r['ratio']:,.1f}배** · 팔로워 {r['followers']:,}명")
                    if r['kind']=='릴스':
                        st.write(f"조회수 {r['plays']:,}회 · 좋아요 {r['likes'] if r['likes'] is not None else '정보 없음'}")
                    else:
                        st.write(f"좋아요 {r['likes']:,}개 · 댓글 {r['comments'] if r['comments'] is not None else '정보 없음'}개")
                    st.write(str(r['caption'])[:180])
                    st.link_button('인스타그램 원본 열기', r['url'])
        if len(visible) > 10:
            st.caption(f'상위 10개만 표시 중 · 나머지 {len(visible)-10}개는 필터를 바꿔 확인하세요.')
    if not st.session_state['hits']:
        st.warning('이번 표본에서는 검증된 조건 충족 콘텐츠가 없어요. 해시태그·수집 범위를 조절해 보세요. 0개라고 인스타그램 전체에 없는 것은 아니에요.')
else:
    st.write('왼쪽에서 자동 발견 또는 직접 검색을 고른 뒤 **지금 검색하기**를 눌러 주세요.')

st.divider()
st.header('🎬 Higgsfield 제작 메모')
st.caption('영상 내용을 자동 시청·분석하는 기능은 없어요. 원본을 직접 보고 구조를 기록하면 재창작용 초안을 만들어 줍니다.')
idea = st.text_input('새 영상 아이디어', placeholder='예: 우주복 입은 고양이가 마트에서 길을 잃는 이야기')
subject = st.text_input('주인공', placeholder='예: 귀여운 주황색 고양이')
scene = st.text_input('배경', placeholder='예: 미래 도시의 슈퍼마켓')
action = st.text_area('행동과 반전', placeholder='예: 고양이가 과자 봉지를 열자 작은 로봇들이 튀어나온다')
if st.button('프롬프트 초안 만들기'):
    if not all([idea, subject, scene, action]):
        st.warning('내용을 먼저 입력해 주세요.')
    else:
        st.markdown('**이미지용 프롬프트**')
        st.code(f'Photorealistic cinematic still of {subject} in {scene}. Concept: {idea}. Detailed lighting, expressive composition, vertical 9:16, no captions, no watermark.', language=None)
        st.markdown('**영상용 프롬프트**')
        st.code(f'Image-to-video, vertical 9:16. Main subject: {subject}. Location: {scene}. Action and twist: {action}. Clear action beats, natural coherent motion, cinematic camera tracking, consistent character appearance, no text.', language=None)
        st.caption('자동 번역이 아니라 입력 내용을 조합한 영어 지시문이야. 영어로 작성하거나 ChatGPT에서 자연스럽게 번역해 사용할 수 있어.')
