"""체크리스트 항목을 보고 인사파일(data/employees.csv)에서 담당자를 골라준다.

판단 방식: 항목 문장에서 업무 개념(암호화, 로그, 토큰 …)을 찾고, 같은 개념을
팀명·업무명에 가진 직원에게 점수를 준다(문장에 걸린 단어 수 × (1 + 문장·업무명에 함께
나온 단어 수), 검토 분야가 개념 이름과 겹치면 보너스). 점수가 같으면 실무 담당 직급(과장 → 차장 → 대리 …)
순으로 고른다. 어떤 개념도 걸리지 않으면 카테고리별 기본 팀(보안 → 보안정책팀,
IT → IT거버넌스팀)의 팀장에게 배정해 재배분하도록 한다.
"""
import csv
from pathlib import Path

EMPLOYEES_PATH = Path(__file__).resolve().parent / "data" / "employees.csv"

# (검토 분야 라벨, 항목 문장에서 찾을 단어, 팀명·업무명에서 찾을 단어)
# 단어는 모두 소문자로 비교한다.
CONCEPTS = [
    ("API·트래픽",   ["api", "gateway", "게이트웨이", "rate limit", "트래픽"],
                     ["api", "gateway", "rate limit", "트래픽"]),
    ("레거시 연동",  ["레거시", "eai", "계정계"], ["레거시", "계정계", "eai"]),
    ("데이터 정합성", ["정합성", "데이터 이관", "데이터베이스"], ["정합성", "이관", "db"]),
    ("장애 대응",    ["장애", "circuit", "복구"], ["장애"]),
    ("전송 암호화",  ["tls", "ssl", "전송 구간"], ["tls"]),
    ("다중 인증",    ["mfa", "다중인증", "다중 인증", "otp"], ["mfa"]),
    ("토큰 관리",    ["토큰", "token", "세션", "jwt"], ["토큰", "세션"]),
    ("통합 인증",    ["sso", "통합인증", "oauth", "saml"], ["sso", "통합인증"]),
    ("생체 인증",    ["생체"], ["생체인증"]),
    ("인증서 정책",  ["공인", "민간 인증서", "인증서 병행", "전자서명"], ["공동·민간", "전자서명"]),
    ("데이터 암호화", ["암호화", "aes", "키 관리", "키관리", "hsm"], ["암호화", "키관리"]),
    ("로그 관리",    ["로그", "log"], ["로그"]),
    ("개인정보",     ["개인정보", "민감정보", "주민번호", "제29조"], ["개인정보"]),
    ("안전조치",     ["안전조치"], ["안전조치"]),
    ("준법 검토",    ["준법", "전자금융감독규정", "감독규정", "금융규제", "컴플라이언스", "사전 검토"],
                     ["준법", "감독규정", "금융규제"]),
    ("법적 근거",    ["법적", "법령", "근거 법"], ["법령"]),
    ("변경 관리",    ["변경 이력", "변경관리", "변경 관리"], ["변경관리"]),
    ("클라우드",     ["클라우드", "쿠버네티스", "kubernetes", "마이크로서비스", "msa"], ["클라우드", "쿠버네티스"]),
    ("배포 관리",    ["ci/cd", "배포", "파이프라인"], ["ci/cd", "배포", "파이프라인"]),
    ("모바일",       ["모바일"], ["모바일"]),
    ("접근 통제",    ["접근제어", "접근통제", "최소 권한", "권한"], ["접근통제"]),
    ("취약점 점검",  ["취약점", "모의해킹", "침투", "owasp"], ["취약점", "모의해킹"]),
    ("네트워크",     ["방화벽", "네트워크"], ["방화벽", "네트워크"]),
    ("보안 정책",    ["보안성 심의", "보안 정책", "정보보호 정책"], ["보안성 심의", "정보보호 정책"]),
    ("전략·성과",    ["kpi", "성과", "전략", "추진 목적", "목표"], ["전략", "성과관리"]),
    # 전결 체크리스트용 (경영지원부 계약관리팀·재무팀). "계약"은 거의 모든 항목과
    # 팀명에 들어가 변별력이 없으므로 쓰지 않고 업무 단위로 나눈다.
    ("계약 체결",    ["계약대장", "체결", "검수", "분할", "이행보증", "발주"], ["계약대장", "체결"]),
    ("견적·가격",    ["견적", "계약총액", "예정가격", "경쟁 절차", "합산"], ["견적", "예정가격"]),
    ("수의·평가",    ["수의", "평가항목", "평가기준", "입찰"], ["수의계약", "입찰"]),
    ("예산·재무",    ["예산", "선급금", "대금", "투자계획", "자산"], ["예산", "대금", "선급금", "투자계획", "자산"]),
]

# 같은 점수라면 카테고리와 맞는 부서를 조금 더 우선한다.
CATEGORY_DEPTS = {
    "security": {"정보보호부", "준법감시부"},
    "it": {"IT기획부", "디지털플랫폼부", "IT인프라부"},
    "approval": {"경영지원부", "준법감시부"},
}
FALLBACK_TEAM = {"security": "보안정책팀", "it": "IT거버넌스팀", "approval": "계약관리팀"}
TITLE_PRIORITY = {"과장": 0, "차장": 1, "대리": 2, "팀장": 3, "주임": 4, "부장": 5}


def _load_employees() -> list[dict]:
    if not EMPLOYEES_PATH.exists():
        return []
    with EMPLOYEES_PATH.open(encoding="utf-8-sig", newline="") as f:
        return [
            {"emp_no": r["사번"], "name": r["성명"], "dept": r["부서"],
             "team": r["팀명"], "title": r["직명"], "duty": r["업무명"]}
            for r in csv.DictReader(f)
        ]


EMPLOYEES = _load_employees()


def _matched_concepts(text: str) -> list[tuple[str, int, list[str]]]:
    """문장에 걸린 개념들을 (라벨, 걸린 단어 수, 팀·업무 쪽 단어) 로 돌려준다."""
    low = text.lower()
    hits = []
    for label, triggers, duty_words in CONCEPTS:
        weight = sum(1 for t in triggers if t in low)
        if weight:
            hits.append((label, weight, duty_words))
    return hits


def _rank_key(emp: dict, score: float):
    return (-score, TITLE_PRIORITY.get(emp["title"], 9), emp["emp_no"])


def infer_area(text: str) -> str:
    """직접 추가한 항목처럼 검토 분야가 없는 경우, 가장 강하게 걸린 개념을 분야로 쓴다."""
    hits = _matched_concepts(text)
    return max(hits, key=lambda h: h[1])[0] if hits else "기타"


def assign_owner(text: str, category_id: str, area: str = "", limit: int = 3) -> dict:
    """항목 문장(과 검토 분야)으로 담당자 후보를 골라
    {'owner': 직원|None, 'candidates': [직원…]} 를 반환한다."""
    if not EMPLOYEES:
        return {"owner": None, "candidates": []}

    low = text.lower()
    # 검토 분야가 개념 이름과 겹치면(예: "개인정보 암호화" ⊃ "개인정보") 그 개념에 보너스.
    area_low = area.lower().strip()
    bonus = {label: 2 for label, _, _ in CONCEPTS
             if area_low and (label.lower() in area_low or area_low in label.lower())}
    hits = {label: (weight, words) for label, weight, words in _matched_concepts(text)}
    for label, _, words in CONCEPTS:
        if label in bonus and label not in hits:
            hits[label] = (0, words)

    preferred = CATEGORY_DEPTS.get(category_id, set())
    scored = []
    for emp in EMPLOYEES:
        haystack = f"{emp['team']} {emp['duty']}".lower()
        score = 0
        for label, (weight, words) in hits.items():
            matched = [d for d in words if d in haystack]
            if not matched:
                continue
            # 항목 문장과 업무명에 같은 단어가 직접 나오면 더 강한 근거로 본다.
            overlap = sum(1 for d in matched if d in low)
            score += weight * (1 + overlap) + bonus.get(label, 0)
        if score:
            if emp["dept"] in preferred:
                score += 0.5
            scored.append((emp, score))

    if not scored:
        team = FALLBACK_TEAM.get(category_id, "IT거버넌스팀")
        # 판단 근거가 없으면 기본 팀 팀장이 먼저 오도록 한다.
        scored = [(e, 1 if e["title"] == "팀장" else 0) for e in EMPLOYEES if e["team"] == team]

    scored.sort(key=lambda es: _rank_key(*es))
    candidates = [e for e, _ in scored[:limit]]
    return {"owner": candidates[0] if candidates else None, "candidates": candidates}
