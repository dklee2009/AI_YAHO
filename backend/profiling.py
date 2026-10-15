"""체크리스트를 시작하기 전 프로젝트 기본 프로파일링.

첫 프로젝트 질문을 보고 영역별 항목(데이터·인프라·계약·서비스·기술·예산)을
1) 질문에서 추론할 수 있으면 근거와 함께 "추론됨"으로 채우고,
2) 추론할 수 없고 이 프로젝트와 관련 있는 것만 질문으로 만든다.
질문에는 depends_on(앞 답변이 특정 값일 때만 묻기)을 달아 무관한 질문을 숨긴다.
실제 모드에서는 Claude가 같은 형식으로 판단하고, 실패하면 단어 규칙(keyword_profile)으로 대신한다.
"""
import json
import re

from approval_rules import format_won, parse_contract_amount

# 수집 항목 카탈로그. infer: (단어 목록, 추론 값) 쌍을 위에서부터 보고 처음 걸린 값을 쓴다.
# depends_on: {"id": 다른 항목, "not_in": [값…]} — 그 항목 값이 not_in 이면 묻지 않는다.
FIELDS = [
    {"id": "personal", "area": "데이터", "label": "개인정보 처리",
     "question": "고객·임직원의 개인정보를 처리하나요?",
     "options": ["처리함", "처리 안 함"],
     "infer": [(["개인정보", "고객", "회원", "상담 이력", "상담이력", "연락처", "본인인증", "계좌", "대출", "농업인"], "처리함")]},
    {"id": "sensitive", "area": "데이터", "label": "민감·고유식별정보",
     "question": "민감정보나 고유식별정보도 처리하나요?", "multi": True, "multi_infer": True,
     "options": ["주민등록번호 등 고유식별정보", "생체·건강 등 민감정보", "해당 없음"],
     "infer": [(["생체", "지문", "얼굴", "홍채"], "생체·건강 등 민감정보"),
               (["주민번호", "주민등록번호", "고유식별"], "주민등록번호 등 고유식별정보")],
     "depends_on": {"id": "personal", "not_in": ["처리 안 함"]}},
    {"id": "credit", "area": "데이터", "label": "신용정보 처리",
     "question": "대출·계좌·거래내역 같은 신용정보를 다루나요?",
     "options": ["처리함", "처리 안 함"],
     "infer": [(["대출", "신용", "계좌", "거래 데이터", "거래데이터", "거래내역", "여신", "카드"], "처리함")],
     "depends_on": {"id": "personal", "not_in": ["처리 안 함"]}},
    {"id": "overseas", "area": "데이터", "label": "해외 이전",
     "question": "데이터가 해외 서버·해외 클라우드로 전송되거나 보관되나요?",
     "options": ["있음", "없음"],
     "infer": [(["해외", "국외", "글로벌 리전", "해외 리전"], "있음")],
     "depends_on": {"id": "personal", "not_in": ["처리 안 함"]}},
    {"id": "hosting", "area": "인프라", "label": "구축 형태",
     "question": "시스템은 어디에 구축하나요?",
     "options": ["온프레미스(사내 전산센터)", "프라이빗 클라우드", "퍼블릭 클라우드", "SaaS 이용"],
     "infer": [(["saas"], "SaaS 이용"),
               (["퍼블릭 클라우드", "aws", "azure", "gcp"], "퍼블릭 클라우드"),
               (["프라이빗 클라우드"], "프라이빗 클라우드"),
               (["클라우드"], "프라이빗 클라우드"),
               (["사내 서버", "전용 서버", "온프레미스", "전산센터"], "온프레미스(사내 전산센터)")]},
    {"id": "network", "area": "인프라", "label": "외부망 연동",
     "question": "외부망과는 어떻게 연결되나요?", "multi": True, "multi_infer": True,
     "options": ["인터넷에 노출(대고객 채널)", "외부 기관·업체와 전용선/API 연동", "내부망 전용"],
     "infer": [(["모바일", "앱", "인터넷", "비대면", "웹"], "인터넷에 노출(대고객 채널)"),
               (["외부 api", "오픈뱅킹", "제휴", "외부 기관"], "외부 기관·업체와 전용선/API 연동")]},
    {"id": "vendor", "area": "계약", "label": "외부 업체 참여",
     "question": "외부 업체가 참여하나요?", "multi": True,
     "options": ["외부 업체가 개발·구축", "외부 업체가 유지보수·운영", "SaaS 업체가 제공·운영", "자체 개발·운영"],
     "infer": [(["saas"], "SaaS 업체가 제공·운영"),
               (["유지보수", "운영 용역"], "외부 업체가 유지보수·운영"),
               (["업체", "용역", "외주", "수의계약", "발주"], "외부 업체가 개발·구축")]},
    {"id": "license", "area": "계약", "label": "라이선스·구독",
     "question": "상용 소프트웨어 라이선스나 구독(SaaS) 비용이 있나요?",
     "options": ["있음", "없음"],
     "infer": [(["라이선스", "구독", "saas"], "있음")]},
    {"id": "outsourcing", "area": "계약", "label": "개인정보 처리 위탁",
     "question": "외부 업체(또는 SaaS)가 개인정보를 대신 처리·보관하나요?",
     "options": ["있음", "없음"],
     "infer": [(["위탁"], "있음")],
     "depends_on": {"id": "personal", "not_in": ["처리 안 함"]}},
    {"id": "audience", "area": "서비스", "label": "이용 대상",
     "question": "주 이용자는 누구인가요?",
     "options": ["대고객", "임직원", "대고객+임직원"],
     "infer": [(["그룹웨어", "임직원", "사내", "직원용", "내부 업무"], "임직원"),
               (["고객", "농업인", "모바일 뱅킹", "인터넷뱅킹", "비대면"], "대고객")]},
    {"id": "scale", "area": "서비스", "label": "예상 이용자 규모",
     "question": "예상 이용자(정보주체) 규모는 어느 정도인가요?",
     "options": ["1만 명 미만", "1만~100만 명", "100만 명 이상"],
     "infer": [], "service_only": True,
     "depends_on": {"id": "audience", "not_in": ["임직원"]}},
    {"id": "impact", "area": "서비스", "label": "장애 영향도",
     "question": "이 시스템이 멈추면 어떤 영향이 있나요?",
     "options": ["금융거래 중단", "고객 불편(조회·상담 등)", "내부 업무 지연"],
     "infer": [(["계정계", "이체", "결제", "지급결제"], "금융거래 중단")]},
    {"id": "genai", "area": "기술", "label": "생성형 AI 활용",
     "question": "생성형 AI(LLM)를 사용하나요?",
     "options": ["사용(외부 LLM API)", "사용(내부 구축 모델)", "사용 안 함"],
     "infer": [(["생성형", "llm", "gpt", "claude"], "사용(외부 LLM API)")], "service_only": True},
    {"id": "external_api", "area": "기술", "label": "외부 API 연동",
     "question": "외부 기관·업체의 API와 연동하나요?",
     "options": ["연동함", "연동 안 함"],
     "infer": [(["api", "오픈뱅킹", "마이데이터", "연동"], "연동함")], "service_only": True},
    {"id": "budget", "area": "예산", "label": "예상 사업비",
     "question": "예상 사업비(부가세 포함)는 어느 구간인가요? (전결권자 판단용)",
     "options": ["5백만원 이하", "5백만원 초과~3천만원 이하", "3천만원 초과~1억원 이하", "1억원 초과", "미정"],
     "infer": []},
]
FIELD_BY_ID = {f["id"]: f for f in FIELDS}

# 이 값이면 "해당 없음"으로 보고 규칙 판단용 문장에서 뺀다.
NEGATIVE_VALUES = {"처리 안 함", "없음", "해당 없음", "연동 안 함", "사용 안 함", "자체 개발·운영",
                   "내부망 전용", "미정", "미확인", "모름"}
# 예산은 구간 값이라 금액 규칙(전결)에 넣으면 경계값이 실제 금액처럼 읽히므로 규칙 문장에서 뺀다.
NOT_FOR_RULES = {"budget"}


# 서비스를 새로 만드는 게 아니라 유지보수·장비 구매 같은 조달 건이면
# 서비스 기술 항목(service_only: 생성형 AI·외부 API·이용자 규모)은 묻지 않는다.
PROCUREMENT_WORDS = ["유지보수", "장비", "스토리지", "하드웨어", "라이선스 갱신", "서버 증설"]
SERVICE_WORDS = ["서비스", "플랫폼", "앱", "챗봇", "채널", "고객"]


def _hits(low: str, words: list[str]) -> list[str]:
    return [w for w in words if w in low]


def suggest_project_name(question: str) -> str:
    """질문에서 '…서비스/플랫폼/시스템/챗봇/앱' 같은 대상 이름을 뽑아 프로젝트명 후보로 쓴다."""
    m = re.search(r"((?:[가-힣A-Za-z0-9·]+\s){0,3}[가-힣A-Za-z0-9·]*"
                  r"(?:서비스|플랫폼|시스템|챗봇|앱|용역|스토리지|솔루션))", question)
    if not m:
        return ""
    # 조사·어미로 끝나는 단어(장비와, 호환되는, 활용한 …)는 이름에서 뺀다.
    words = [w for w in m.group(1).split() if not re.search(r"(을|를|이|가|에|의|로|과|와|는|한|하려)$", w)]
    name = " ".join(words[-3:]).strip()
    if not name or name.endswith(("구축", "도입", "전환", "용역")):
        return name
    suffix = next((s for s in ("전환", "도입", "구축") if s in question), "구축")
    return f"{name} {suffix}"


def keyword_profile(question: str) -> dict:
    """질문에 나온 단어로 추론 항목과 질문 목록을 만든다."""
    low = question.lower()
    procurement = bool(_hits(low, PROCUREMENT_WORDS)) and not _hits(low, SERVICE_WORDS)
    inferred, questions = [], []
    for f in FIELDS:
        if procurement and f.get("service_only"):
            continue
        values, reasons = [], []
        for words, value in f["infer"]:
            hit = _hits(low, words)
            if hit and value not in values:
                values.append(value)
                reasons += hit
            if values and not f.get("multi_infer"):
                break
        if f["id"] == "budget":
            amount = parse_contract_amount(question)
            if amount:
                values, reasons = [f"약 {format_won(amount['total'])}"], ["금액"]
        if values:
            inferred.append({"id": f["id"], "area": f["area"], "label": f["label"],
                             "value": ", ".join(values),
                             "reason": "질문에 " + ", ".join(f"'{w}'" for w in reasons[:3]) + " 언급"})
        else:
            questions.append({k: f[k] for k in ("id", "area", "label", "question", "options")}
                             | {"multi": f.get("multi", False), "depends_on": f.get("depends_on")})

    # 민감·신용정보를 다룬다고 추론됐으면 개인정보 처리도 추론된 것으로 본다.
    found = {i["id"] for i in inferred}
    if "personal" not in found and found & {"sensitive", "credit"}:
        questions = [q for q in questions if q["id"] != "personal"]
        inferred.insert(0, {"id": "personal", "area": "데이터", "label": "개인정보 처리", "value": "처리함",
                            "reason": "민감·신용정보 처리에서 추론"})
    return {"suggested_name": suggest_project_name(question), "inferred": inferred, "questions": questions}


def _catalog_text() -> str:
    lines = []
    for f in FIELDS:
        dep = f.get("depends_on")
        cond = f" (단, {dep['id']} 값이 {dep['not_in']} 이면 묻지 않음)" if dep else ""
        lines.append(f"- id={f['id']} | {f['area']} · {f['label']} | 보기: {f['options']}"
                     f"{' (복수 선택)' if f.get('multi') else ''}{cond}")
    return "\n".join(lines)


def _clean_ai_profile(raw: dict) -> dict | None:
    """AI 응답을 화면에서 쓰는 형식으로 정리한다. 형식이 틀리면 None."""
    inferred, questions = [], []
    for it in raw.get("inferred", []):
        if it.get("label") and it.get("value"):
            inferred.append({"id": str(it.get("id") or it["label"]), "area": it.get("area") or "기타",
                             "label": it["label"], "value": str(it["value"]), "reason": it.get("reason", "")})
    seen = {i["id"] for i in inferred}
    for q in raw.get("questions", []):
        options = [str(o) for o in q.get("options", []) if str(o).strip()]
        qid = str(q.get("id") or q.get("label") or "")
        if not qid or qid in seen or not q.get("question") or len(options) < 2:
            continue
        seen.add(qid)
        dep = q.get("depends_on")
        dep = dep if isinstance(dep, dict) and dep.get("id") and isinstance(dep.get("not_in"), list) else None
        questions.append({"id": qid, "area": q.get("area") or "기타", "label": q.get("label") or qid,
                          "question": q["question"], "options": options[:6],
                          "multi": bool(q.get("multi")), "depends_on": dep})
    if not inferred and not questions:
        return None
    return {"suggested_name": str(raw.get("suggested_name") or "").strip(), "inferred": inferred, "questions": questions}


async def ai_profile(question: str, api_key: str, model: str) -> dict:
    """Claude가 질문을 보고 추론 항목·질문 목록을 만든다. 실패하면 keyword_profile."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""당신은 은행 IT본부에서 신규 프로젝트를 검토하기 전에 기본 정보를 수집하는 담당자입니다.

사업 아이디어: "{question}"

아래 수집 항목 카탈로그를 참고해 프로젝트 프로파일을 만드세요.
{_catalog_text()}

규칙:
1. 사업 아이디어에서 합리적으로 추론할 수 있는 항목은 질문하지 말고 inferred에 값과 근거(reason, 30자 안팎)를 적으세요.
2. 이 프로젝트와 무관한 항목은 inferred에도 questions에도 넣지 마세요.
3. 추론할 수 없고 검토에 꼭 필요한 항목만 questions에 넣으세요. 카탈로그 보기를 그대로 쓰는 것을 우선하세요.
4. 카탈로그에 없지만 이 프로젝트 검토에 꼭 필요한 정보가 있으면 새 id·area로 질문을 추가하세요(최대 2개).
5. suggested_name에는 사업 아이디어에 어울리는 짧은 프로젝트명(20자 이내)을 제안하세요.

아래 JSON 형식으로만 응답하세요:
{{"suggested_name": "프로젝트명",
  "inferred": [{{"id": "overseas", "area": "데이터", "label": "해외 이전", "value": "있음", "reason": "해외 서버로 전송한다고 언급"}}],
  "questions": [{{"id": "hosting", "area": "인프라", "label": "구축 형태", "question": "시스템은 어디에 구축하나요?",
                 "options": ["온프레미스(사내 전산센터)", "퍼블릭 클라우드"], "multi": false,
                 "depends_on": {{"id": "personal", "not_in": ["처리 안 함"]}}}}]}}
depends_on은 필요할 때만 넣고, 아니면 null로 두세요."""
    try:
        resp = client.messages.create(model=model, max_tokens=1500,
                                      messages=[{"role": "user", "content": prompt}])
        match = re.search(r"\{.*\}", resp.content[0].text, re.DOTALL)
        cleaned = _clean_ai_profile(json.loads(match.group())) if match else None
    except Exception:
        cleaned = None
    if not cleaned:
        return keyword_profile(question)
    if not cleaned["suggested_name"]:
        cleaned["suggested_name"] = suggest_project_name(question)
    return cleaned


def profile_prompt(profile: dict) -> str:
    """답변·이슈 추출에 넘길 프로파일 요약 (해당 없음 값 포함 전체)."""
    lines = [f"- 프로젝트명: {profile.get('project_name', '')}"]
    if profile.get("start_date") and profile.get("end_date"):
        lines.append(f"- 프로젝트 기간: {profile['start_date']} ~ {profile['end_date']}")
    for it in profile.get("items", []):
        lines.append(f"- {it['area']} · {it['label']}: {it['value']}")
    return "\n".join(lines)


def profile_rule_text(profile: dict) -> str:
    """단어 규칙(리스크·이슈·전결)에 덧붙일 문장. 해당 없음 값과 예산 구간은 뺀다."""
    parts = []
    for it in profile.get("items", []):
        if it.get("id") in NOT_FOR_RULES:
            continue
        values = [v.strip() for v in it["value"].split(",") if v.strip() not in NEGATIVE_VALUES]
        if values:
            parts.append(f"{it['label']} {', '.join(values)}")
    return " / ".join(parts)
