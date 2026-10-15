"""리스크 검토 카테고리: 개인정보 · 외부 API · 해외 전송 · 취약점.

질문(과 AI 답변)을 보고 네 가지 리스크 유형별로 해당 여부와 위험도(높음/보통/낮음),
판단 근거를 정한다. 실제 모드에서는 Claude가 판단하고, mock 모드나 API 실패 시에는
질문에 나온 단어로 판단하는 규칙(keyword_risks)으로 대신한다.
"""
import json
import re

LEVELS = ["높음", "보통", "낮음"]

# 리스크 유형별 (검토 분야 라벨, 기본 점검 질문, 기본 확인 필요사항)
RISK_TYPES = {
    "privacy": (
        "개인정보",
        "개인정보 수집·이용 목적과 최소 수집 원칙, 암호화·접근통제 등 안전조치가 마련되었는가?",
        "수집 항목, 이용 목적, 동의서, 영향평가 대상 여부",
    ),
    "external_api": (
        "외부 API",
        "외부 API 연동 시 인증·전송 암호화·호출 제한과 제3자 제공·위탁 근거가 검토되었는가?",
        "연동 기관, 제공 항목, API 인증 방식, 위탁·제공 계약",
    ),
    "overseas": (
        "해외 전송",
        "정보의 국외 이전 시 법적 근거, 고객 고지·동의, 감독기관 보고 요건을 확인하였는가?",
        "이전 국가, 수탁사, 이전 항목, 국외이전 동의, 클라우드 이용 보고",
    ),
    "vulnerability": (
        "취약점",
        "서비스 오픈 전 취약점 점검·모의해킹을 수행하고 조치 결과를 확인하였는가?",
        "점검 범위, 점검 일정, 조치 결과 보고서",
    ),
}

# mock/폴백 판단용 단어. "high"에 걸리면 위험도를 한 단계 올린다.
RISK_KEYWORDS = {
    "privacy": {
        "base": ["개인정보", "고객", "회원", "계좌", "연락처", "거래 데이터", "거래데이터",
                 "상담 이력", "상담이력", "위치", "이력", "마이데이터", "본인인증"],
        "high": ["주민", "생체", "신용", "건강", "민감정보", "고유식별", "얼굴", "지문"],
    },
    # "외부"만으로는 넣지 않는다 ("외부 업체와 계약"처럼 연동과 무관한 문장이 많음).
    "external_api": {
        "base": ["api", "연동", "제3자", "오픈뱅킹", "핀테크", "saas", "제휴",
                 "마이데이터", "타사", "위탁"],
        "high": ["제3자 제공", "외부 api", "외부 연동", "오픈api", "오픈 api"],
    },
    "overseas": {
        "base": ["해외", "국외", "글로벌", "외국", "aws", "azure", "gcp", "구글 클라우드",
                 "역외", "saas", "퍼블릭 클라우드"],
        "high": ["해외 서버", "국외 이전", "해외 전송", "국외 전송", "해외 리전"],
    },
    "vulnerability": {
        "base": ["앱", "모바일", "웹", "인터넷", "비대면", "클라우드", "신규",
                 "구축", "플랫폼", "api", "챗봇"],
        "high": ["인터넷뱅킹", "비대면", "공개", "오픈api", "오픈 api", "외부 공개", "취약점"],
    },
}

RISK_ORDER = list(RISK_TYPES.keys())


def _hits(text: str, words: list[str]) -> list[str]:
    return [w for w in words if w in text]


def keyword_risks(question: str) -> list[dict]:
    """질문에 나온 단어로 리스크 유형별 해당 여부와 위험도를 정한다."""
    low = question.lower()

    def found(risk_type: str) -> bool:
        kws = RISK_KEYWORDS[risk_type]
        return bool(_hits(low, kws["base"] + kws["high"]))

    privacy_found = found("privacy")
    leaves_bank = found("external_api") or found("overseas")
    risks = []
    for risk_type, kws in RISK_KEYWORDS.items():
        base, high = _hits(low, kws["base"]), _hits(low, kws["high"])
        if not base and not high:
            continue
        level = 1  # 보통
        if high:
            level -= 1
        # 개인정보가 외부 연동·해외 전송으로 은행 밖에 나가면 양쪽 모두 위험도를 올린다.
        if (risk_type in ("external_api", "overseas") and privacy_found) or \
           (risk_type == "privacy" and leaves_bank):
            level -= 1
        if risk_type == "vulnerability" and not high and len(base) < 2:
            level += 1
        level = max(0, min(level, 2))
        words = ", ".join(f"'{w}'" for w in (high + base)[:3])
        _, text, check = RISK_TYPES[risk_type]
        risks.append({
            "type": risk_type, "level": LEVELS[level], "text": text, "check": check,
            # 단어는 질문뿐 아니라 프로파일 응답에서 왔을 수도 있다.
            "reason": f"질문·프로젝트 정보에 {words}이(가) 있어 {RISK_TYPES[risk_type][0]} 리스크가 예상됩니다.",
        })
    return risks


async def ai_risks(question: str, reply: str, api_key: str) -> list[dict]:
    """Claude가 질문·답변을 보고 리스크 유형별 위험도를 판단한다.
    응답을 해석하지 못하거나 API가 실패하면 keyword_risks로 폴백한다."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""당신은 은행 IT 프로젝트의 리스크 검토 담당자입니다.
다음 질문과 검토 답변을 보고, 아래 네 가지 리스크 유형별로 이 프로젝트에 해당하는지 판단하세요.

- privacy: 개인정보 (고객 정보 수집·이용·보관, 민감정보·고유식별정보 처리)
- external_api: 외부 API (외부 기관·업체·SaaS와의 연동, 제3자 제공·위탁)
- overseas: 해외 전송 (해외 서버·클라우드 사용, 정보의 국외 이전)
- vulnerability: 취약점 (외부에 노출되는 서비스의 보안 취약점, 공격 표면)

질문: "{question}"

검토 답변:
{reply}

해당하는 유형만 골라 다음을 채우세요. 근거가 없는 유형은 억지로 넣지 말고 빼세요.
- level: "높음" / "보통" / "낮음" 중 하나
- reason: 그렇게 판단한 근거 한 문장 (60자 안팎)
- text: "~되었는가?" / "~하였는가?" 로 끝나는 점검 질문 한 문장
- check: 확인에 필요한 자료·값을 쉼표로 구분한 짧은 명사구

아래 JSON 형식으로만 응답하세요:
{{"risks": [{{"type": "privacy", "level": "높음", "reason": "판단 근거", "text": "점검 질문", "check": "확인 필요사항"}}]}}"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        match = re.search(r"\{.*\}", resp.content[0].text, re.DOTALL)
        raw = json.loads(match.group()).get("risks", []) if match else None
    except Exception:
        raw = None
    if raw is None:
        return keyword_risks(question)

    risks = []
    for r in raw:
        risk_type = r.get("type")
        if risk_type not in RISK_TYPES or any(x["type"] == risk_type for x in risks):
            continue
        _, default_text, default_check = RISK_TYPES[risk_type]
        risks.append({
            "type": risk_type,
            "level": r.get("level") if r.get("level") in LEVELS else "보통",
            "reason": (r.get("reason") or "").strip(),
            "text": (r.get("text") or "").strip() or default_text,
            "check": (r.get("check") or "").strip() or default_check,
        })
    return risks


def sort_risks(risks: list[dict]) -> list[dict]:
    """위험도가 높은 것부터, 같은 위험도면 개인정보 → 외부 API → 해외 전송 → 취약점 순."""
    return sorted(risks, key=lambda r: (LEVELS.index(r["level"]), RISK_ORDER.index(r["type"])))


def risk_area(risk_type: str) -> str:
    return RISK_TYPES[risk_type][0]
