import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import streamlit as st

st.set_page_config(page_title='Instagram Radar', page_icon='📸', layout='wide')
st.title('📸 Instagram Radar · 숨은 떡상 찾기')
st.caption('Apify 공개 콘텐츠 검색 + 선택 영상 기반 Higgsfield 반자동 제작 스튜디오 · v4.0')

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
                    btn_open, btn_analyze = st.columns(2)
                    with btn_open:
                        st.link_button('인스타그램 원본 열기', r['url'], use_container_width=True)
                    with btn_analyze:
                        if st.button('🎬 AI 영상 분석하기', key=f"analyze_{r['url']}", use_container_width=True):
                            st.session_state['studio_selected'] = dict(r)
                            st.session_state['studio_notice'] = True
                            st.rerun()
        if len(visible) > 10:
            st.caption(f'상위 10개만 표시 중 · 나머지 {len(visible)-10}개는 필터를 바꿔 확인하세요.')
    if not st.session_state['hits']:
        st.warning('이번 표본에서는 검증된 조건 충족 콘텐츠가 없어요. 해시태그·수집 범위를 조절해 보세요. 0개라고 인스타그램 전체에 없는 것은 아니에요.')
else:
    st.write('왼쪽에서 자동 발견 또는 직접 검색을 고른 뒤 **지금 검색하기**를 눌러 주세요.')

st.divider()
st.header('🎬 AI 분석 · Higgsfield 제작 스튜디오')
st.caption('무료 반자동 도구입니다. 게시물 메타데이터는 자동으로 가져오지만 AI가 원본 영상을 직접 시청하거나 장면을 해석하지는 않습니다. 별도 유료 AI API를 호출하지 않습니다.')
selected = st.session_state.get('studio_selected')
if selected:
    st.success(f"선택한 콘텐츠: @{selected['username']} · {selected['kind']} · {selected['ratio']:,.1f}배")
    cols = st.columns([1, 2])
    with cols[0]:
        if selected.get('thumbnail'):
            try:
                st.image(selected['thumbnail'], use_container_width=True)
            except Exception:
                st.caption('이미지 표시가 제한됐어요.')
    with cols[1]:
        st.write(f"게시일: {selected['posted']} · 검색 묶음: {selected.get('region', '미분류')}")
        st.write(f"팔로워: {selected['followers']:,}명 · 조회수: {selected['plays'] if selected.get('plays') is not None else '해당 없음'}")
        st.write(f"원본 캡션: {str(selected.get('caption',''))[:450]}")
        st.link_button('원본 보고 장면 확인하기', selected['url'])
    if st.button('선택 해제', key='clear_studio'):
        st.session_state.pop('studio_selected', None)
        st.rerun()
else:
    st.info('위 TOP 10 카드에서 **🎬 AI 영상 분석하기**를 누르면 여기로 연결됩니다. 검색하지 않고도 아래 양식으로 기획할 수 있어요.')

st.subheader('1. 원본의 성공 구조 관찰 메모')
st.caption('추측과 직접 관찰한 내용을 구분해 적어주세요. 아래 예시는 실제 영상 분석이 아닙니다.')
col1, col2 = st.columns(2)
with col1:
    hook = st.text_area('첫 0~2초 후킹', key='studio_hook', placeholder='예: 화면에 갑자기 강아지가 등장해 무슨 일인지 궁금해짐')
    tension = st.text_area('2~6초 전개·궁금증', key='studio_tension', placeholder='예: 강아지가 상자 앞에서 계속 기다림')
with col2:
    payoff = st.text_area('반전·해결 장면', key='studio_payoff', placeholder='예: 상자 속에서 작은 장난감이 튀어나옴')
    ending = st.text_area('엔딩·반복 시청 이유', key='studio_ending', placeholder='예: 마지막 모습이 첫 화면으로 자연스럽게 이어짐')

st.subheader('2. 원본과 다른 새 콘텐츠 기획')
new_idea = st.text_input('새로운 이야기 핵심', key='studio_idea', placeholder='예: 우주복 입은 고양이가 마트에서 길을 잃는다')
subject = st.text_input('새로운 주인공', key='studio_subject', placeholder='예: 주황색 고양이 우주비행사')
scene = st.text_input('새로운 장소', key='studio_scene', placeholder='예: 미래 도시의 작은 마트')
action = st.text_area('새로운 행동과 반전', key='studio_action', placeholder='예: 문을 열자 진열대가 작은 우주선으로 변한다')
look = st.selectbox('이미지 스타일', ['실사 시네마틱', '3D 클레이 애니메이션', '동화 일러스트', '광고 화보'], key='studio_look')
camera = st.selectbox('카메라 움직임', ['고정 카메라', '부드러운 트래킹', '느린 줌인', '핸드헬드'], key='studio_camera')
duration = st.selectbox('영상 길이', ['5초', '8초', '10초', '15초'], index=2, key='studio_duration')

STYLE = {'실사 시네마틱':'photorealistic cinematic film still', '3D 클레이 애니메이션':'charming handcrafted 3D clay animation', '동화 일러스트':'warm storybook illustration', '광고 화보':'premium commercial editorial photography'}
CAMERA = {'고정 카메라':'stable locked-off camera', '부드러운 트래킹':'smooth tracking shot', '느린 줌인':'slow gradual push-in', '핸드헬드':'subtle handheld camera'}

if st.button('✨ 새 아이디어 3개 + Higgsfield 프롬프트 생성', type='primary', key='studio_generate'):
    if not all(x.strip() for x in [new_idea, subject, scene, action]):
        st.warning('새로운 이야기 핵심·주인공·장소·행동과 반전을 먼저 입력해 줘.')
    else:
        context = f"@{selected['username']} / {selected['kind']} / {selected['ratio']:,.1f}x" if selected else '원본 미선택'
        structure = ' → '.join(x.strip() for x in [hook, tension, payoff, ending] if x.strip()) or '직접 관찰한 구조 미입력'
        variations = [
            f'① 귀여운 반전형: {subject}이(가) {scene}에서 평범한 일상을 보내다 {action}',
            f'② 미스터리 호기심형: {scene}에 예상치 못한 이상 현상이 생기고, {subject}이(가) 그 비밀을 쫓는다. 결말은 {action}',
            f'③ 상황 코미디형: {subject}이(가) {scene}에서 계획대로 하려 하지만 예상치 못한 상황이 계속 발생한다. 마지막에는 {action}',
        ]
        brief = f'''[Instagram Radar 4.0 · 재창작 분석 시트]
참고 원본: {context}
참고 링크: {selected['url'] if selected else '없음'}
원본 캡션: {str(selected.get('caption',''))[:300] if selected else '미선택'}
원본 관찰: 후킹={hook or '미입력'} / 전개={tension or '미입력'} / 반전={payoff or '미입력'} / 엔딩={ending or '미입력'}
주의: 아래 아이디어는 입력 정보를 활용한 규칙 기반 초안이며, AI 자동 영상 판독 결과가 아닙니다.
재사용할 구조: {structure}
새로운 핵심 아이디어: {new_idea}
'''
        img = f'''{STYLE[look]}, {subject} in {scene}. Original fictional concept: {new_idea}. Frame should establish the subject and the setting clearly, expressive storytelling, coherent lighting, detailed textures, 9:16 vertical composition, leave safe space for captions, no text, no watermark. Avoid copying characters, shots, logos, or distinct visual assets from any reference video.'''
        vid = f'''Image-to-video prompt for Higgsfield. Duration: {duration}. Format: vertical 9:16. Maintain visual consistency with the supplied starting image. Subject: {subject}. Setting: {scene}. Original action and twist: {action}. Camera: {CAMERA[camera]}. Pacing: immediate curiosity hook, visible action escalation, clear ending payoff. Realistic or stylistically consistent motion, physically coherent movement, stable character identity, no abrupt morphing, no captions, no logos. Create a new scene; do not reproduce shots from reference videos.'''
        st.session_state['studio_output'] = {'brief':brief, 'ideas':'\n'.join(variations), 'image':img, 'video':vid}

output = st.session_state.get('studio_output')
if output:
    st.subheader('3. 완성된 제작 초안')
    st.caption('아래 텍스트는 각각 복사해 사용할 수 있어요. 한국어로 입력한 부분은 그대로 남아 있을 수 있으므로 Higgsfield 입력 시 문장을 다듬어 주세요.')
    st.markdown('**새 콘텐츠 아이디어 3개**')
    st.code(output['ideas'], language=None)
    st.markdown('**이미지 생성 프롬프트**')
    st.code(output['image'], language=None)
    st.markdown('**Higgsfield 영상 생성 프롬프트**')
    st.code(output['video'], language=None)
    st.download_button('📄 분석 시트 + 프롬프트 TXT 저장', data=output['brief']+'\n'+output['ideas']+'\n\n[IMAGE]\n'+output['image']+'\n\n[VIDEO]\n'+output['video'], file_name='instagram_radar_higgsfield_brief.txt', mime='text/plain')
    st.caption('실제 Higgsfield 영상 생성은 별도 서비스에서 진행하며 구독 플랜의 크레딧이 사용될 수 있어요.')
