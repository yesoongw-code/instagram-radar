import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import streamlit as st

st.set_page_config(page_title='Instagram Radar', page_icon='📸', layout='wide')
st.title('📸 Instagram Radar · 숨은 떡상 찾기')
st.caption('Apify에서 공개 게시물·릴스 후보를 수집하고 작은 계정의 높은 반응을 찾아요. 인스타그램 전체 검색이나 국적 판정은 아니에요.')

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
        msg = response.text[:400]
        raise RuntimeError(f'Apify 응답 오류 ({response.status_code}): {msg}')
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

with st.sidebar:
    st.header('검색 설정')
    tags = st.text_input('해시태그 (쉼표 구분)', 'cat, funny, 일상, 猫')
    kinds = st.multiselect('콘텐츠 종류', ['Reels', 'Posts'], default=['Reels'])
    per_tag = st.slider('해시태그당 수집 개수', 5, 30, 10, 5)
    days = st.number_input('최근 며칠', 1, 90, 7)
    followers_limit = st.number_input('최대 팔로워', 1, 1000000, 1000)
    min_views = st.number_input('릴스 최소 조회수', 0, 100000000, 100000, 10000)
    min_ratio = st.number_input('릴스 최소 조회수/팔로워 배율', 1, 10000, 20)
    min_eng = st.number_input('이미지·캐러셀 최소 좋아요', 0, 1000000, 100, 10)
    max_accounts = st.slider('팔로워 조회 계정 상한', 1, 20, 5)
    max_usd = st.select_slider('한 번의 Actor 호출 비용 상한 (USD)', options=[0.01,0.03,0.05,0.10,0.20], value=0.10)
    run = st.button('🔎 공개 게시물 수집하고 분석하기', type='primary', use_container_width=True)
    st.caption('실행할 때마다 Apify 크레딧이 사용될 수 있어요. 해시태그·콘텐츠 종류별 호출과 프로필 조회 호출마다 상한이 별도로 적용됩니다.')

st.info('한국·미국·일본 게시물을 해시태그로 탐색할 수 있지만 실제 작성자 국가는 이 데이터만으로 확인할 수 없어요. 릴스는 조회수, 이미지·캐러셀은 좋아요를 기준으로 평가해요.')

if run:
    words = list(dict.fromkeys(x.strip().lstrip('#') for x in tags.split(',') if x.strip()))[:5]
    if not words or not kinds:
        st.warning('해시태그와 콘텐츠 종류를 선택해 주세요.')
        st.stop()
    st.caption(f'최대 {len(words)*len(kinds)}회 게시물 수집 + 최대 {max_accounts}회 프로필 조회가 실행될 수 있어요. 각 호출의 비용 상한은 ${max_usd:.2f}입니다.')
    result = []
    problems = []
    for tag in words:
        for kind in kinds:
            source = f'https://www.instagram.com/explore/tags/{tag}/'
            data = {'directUrls':[source], 'resultsType': kind.lower(), 'resultsLimit': per_tag}
            try:
                with st.spinner(f'#{tag} · {kind} 수집 중…'):
                    rows = execute(SCRAPER, data, max_usd)
                for row in rows:
                    if row.get('error'):
                        problems.append(f'{tag}/{kind}: {row.get("errorDescription", row.get("error"))}')
                    elif isinstance(row, dict):
                        row['_kind_search'] = kind
                        result.append(row)
            except Exception as e:
                problems.append(f'{tag}/{kind}: {e}')
    if problems:
        with st.expander(f'수집되지 않은 요청 {len(problems)}건'):
            for x in problems:
                st.write(x)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records = {}
    for item in result:
        posted = date(item)
        if not posted or posted < cutoff:
            continue
        username = item.get('ownerUsername') or item.get('username')
        if not username:
            continue
        url = item.get('url') or f'https://www.instagram.com/p/{item.get("shortCode", "")}/'
        code = item.get('shortCode') or url
        if code in records:
            continue
        kind = item.get('type', '')
        plays = num(item, 'videoPlayCount', 'igPlayCount', 'videoViewCount')
        likes = num(item, 'likesCount')
        is_video = item.get('_kind_search') == 'Reels' or kind == 'Video'
        if is_video and (plays is None or plays < min_views):
            continue
        if not is_video and (likes is None or likes < min_eng):
            continue
        records[code] = {'username': username, 'url': url, 'kind': '릴스' if is_video else ('캐러셀' if kind == 'Sidecar' else '이미지'), 'plays': plays, 'likes': likes, 'comments': num(item, 'commentsCount'), 'posted': posted.strftime('%Y-%m-%d'), 'caption': item.get('caption', '') or '', 'thumbnail': item.get('displayUrl', '')}
    candidates = list(records.values())
    candidates.sort(key=lambda x: x['plays'] if x['kind']=='릴스' else x['likes'] or 0, reverse=True)
    unique_users = list(dict.fromkeys(x['username'] for x in candidates))[:max_accounts]
    profiles = {}
    for user in unique_users:
        try:
            with st.spinner(f'@{user} 팔로워 확인 중…'):
                rows = execute(PROFILE, {'usernames':[user], 'resultsLimit':1}, max_usd)
            for p in rows:
                if p.get('username') == user:
                    profiles[user] = num(p, 'followersCount')
        except Exception as e:
            problems.append(f'프로필 @{user}: {e}')
    hits = []
    unchecked = 0
    for r in candidates:
        followers = profiles.get(r['username'])
        if followers is None:
            unchecked += 1
            continue
        if followers > followers_limit:
            continue
        base = r['plays'] if r['kind']=='릴스' else r['likes']
        ratio = base / max(1, followers)
        if r['kind']=='릴스' and ratio < min_ratio:
            continue
        r['followers'] = followers
        r['ratio'] = ratio
        hits.append(r)
    hits.sort(key=lambda r: r['ratio'], reverse=True)
    st.session_state['hits'] = hits
    st.session_state['unchecked'] = unchecked
    st.session_state['count'] = len(result)

if 'hits' in st.session_state:
    st.subheader(f"수집된 원본 {st.session_state['count']}건 · 확인된 조건 충족 {len(st.session_state['hits'])}건")
    st.caption(f"팔로워 정보를 확인하지 못해 판정에서 제외한 후보: {st.session_state['unchecked']}건. 상한에 걸려 조회하지 않은 계정도 포함될 수 있어요.")
    for r in st.session_state['hits']:
        with st.container(border=True):
            st.markdown(f"**{r['kind']} · @{r['username']} · {r['ratio']:.1f}배**")
            st.write(f"조회수: {r['plays'] if r['plays'] is not None else '해당 없음'} · 좋아요: {r['likes']} · 팔로워: {r['followers']} · 게시일: {r['posted']}")
            st.write(r['caption'][:220]); st.link_button('인스타그램 원본 열기', r['url'])
    if not st.session_state['hits']:
        st.warning('이번 표본에서는 검증된 조건 충족 콘텐츠가 없어요. 해시태그·수집 범위를 조절해 보세요. 0개라고 인스타그램 전체에 없는 것은 아니에요.')
else:
    st.write('왼쪽에서 해시태그와 수집 개수를 정한 뒤 검색 버튼을 누르세요.')

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
