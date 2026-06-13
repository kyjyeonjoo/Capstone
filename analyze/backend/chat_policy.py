"""Traffic-chat domain policy and prompt construction."""

import re


CHAT_DOMAIN_REJECTION = (
    "저는 교통사고 법률 상담 전문 챗봇으로, 교통 관련 질문에만 답변드릴 수 있습니다. "
    "교통사고나 관련 법률에 대해 궁금하신 점이 있으시면 질문해 주세요."
)

STRONG_TRAFFIC_KEYWORDS = (
    "교통", "교통사고", "차대차", "블랙박스", "블박", "과실", "과실비율",
    "도로교통법", "신호위반", "중앙선침범", "진로변경", "차선변경",
    "교차로", "횡단보도", "노외진입", "회전교차로", "추돌", "충돌",
    "접촉사고", "안전거리", "과속", "사고처리", "사고 처리", "분심위",
    "일시정지", "방향지시등", "전방주시", "꼬리물기", "불법주차",
    "과실상계", "책임보험",
)

VEHICLE_KEYWORDS = (
    "차량", "자동차", "승용차", "차", "차선", "차로", "차주", "운전",
    "운전자", "내차", "내 차", "상대차", "상대 차량", "앞차", "뒷차",
    "선행차", "후행차", "버스", "택시", "화물차", "트럭", "오토바이",
    "이륜차", "자전거", "보행자", "주차", "출차", "입차", "후진",
    "유턴", "좌회전", "우회전", "직진", "합류", "끼어들기", "급정거",
    "급제동", "정차", "주정차", "도로", "고속도로", "골목", "사거리",
    "삼거리", "주차장", "신호", "정지선", "번호판", "면허",
)

ACCIDENT_SUPPORT_KEYWORDS = (
    "사고", "가해", "피해", "위반", "법규", "법률", "판례", "대법원",
    "법원", "소송", "합의", "보험", "보험사", "손해배상", "대인", "대물",
    "보상", "수리비", "책임", "비율", "몇대몇", "몇 대 몇", "경찰",
    "신고", "진단서", "수리", "견적", "렌트", "대차", "민사", "형사",
    "벌점", "범칙금", "과태료", "청구", "배상", "손해", "합의금",
    "치료비", "병원", "상해", "부상", "정비소", "폐차", "견인",
    "cctv", "영상", "증거", "목격자",
)

EXCLUDED_KEYWORDS = (
    "점심", "저녁", "아침메뉴", "맛집", "레시피", "요리", "날씨", "여행",
    "숙소", "호텔", "게임", "영화", "드라마", "노래", "음악", "주식",
    "코인", "파이썬", "자바", "코딩", "프로그램 개발", "수학", "번역",
)

FOLLOWUP_PHRASES = (
    "왜", "맞아", "맞나요", "틀려", "틀린", "이유", "근거", "설명",
    "자세히", "어떻게", "뭐야", "뭔데", "가능", "불가능", "더", "다시",
    "정리", "요약", "상세", "그러면", "그럼", "이거", "저거", "결과",
    "판단", "비교",
)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", (text or "").lower(), flags=re.UNICODE)


def _contains_any(normalized: str, keywords: tuple[str, ...]) -> bool:
    return any(_normalize(keyword) in normalized for keyword in keywords)


def is_traffic_chat_question(question: str, has_accident_context: bool = False) -> bool:
    normalized = _normalize(question)
    if not normalized:
        return False

    ratio_source = re.sub(r"\s+", "", (question or "").lower())
    has_fault_ratio = bool(
        re.search(r"(?:100|[0-9]{1,2})(?::|대)(?:100|[0-9]{1,2})", ratio_source)
    )
    has_strong_term = _contains_any(normalized, STRONG_TRAFFIC_KEYWORDS)
    has_vehicle_term = _contains_any(normalized, VEHICLE_KEYWORDS)
    has_support_term = _contains_any(normalized, ACCIDENT_SUPPORT_KEYWORDS)
    has_excluded_term = _contains_any(normalized, EXCLUDED_KEYWORDS)

    if has_fault_ratio or has_strong_term or (has_vehicle_term and has_support_term):
        return True

    # "자동차", "자동차 알려줘"처럼 짧고 명확한 차량 주제도 허용한다.
    if has_vehicle_term and not has_excluded_term:
        return True

    if has_excluded_term:
        return False

    if has_accident_context and (
        _contains_any(normalized, FOLLOWUP_PHRASES) or len(normalized) <= 30
    ):
        return True

    return False


def build_chat_system_prompt() -> str:
    return (
        "당신은 'AI 교통사고 및 자동차 법률 보조 시스템'의 전문 상담 챗봇입니다. "
        "교통사고, 자동차와 차량 운행, 도로 및 신호 체계, 교통법규, 과실 비율, "
        "보험과 보상, 사고 처리, 관련 법률과 판례에 답변할 수 있습니다. "
        "질문에 '자동차', '차량', '운전'처럼 교통 관련 표현이 있으나 의도가 "
        "모호하면 답변을 거부하지 말고 어떤 내용이 궁금한지 짧게 되물으세요. "
        "교통 및 자동차와 명백히 무관한 질문에만 다음 문장으로 답변하세요: "
        f"'{CHAT_DOMAIN_REJECTION}' "
        "영상 분석 결과가 제공되면 감지된 사실과 추정 내용을 구분하고, 확인되지 "
        "않은 신호 상태나 운전자 행동을 단정하지 마세요. 과실 비율은 참고용 "
        "추정치임을 밝히고 관련 법규와 판례의 적용 이유를 친절하고 명확하게 "
        "설명하세요."
    )
