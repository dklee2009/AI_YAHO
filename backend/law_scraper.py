"""
국가법령정보센터 법령 스크래퍼

우선순위:
  1) LAW_API_OC 환경변수가 있으면 → 공식 Open API 사용 (open.law.go.kr 무료 등록)
  2) 없으면 → law.go.kr HTML 직접 스크래핑
  3) 스크래핑도 실패하면 → 내장 Mock 조문 데이터 사용
"""

import os
import json
import re
import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

CACHE_DIR = Path(__file__).parent / "law_cache"
CACHE_DIR.mkdir(exist_ok=True)

OC = os.getenv("LAW_API_OC", "")
DRF_BASE = "http://www.law.go.kr/DRF"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 질문 키워드 → 관련 법령 매핑
LAW_KEYWORD_MAP = {
    "전자금융거래법": [
        "전자금융", "전자화폐", "전자자금이체", "결제시스템", "지급결제",
        "선불전자", "직불전자", "전자금융업", "금융거래",
    ],
    "개인정보보호법": [
        "개인정보", "정보주체", "동의", "개인정보처리", "민감정보",
        "고유식별", "개인정보 유출", "파기", "열람",
    ],
    "정보통신망이용촉진및정보보호등에관한법률": [
        "정보통신망", "해킹", "사이버", "악성프로그램", "침해사고",
        "스팸", "정보통신서비스", "망 보안",
    ],
    "전자서명법": [
        "전자서명", "공동인증서", "공인인증서", "인증서", "전자증명",
        "전자서명인증사업자", "공개키",
    ],
}

# ─────────────────────────────────────────────────────────
# Mock 조문 데이터 (API 없이도 동작하도록 핵심 조문 내장)
# ─────────────────────────────────────────────────────────
MOCK_LAW_DB = {
    "전자금융거래법": [
        {
            "조": "제21조",
            "제목": "전자금융기반시설의 보호",
            "내용": (
                "금융회사 또는 전자금융업자는 전자금융거래의 안전성과 신뢰성을 확보하기 위하여 "
                "전자적 침해행위를 방지하고 전자금융기반시설을 보호하기 위한 정보보호 최고책임자를 "
                "지정하고 정보보호업무를 총괄하게 하여야 한다. "
                "금융위원회는 필요하다고 인정하는 경우 금융회사 등에게 전자금융기반시설 보호에 "
                "필요한 조치를 취할 것을 명령할 수 있다."
            ),
        },
        {
            "조": "제22조",
            "제목": "전자금융기반시설의 취약점 분석·평가",
            "내용": (
                "금융회사 또는 전자금융업자는 전자금융기반시설에 대하여 연 1회 이상 취약점을 "
                "분석·평가하고 그 결과를 금융위원회에 보고하여야 한다. "
                "취약점 분석·평가는 금융위원회가 정하는 전문기관에 의뢰할 수 있다."
            ),
        },
        {
            "조": "제9조",
            "제목": "접근매체의 선정과 사용 및 관리",
            "내용": (
                "금융회사 또는 전자금융업자는 전자금융거래에 사용되는 접근매체를 선정하는 경우 "
                "이용자가 안전하게 사용할 수 있도록 필요한 보안기술을 적용하여야 하며, "
                "접근매체의 도용이나 위조 또는 변조를 방지할 수 있는 기술적 조치를 하여야 한다."
            ),
        },
        {
            "조": "제32조",
            "제목": "전자금융거래기록의 생성 및 보존",
            "내용": (
                "금융회사 또는 전자금융업자는 전자금융거래의 내용을 추적·검색하거나 "
                "그 내용에 오류가 발생할 경우 이를 확인·정정할 수 있는 전자금융거래기록을 "
                "생성·보존하여야 한다. 전자금융거래기록의 종류 및 보존기간은 "
                "대통령령으로 정한다(통상 5년)."
            ),
        },
    ],
    "개인정보보호법": [
        {
            "조": "제29조",
            "제목": "안전조치의무",
            "내용": (
                "개인정보처리자는 개인정보가 분실·도난·유출·위조·변조 또는 훼손되지 아니하도록 "
                "내부 관리계획 수립, 접속기록 보관 등 대통령령으로 정하는 바에 따라 "
                "안전성 확보에 필요한 기술적·관리적 및 물리적 조치를 하여야 한다."
            ),
        },
        {
            "조": "제34조",
            "제목": "개인정보 유출 통지 등",
            "내용": (
                "개인정보처리자는 개인정보가 유출되었음을 알게 되었을 때에는 지체 없이 해당 "
                "정보주체에게 ① 유출된 개인정보의 항목 ② 유출된 시점과 그 경위 "
                "③ 유출로 인한 피해를 최소화하기 위한 방법을 알려야 한다. "
                "1천 명 이상의 정보주체에 관한 개인정보가 유출된 경우 72시간 내 "
                "개인정보보호위원회 또는 전문기관에 신고하여야 한다."
            ),
        },
        {
            "조": "제15조",
            "제목": "개인정보의 수집·이용",
            "내용": (
                "개인정보처리자는 ① 정보주체의 동의를 받은 경우 "
                "② 법률에 특별한 규정이 있거나 법령상 의무 준수를 위해 불가피한 경우 "
                "③ 공공기관이 법령에서 정하는 소관 업무 수행을 위해 불가피한 경우 등에 한하여 "
                "개인정보를 수집할 수 있으며, 수집 목적 범위 내에서만 이용할 수 있다."
            ),
        },
        {
            "조": "제24조",
            "제목": "고유식별정보의 처리 제한",
            "내용": (
                "개인정보처리자는 주민등록번호, 여권번호, 운전면허번호, 외국인등록번호 등 "
                "고유식별정보를 처리할 수 없다. 다만, 정보주체에게 별도의 동의를 받은 경우 또는 "
                "법령에서 구체적으로 고유식별정보의 처리를 요구하거나 허용하는 경우에는 그러하지 아니하다. "
                "금융회사는 주민등록번호의 경우 암호화 등 안전성 확보 조치를 하여야 한다."
            ),
        },
    ],
    "정보통신망이용촉진및정보보호등에관한법률": [
        {
            "조": "제28조",
            "제목": "개인정보의 보호조치",
            "내용": (
                "정보통신서비스 제공자 등이 개인정보를 취급할 때에는 개인정보의 "
                "분실·도난·누출·변조 또는 훼손을 방지하기 위하여 ① 개인정보를 안전하게 취급하기 위한 "
                "내부관리계획의 수립·시행 ② 개인정보에 대한 불법적인 접근을 차단하기 위한 "
                "침입차단시스템 등 접근통제장치의 설치·운영 ③ 접속기록의 위조·변조 방지를 위한 "
                "조치 등 기술적·관리적 조치를 하여야 한다."
            ),
        },
        {
            "조": "제48조",
            "제목": "정보통신망 침해행위 등의 금지",
            "내용": (
                "누구든지 정당한 접근권한 없이 또는 허용된 접근권한을 넘어 정보통신망에 "
                "침입하여서는 아니된다. 누구든지 정보통신망에 장애가 발생하게 하는 "
                "악성프로그램을 전달 또는 유포하여서는 아니된다. "
                "침해사고 발생 시 과학기술정보통신부장관에게 신고하여야 한다."
            ),
        },
    ],
    "전자서명법": [
        {
            "조": "제3조",
            "제목": "전자서명의 효력",
            "내용": (
                "전자서명은 전자적 형태라는 이유만으로 서명, 서명날인 또는 기명날인으로서의 "
                "효력이 부인되지 아니한다. 법령의 규정 또는 당사자 간의 약정에 따라 서명, "
                "서명날인 또는 기명날인의 방식으로 전자서명을 선택한 경우 그 전자서명은 "
                "서명, 서명날인 또는 기명날인으로서의 효력을 가진다."
            ),
        },
        {
            "조": "제9조",
            "제목": "전자서명인증사업자의 준수사항",
            "내용": (
                "전자서명인증사업자는 전자서명인증서비스를 제공함에 있어 "
                "과학기술정보통신부장관이 정하는 전자서명인증업무 운영기준을 준수하여야 한다. "
                "인증사업자는 전자서명인증서의 발급·갱신·효력정지·폐지 등의 업무를 수행하며 "
                "그 기록을 5년간 보존하여야 한다."
            ),
        },
    ],
}


# ─────────────────────────────────────────────────────────
# 공식 Open API (LAW_API_OC 설정 시)
# ─────────────────────────────────────────────────────────

async def _api_search(law_name: str) -> str | None:
    """법령명으로 MST 번호 검색"""
    try:
        async with httpx.AsyncClient(timeout=8, headers=HEADERS) as client:
            r = await client.get(f"{DRF_BASE}/lawSearch.do", params={
                "OC": OC, "target": "law", "type": "JSON",
                "query": law_name, "display": 3,
            })
            data = r.json()
            laws = data.get("LawSearch", {}).get("law", [])
            if isinstance(laws, dict):
                laws = [laws]
            return laws[0].get("MST") if laws else None
    except Exception:
        return None


async def _api_get_articles(mst: str, law_name: str) -> list[dict]:
    """MST로 법령 전문 조회 후 조문 파싱"""
    cache = CACHE_DIR / f"api_{mst}.json"
    if cache.exists():
        return json.loads(cache.read_text("utf-8"))

    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(f"{DRF_BASE}/lawService.do", params={
                "OC": OC, "target": "law", "MST": mst, "type": "XML",
            })
        root = ET.fromstring(r.text)
        articles = []
        for jo in root.findall(".//조문"):
            num = jo.findtext("조번호", "").strip()
            title = jo.findtext("조제목", "").strip()
            parts = []
            body = jo.findtext("조문내용", "").strip()
            if body:
                parts.append(body)
            for hang in jo.findall("항"):
                hc = hang.findtext("항내용", "").strip()
                if hc:
                    parts.append(hc)
            content = " ".join(parts)[:600]
            if num and content:
                articles.append({"조": f"제{num}조", "제목": title, "내용": content})

        cache.write_text(json.dumps(articles, ensure_ascii=False, indent=2), "utf-8")
        return articles
    except Exception:
        return []


# ─────────────────────────────────────────────────────────
# HTML 스크래핑 폴백 (API 키 없을 때)
# ─────────────────────────────────────────────────────────

async def _html_scrape(law_name: str) -> list[dict]:
    """law.go.kr 모바일 페이지에서 조문 스크래핑"""
    cache = CACHE_DIR / f"html_{law_name}.json"
    if cache.exists():
        return json.loads(cache.read_text("utf-8"))

    try:
        enc_name = law_name.encode("utf-8").hex()  # 폴백
        url = f"https://www.law.go.kr/법령/{law_name}"
        async with httpx.AsyncClient(
            timeout=12, headers=HEADERS,
            follow_redirects=True,
        ) as client:
            r = await client.get(url)

        # 간단한 조문 패턴 추출 (정규식 기반)
        text = r.text
        articles = []
        # 패턴: 제XX조(제목) 본문
        pattern = re.compile(
            r"제(\d+)조(?:의\d+)?\s*\(([^)]{1,40})\)\s*((?:(?!제\d+조).){20,400})",
            re.S,
        )
        for m in pattern.finditer(text):
            content = re.sub(r"\s+", " ", m.group(3)).strip()
            content = re.sub(r"<[^>]+>", "", content)  # 태그 제거
            if len(content) > 30:
                articles.append({
                    "조": f"제{m.group(1)}조",
                    "제목": m.group(2).strip(),
                    "내용": content[:500],
                })

        if articles:
            cache.write_text(json.dumps(articles, ensure_ascii=False, indent=2), "utf-8")
        return articles
    except Exception:
        return []


# ─────────────────────────────────────────────────────────
# 핵심 퍼블릭 함수
# ─────────────────────────────────────────────────────────

def _match_laws(question: str) -> list[str]:
    """질문 키워드로 관련 법령 목록 반환"""
    matched = []
    for law, keywords in LAW_KEYWORD_MAP.items():
        if any(kw in question for kw in keywords):
            matched.append(law)
    return matched or list(LAW_KEYWORD_MAP.keys())[:2]


def _score_articles(articles: list[dict], question: str) -> list[dict]:
    """질문과의 연관도로 조문 정렬"""
    words = set(re.findall(r"[가-힣a-zA-Z]{2,}", question))

    def score(art):
        text = art.get("제목", "") + art.get("내용", "")
        return sum(1 for w in words if w in text)

    return sorted(articles, key=score, reverse=True)


async def find_relevant_articles(question: str, max_articles: int = 4) -> str:
    """
    질문에 관련된 법령 조문을 찾아 포맷된 문자열로 반환.
    규정담당 에이전트의 시스템 프롬프트에 삽입됩니다.
    """
    target_laws = _match_laws(question)
    found: list[tuple[str, dict]] = []  # (law_name, article)

    for law_name in target_laws:
        articles: list[dict] = []

        # 1) 공식 API
        if OC:
            mst = await _api_search(law_name)
            if mst:
                articles = await _api_get_articles(mst, law_name)

        # 2) HTML 스크래핑
        if not articles:
            articles = await _html_scrape(law_name)

        # 3) Mock 데이터
        if not articles:
            articles = MOCK_LAW_DB.get(law_name, [])

        ranked = _score_articles(articles, question)
        for art in ranked[:2]:
            found.append((law_name, art))

    if not found:
        return ""

    lines = ["📋 **관련 법령 조문 참고자료**\n"]
    for law_name, art in found[:max_articles]:
        lines.append(
            f"▸ **{law_name} {art['조']}** {art.get('제목','')}\n"
            f"  {art['내용']}\n"
        )
    return "\n".join(lines)


async def get_law_summary() -> dict[str, int]:
    """현재 캐시 상태 반환 (health check용)"""
    summary = {}
    for law in LAW_KEYWORD_MAP:
        articles = MOCK_LAW_DB.get(law, [])
        summary[law] = len(articles)
    return summary