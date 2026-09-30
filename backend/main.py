import os
import json
import asyncio
import random
import re
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from dotenv import load_dotenv
from law_scraper import find_relevant_articles, get_law_summary
from owner_matcher import EMPLOYEES, assign_owner, infer_area
from checklist_docx import build_checklist_docx
from approval_rules import approval_brief, approval_items, approval_summary

load_dotenv()

app = FastAPI(title="AI Agent Chat API")

# 로컬 개발 주소 + 배포 시 ALLOWED_ORIGINS(쉼표 구분, 예: https://ai-yaho-web.onrender.com)
ALLOWED_ORIGINS = ["http://localhost:5173", "http://localhost:3000"] + [
    o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
USE_MOCK = not API_KEY or API_KEY == "여기에_API_키_입력"

# 화면에는 더 이상 노출되지 않는, 내부적으로만 쓰는 주제 분류.
# 어떤 mock 응답/이슈 풀을 쓸지, 법령 조문을 조회할지 결정하는 용도로만 사용.
TOPICS = {
    "platform": {
        "keywords": ["플랫폼", "시스템", "솔루션", "api", "서버", "인프라", "아키텍처",
                     "통합", "클라우드", "개발", "구현", "기술", "연동", "배포", "마이크로서비스"],
    },
    "security": {
        "keywords": ["보안", "해킹", "취약점", "암호화", "방화벽", "공격", "위협",
                     "침해", "ssl", "tls", "암호", "보호", "위험", "사이버"],
    },
    "regulation": {
        "keywords": ["규정", "규제", "법률", "정책", "준수", "컴플라이언스", "감사",
                     "지침", "기준", "허가", "승인", "절차", "법적", "심의"],
    },
    "auth": {
        "keywords": ["인증", "로그인", "jwt", "oauth", "권한", "세션", "토큰",
                     "sso", "공인인증서", "비밀번호", "계정", "접근제어", "id", "패스워드"],
    },
}

ASSISTANT_SYSTEM_PROMPT = """당신은 NH농협은행 IT본부의 AI 어시스턴트입니다.
사용자가 제시하는 IT 프로젝트나 서비스 아이디어를 플랫폼·보안·규정·인증 관점에서 검토합니다.

답변은 핵심 요약만 짧게 작성하세요:
- 첫 줄은 "**핵심 요약**"
- 질문과 관련 있는 관점만 3~5개 글머리표로, 각 1문장(60자 안팎)
- 관련 법령이나 전결 판단이 있으면 "📚 **관련 법령**", "💼 **전결**"로 각각 한 줄만 덧붙임
- 서론·맺음말·같은 내용 반복·긴 설명은 쓰지 않음 (전체 400자 이내)
한국어로 응답하세요."""

# 주제 라벨과 mock 모드 한 줄 요약 후보 (매번 하나씩 무작위로 고른다)
TOPIC_LABELS = {"platform": "플랫폼", "security": "보안", "regulation": "규정", "auth": "인증"}
MOCK_SUMMARIES = {
    "platform": [
        "API Gateway로 라우팅하고, 레거시 연동은 ACL 패턴으로 분리해 단계적으로 전환하세요.",
        "온프레미스+하이브리드 클라우드 기준으로, 규제 범위 안에서 클라우드 네이티브로 설계하세요.",
        "Kubernetes 기반 배포에 Prometheus·Grafana 모니터링, CI/CD 파이프라인을 갖추세요.",
    ],
    "security": [
        "TLS 1.3, 최소 권한, OWASP Top 10 대응, 접근 로그 180일 보관이 기본입니다.",
        "민감정보는 AES-256 암호화·HSM 키 관리, 세션은 Secure/HttpOnly 쿠키와 CSRF 토큰으로 보호하세요.",
    ],
    "regulation": [
        "전자금융감독규정·개인정보보호법 적용 대상이라 준법감시팀 사전 검토가 필요합니다.",
        "위험평가·ISMS 대응·내부통제 기준 확인 후 진행하세요.",
    ],
    "auth": [
        "JWT(1시간)+Refresh Token(7일, Rotation) 구조에 고위험 거래는 MFA를 적용하세요.",
        "OAuth 2.0+OIDC 기반 SSO로 구성하고, 내부 연동은 SAML 2.0도 검토하세요.",
    ],
}


def law_brief(law_context: str) -> str:
    """법령 조문 전문 대신 법령별 조문 번호만 한 줄로 줄인다.
    예: 📚 관련 법령 전자금융거래법 제21조·제9조, 개인정보보호법 제29조"""
    by_law: dict[str, list[str]] = {}
    for law, article in re.findall(r"▸ \*\*(.+?)\s+(제\d+조(?:의\d+)?)\*\*", law_context):
        by_law.setdefault(law, []).append(article)
    if not by_law:
        return ""
    return "📚 **관련 법령** " + ", ".join(f"{law} {'·'.join(arts)}" for law, arts in by_law.items())


# 체크리스트 카테고리. 지금은 두 개로 시작하지만 이후 계속 추가될 예정이라
# 프론트/백엔드 모두 이 id를 기준으로 동적으로 섹션을 만든다.
CATEGORY_LABELS = {
    "security": "보안 (개인정보보호·정보보안 법/규정)",
    "it": "IT (서비스 구현 체크리스트)",
    "approval": "전결 (전결기준표·계약업무준칙)",
}

AI_EXTRACTED_CATEGORIES = {"security", "it"}

# Mock 모드 이슈 후보. 체크리스트 표의 한 줄(검토 분야 / 점검 질문 / 확인 필요사항)
# 형태로 묶어 두었다. 담당자는 인사파일에서 자동으로 고른다.
MOCK_ISSUES_BY_CATEGORY = {
    "it": [
        ("트래픽 관리", "API Gateway 트래픽 급증에 대비한 Rate Limiting 정책이 수립되었는가?", "호출 한도, 초과 시 처리 방식"),
        ("데이터 정합성", "레거시 시스템 연동 시 데이터 정합성 검증 절차가 마련되었는가?", "검증 대상 데이터, 대사 주기"),
        ("장애 대응", "마이크로서비스 장애 전파를 막는 Circuit Breaker가 설계되었는가?", "차단 임계치, 복구 절차"),
        ("전송 암호화", "전송 구간에 TLS 1.3 이상이 적용되었는가?", "적용 구간, 인증서 관리 주체"),
        ("다중 인증", "MFA(다중인증) 적용 대상 계정 범위가 확정되었는가?", "대상 계정 목록, 인증 수단"),
        ("토큰 관리", "Refresh Token Rotation과 토큰 탈취 대응 방안이 수립되었는가?", "토큰 유효기간, 폐기 절차"),
    ],
    "security": [
        ("개인정보 암호화", "민감정보(주민번호·계좌번호) 저장 시 AES-256 암호화가 적용되었는가?", "암호화 대상 항목, 키 관리 방식"),
        ("로그 보관", "접근 로그를 180일 이상 보관하는 정책이 수립되었는가? (금융보안원 기준)", "보관 기간, 저장 위치"),
        ("안전조치 의무", "개인정보보호법 제29조 안전조치 의무를 이행하였는가?", "내부관리계획, 점검 결과"),
        ("준법 검토", "전자금융감독규정에 따른 준법감시팀 사전 검토·승인을 받았는가?", "검토 요청서, 승인 일자"),
        ("변경 관리", "변경 이력 관리시스템에 등록되었는가?", "등록 번호, 변경 요청자"),
        ("인증서 정책", "공인/민간 인증서 병행 정책의 법적 근거가 확인되었는가?", "근거 법령, 적용 범위"),
    ],
}


def make_issue(category_id: str, text: str, area: str = "", check: str = "") -> dict:
    """체크리스트 한 줄 데이터를 만들고 인사파일 기준으로 담당자를 붙인다."""
    matched = assign_owner(f"{text} {check}", category_id, area)
    return {
        "id": uuid.uuid4().hex,
        "text": text,
        "area": area or infer_area(text),
        "check": check,
        "category_id": category_id,
        "category_label": CATEGORY_LABELS.get(category_id, category_id),
        "owner": matched["owner"],
        "candidates": matched["candidates"],
    }


# 질문 문장 자체에 카테고리별 키워드가 실제로 있는지 봐서 관련성을 판단.
# (TOPICS 라우팅과 별개로, "이슈를 뽑을 가치가 있는 카테고리인지"만 본다)
ISSUE_CATEGORY_KEYWORDS = {
    "it": TOPICS["platform"]["keywords"] + TOPICS["auth"]["keywords"],
    "security": TOPICS["security"]["keywords"] + TOPICS["regulation"]["keywords"],
}


def approval_issues(question: str) -> list[dict]:
    """전결 카테고리는 AI 추출 없이 전결기준표·계약업무준칙 규칙으로 항목을 만든다."""
    return [make_issue("approval", text, area, check) for area, text, check in approval_items(question)]


def relevant_issue_categories(text: str) -> list[str]:
    text_lower = text.lower()
    return [
        cat_id for cat_id, kws in ISSUE_CATEGORY_KEYWORDS.items()
        if any(kw in text_lower for kw in kws)
    ]


def pick_mock_issues(category_ids: list[str]) -> list[dict]:
    """실제로 관련 있다고 판단된 카테고리에서만 이슈를 뽑는다.
    관련 카테고리가 없으면 빈 리스트를 반환(=이슈 없음)."""
    items = []
    for category_id in category_ids:
        pool = MOCK_ISSUES_BY_CATEGORY.get(category_id, [])
        for area, text, check in random.sample(pool, k=min(2, len(pool))):
            items.append(make_issue(category_id, text, area, check))
    return items


async def extract_issues_real(question: str, reply: str) -> list[dict]:
    """AI 답변을 바탕으로 체크리스트에 올릴 이슈 후보를 추출.
    실패하면 빈 리스트를 반환(이슈 제안 없이 넘어감)."""
    import anthropic
    client = anthropic.Anthropic(api_key=API_KEY)

    prompt = f"""다음은 IT 프로젝트 질문과 AI의 검토 답변입니다.

질문: "{question}"

검토 답변:
{reply}

위 내용을 바탕으로, 프로젝트 진행 전 실제로 검토·체크해야 할 구체적인 이슈만 뽑아주세요.
각 이슈는 다음 중 하나의 category_id로 분류하세요:
- "security": 개인정보보호/정보보안 관련 법·규정 이슈
- "it": 서비스를 IT적으로 구현할 때 점검해야 할 기술적 이슈

각 이슈는 체크리스트 표의 한 줄이 되므로 다음 세 가지를 채우세요:
- area: 검토 분야를 2~7글자 명사로 (예: "토큰 관리", "개인정보 암호화")
- text: "~되었는가?" / "~하였는가?" 로 끝나는 점검 질문 한 문장
- check: 확인에 필요한 자료·값을 쉼표로 구분한 짧은 명사구 (예: "보관 기간, 저장 위치")

실제로 질문/답변 내용과 관련이 있는 이슈만 뽑으세요. 억지로 채우지 말고, 어느 한
카테고리에 해당하는 이슈가 없으면 그 카테고리는 아예 비워두세요(둘 다 없으면 빈 배열도 가능).

아래 JSON 형식으로만 응답하세요:
{{"items": [{{"area": "검토 분야", "text": "점검 질문", "check": "확인 필요사항", "category_id": "security 또는 it"}}]}}"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        match = re.search(r'\{.*\}', resp.content[0].text, re.DOTALL)
        raw_items = json.loads(match.group()).get("items", []) if match else []
        return [
            make_issue(it["category_id"], it["text"], it.get("area", ""), it.get("check", ""))
            for it in raw_items if it.get("category_id") in AI_EXTRACTED_CATEGORIES and it.get("text")
        ]
    except Exception:
        return []


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    model: str = "claude-sonnet-5"


def keyword_route(text: str) -> list[str]:
    """어떤 주제와 관련 있는 질문인지 내부적으로만 판단(화면에는 노출 안 함).
    mock 응답/이슈 풀 선택, 법령 조문 조회 여부 결정에 사용."""
    text_lower = text.lower()
    selected = [k for k, t in TOPICS.items() if any(kw in text_lower for kw in t["keywords"])]
    return selected if selected else ["platform"]


PROJECT_KEYWORDS = [
    "프로젝트", "기획", "사업", "구축", "도입", "런칭", "출시", "제안서",
    "계획서", "구상", "추진", "신규 서비스", "신규 시스템", "개발하려",
]


def keyword_is_project_question(text: str) -> bool:
    return any(kw in text for kw in PROJECT_KEYWORDS)


async def is_project_question(text: str) -> bool:
    """첫 질문이 프로젝트 기획/사업 구상에 관한 내용인지 판단.
    Mock 모드나 API 실패 시 키워드 휴리스틱으로 폴백."""
    if USE_MOCK:
        return keyword_is_project_question(text)

    import anthropic
    client = anthropic.Anthropic(api_key=API_KEY)
    prompt = f"""다음 사용자 입력이 'IT 프로젝트 기획' 또는 '사업 구상'에 관한 내용인지 판단하세요.
(예: 신규 시스템 구축 계획, 서비스 출시 아이디어, IT 프로젝트/사업 제안 등)

입력: "{text}"

프로젝트 기획/사업 구상 내용이면 yes, 아니면 no 라고만 답하세요."""
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=8,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = resp.content[0].text.strip().lower()
        return answer.startswith("y")
    except Exception:
        return keyword_is_project_question(text)


def is_first_turn(messages: list[dict]) -> bool:
    """대화 이력에 담당자(assistant) 응답이 아직 없으면 첫 질문으로 간주."""
    return not any(m["role"] == "assistant" for m in messages[:-1])


async def clarify_stream():
    message = (
        "입력하신 내용이 프로젝트 기획이나 사업 구상에 관한 질문인지 확인이 필요해요. "
        "검토를 원하시는 IT 프로젝트 계획이나 사업 아이디어를 조금 더 구체적으로 설명해 주시겠어요?"
    )
    await asyncio.sleep(0.3)
    yield f"data: {json.dumps({'type': 'clarify', 'message': message})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def mock_agent_stream(question: str):
    topics = keyword_route(question)

    # regulation 관련 질문이면 관련 법령 조문 사전 조회
    law_context = ""
    if "regulation" in topics:
        await asyncio.sleep(0.3)
        yield f"data: {json.dumps({'type': 'law_searching'})}\n\n"
        law_context = await find_relevant_articles(question)
        await asyncio.sleep(0.2)

    yield f"data: {json.dumps({'type': 'answer_start'})}\n\n"
    await asyncio.sleep(0.2)

    lines = ["**핵심 요약**"]
    lines += [f"- **{TOPIC_LABELS[t]}** {random.choice(MOCK_SUMMARIES[t])}" for t in topics]
    extras = [law_brief(law_context), approval_brief(question)]
    reply = "\n".join(lines) + "".join(f"\n\n{e}" for e in extras if e)

    for char in reply:
        yield f"data: {json.dumps({'type': 'text', 'text': char})}\n\n"
        await asyncio.sleep(0.010 if char not in "\n " else 0.003)

    yield f"data: {json.dumps({'type': 'answer_done'})}\n\n"

    relevant = relevant_issue_categories(question)
    issues = pick_mock_issues(relevant) + approval_issues(question)
    await asyncio.sleep(0.3)
    yield f"data: {json.dumps({'type': 'issue_suggestion', 'items': issues, 'checked_categories': list(CATEGORY_LABELS.keys())})}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def real_agent_stream(messages: list[dict], model: str):
    import anthropic
    client = anthropic.Anthropic(api_key=API_KEY)

    last_question = messages[-1]["content"] if messages else ""
    topics = keyword_route(last_question)

    # regulation 관련 질문이면 관련 법령 조문 사전 조회
    law_context = ""
    if "regulation" in topics:
        yield f"data: {json.dumps({'type': 'law_searching'})}\n\n"
        law_context = await find_relevant_articles(last_question)

    system_prompt = ASSISTANT_SYSTEM_PROMPT
    if law_context:
        system_prompt += (
            "\n\n다음은 관련 법령 조문입니다. 조문 내용을 옮겨 적지 말고 📚 **관련 법령** 한 줄에 조문 번호만 적으세요:\n\n"
            + law_context
        )

    approval_text = approval_summary(last_question)
    if approval_text:
        system_prompt += (
            "\n\n다음은 사내 전결기준표·계약업무준칙에 따라 규칙으로 판단한 결과입니다. "
            "금액·전결권자는 이 내용을 그대로 따르고 답변 끝에 💼 **전결** 한 줄로만 요약하세요:\n\n" + approval_text
        )

    yield f"data: {json.dumps({'type': 'answer_start'})}\n\n"

    collected = []
    try:
        with client.messages.stream(
            model=model, max_tokens=700,
            system=system_prompt, messages=messages,
        ) as stream:
            for text in stream.text_stream:
                collected.append(text)
                yield f"data: {json.dumps({'type': 'text', 'text': text})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'text', 'text': f'[오류: {e}]'})}\n\n"

    yield f"data: {json.dumps({'type': 'answer_done'})}\n\n"

    reply = "".join(collected)
    issues = await extract_issues_real(last_question, reply) + approval_issues(last_question)
    yield f"data: {json.dumps({'type': 'issue_suggestion', 'items': issues, 'checked_categories': list(CATEGORY_LABELS.keys())})}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


@app.post("/agent-chat")
async def agent_chat(request: ChatRequest):
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    question = messages[-1]["content"] if messages else ""

    if is_first_turn(messages) and not await is_project_question(question):
        gen = clarify_stream()
    else:
        gen = mock_agent_stream(question) if USE_MOCK else real_agent_stream(messages, request.model)

    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class OwnerIn(BaseModel):
    emp_no: str
    name: str
    dept: str = ""
    team: str = ""
    title: str = ""
    duty: str = ""


class ChecklistItemIn(BaseModel):
    id: str
    text: str
    done: bool = False
    no: str = ""
    area: str = ""
    check: str = ""
    owner: OwnerIn | None = None


class ChecklistCategoryIn(BaseModel):
    id: str
    title: str
    items: list[ChecklistItemIn]


class ChecklistExportRequest(BaseModel):
    categories: list[ChecklistCategoryIn]


@app.post("/export-checklist")
async def export_checklist(request: ChecklistExportRequest):
    content = build_checklist_docx([c.model_dump() for c in request.categories])
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=checklist.docx"},
    )


class AssignOwnerRequest(BaseModel):
    text: str
    category_id: str


@app.post("/assign-owner")
async def assign_owner_endpoint(request: AssignOwnerRequest):
    """체크리스트에 직접 추가한 항목의 검토 분야와 담당자를 인사파일 기준으로 판단."""
    return {"area": infer_area(request.text), **assign_owner(request.text, request.category_id)}


@app.get("/health")
async def health():
    law_summary = await get_law_summary()
    return {
        "status": "ok",
        "mode": "mock" if USE_MOCK else "claude",
        "topics": list(TOPICS.keys()),
        "law_api_oc": bool(os.getenv("LAW_API_OC")),
        "employees": len(EMPLOYEES),
        "law_mock_articles": law_summary,
    }