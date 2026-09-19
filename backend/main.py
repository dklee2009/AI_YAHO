import os
import io
import json
import asyncio
import random
import re
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from docx import Document
from dotenv import load_dotenv
from law_scraper import find_relevant_articles, get_law_summary

load_dotenv()

app = FastAPI(title="AI Agent Chat API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
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
사용자가 제시하는 IT 프로젝트나 서비스 아이디어를 다음 관점에서 종합적으로 검토합니다:
- 플랫폼/시스템: 아키텍처, API, 인프라, 기술 구현
- 보안: 취약점, 암호화, 위협 대응
- 규정/컴플라이언스: 금융 규제, 개인정보보호법, 사내 정책
- 인증/권한: 로그인, 세션, 접근 제어

질문과 관련 있는 관점들을 종합해서 실용적이고 명확한 하나의 답변으로 정리해 주세요.
한국어로 응답하세요."""

MOCK_RESPONSES = {
    "platform": [
        "플랫폼 관점에서 검토했습니다.\n\n현재 구조에서는 **API Gateway**를 통한 요청 라우팅이 적합하며, 마이크로서비스 아키텍처 적용 시 서비스 간 통신은 gRPC 또는 REST를 상황에 맞게 선택해야 합니다.\n\n구체적인 구현 방향:\n- 서비스 디스커버리: Kubernetes + Istio\n- 모니터링: Prometheus + Grafana\n- CI/CD: GitLab Pipeline\n\n추가 요건이 있으시면 말씀해 주세요.",
        "시스템 통합 측면에서 말씀드리겠습니다.\n\n기존 레거시 시스템과의 연동은 **Anti-Corruption Layer(ACL)** 패턴을 활용하는 것을 권장합니다. 신규 플랫폼과 기존 시스템 간의 데이터 변환 로직을 분리하면 추후 마이그레이션이 용이합니다.\n\n단계적 전환 계획을 수립하여 진행하는 것이 안전합니다.",
        "해당 질문에 대해 플랫폼솔루션 관점에서 답변드립니다.\n\n현재 NH농협은행 IT 환경에서는 **온프레미스 + 하이브리드 클라우드** 구성이 기본입니다. 신규 서비스 개발 시 클라우드 네이티브 설계를 우선 적용하되, 금융 규제 요건을 충족하는 범위 내에서 진행해야 합니다.",
    ],
    "security": [
        "보안 관점에서 중요한 사항들을 짚어드리겠습니다.\n\n1. **전송 구간 암호화**: TLS 1.3 이상 필수 적용\n2. **최소 권한 원칙**: 각 서비스에 필요한 최소한의 접근 권한만 부여\n3. **입력값 검증**: SQL Injection, XSS 등 OWASP Top 10 대응\n4. **로그 관리**: 접근 로그 180일 이상 보관 (금융보안원 기준)\n\n정기적인 취약점 점검과 침투 테스트도 필수입니다.",
        "보안 위협 분석 결과를 공유합니다.\n\n현재 설계에서 주의해야 할 부분은 **세션 하이재킹** 방지입니다. HTTPS Only, Secure/HttpOnly 쿠키 설정, CSRF Token 적용이 기본입니다.\n\n또한 민감 정보(주민번호, 계좌번호)는 저장 시 AES-256 암호화를 적용해야 하며, 키 관리는 HSM(Hardware Security Module)을 통해 별도로 관리해야 합니다.",
    ],
    "regulation": [
        "규정 측면에서 검토하겠습니다.\n\n해당 사항은 **전자금융감독규정 제15조**와 **개인정보보호법 제29조**에 해당합니다.\n\n진행 전 필수 확인 사항:\n- 준법감시팀 사전 검토 및 승인\n- IT컴플라이언스 자가점검 체크리스트 완료\n- 변경 이력 관리 시스템 등록\n\n금융위원회 감독 기준 변경이 있을 수 있으니 최신 고시를 확인해 주세요.",
        "IT 규정 준수 관점에서 안내드립니다.\n\n**전자금융거래법** 및 **정보통신망법**에 따라 다음 절차가 필요합니다:\n\n1. 위험평가 실시 (분기 1회)\n2. 정보보호 관리체계(ISMS) 심사 대응\n3. 내부 통제 기준 적용 여부 확인\n\n세부 기준은 내부 IT컴플라이언스 지침을 참조하시고, 불명확한 부분은 준법감시팀에 문의 주세요.",
    ],
    "auth": [
        "인증 체계 관점에서 말씀드리겠습니다.\n\n**권장 구조:**\n```\nAccess Token:  JWT (유효기간 1시간)\nRefresh Token: Opaque Token (유효기간 7일, DB 저장)\n```\n\n토큰 재발급 시 Refresh Token Rotation 적용을 권장합니다. 탈취 시 즉시 무효화가 가능하도록 Redis 기반 블랙리스트 관리도 고려해 주세요.\n\nMFA(다중인증)는 관리자 계정 및 고위험 거래에 필수 적용이 필요합니다.",
        "SSO(Single Sign-On) 구현 방안입니다.\n\nOAuth 2.0 + OIDC 기반으로 구성하되, NH 내부 시스템과의 연동은 **SAML 2.0** 프로토콜도 검토가 필요합니다.\n\n공인인증서 연동의 경우 전자서명법 개정(2021)에 따라 민간 인증서(PASS, 카카오 등) 병행 사용이 가능합니다. 내부 정책 확인 후 적용 범위를 결정해 주세요.",
    ],
}


# 체크리스트 카테고리. 지금은 두 개로 시작하지만 이후 계속 추가될 예정이라
# 프론트/백엔드 모두 이 id를 기준으로 동적으로 섹션을 만든다.
CATEGORY_LABELS = {
    "security": "보안 (개인정보보호·정보보안 법/규정)",
    "it": "IT (서비스 구현 체크리스트)",
}

# Mock 모드 이슈 후보. 카테고리별로 묶어두고 매번 두 카테고리 모두에서 뽑아
# 질문 내용(topics)과 무관하게 항상 IT/보안 두 카드가 다 나오도록 보장한다.
MOCK_ISSUES_BY_CATEGORY = {
    "it": [
        "API Gateway 트래픽 급증 대비 Rate Limiting 정책 수립 필요",
        "레거시 시스템 연동 시 데이터 정합성 검증 절차 필요",
        "마이크로서비스 장애 전파 방지(Circuit Breaker) 설계 필요",
        "전송 구간 TLS 1.3 이상 적용 여부 확인 필요",
        "MFA(다중인증) 적용 대상 계정 범위 확정 필요",
        "Refresh Token Rotation 및 탈취 대응 방안 수립 필요",
    ],
    "security": [
        "민감정보(주민번호·계좌번호) 저장 시 AES-256 암호화 적용 필요",
        "접근 로그 180일 이상 보관 정책 수립 필요 (금융보안원 기준)",
        "개인정보보호법 제29조 안전조치 의무 이행 여부 확인 필요",
        "전자금융감독규정에 따른 준법감시팀 사전 검토·승인 필요",
        "변경 이력 관리시스템 등록 여부 확인 필요",
        "공인/민간 인증서 병행 정책의 법적 근거 확인 필요",
    ],
}


# 질문 문장 자체에 카테고리별 키워드가 실제로 있는지 봐서 관련성을 판단.
# (TOPICS 라우팅과 별개로, "이슈를 뽑을 가치가 있는 카테고리인지"만 본다)
ISSUE_CATEGORY_KEYWORDS = {
    "it": TOPICS["platform"]["keywords"] + TOPICS["auth"]["keywords"],
    "security": TOPICS["security"]["keywords"] + TOPICS["regulation"]["keywords"],
}


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
        for text in random.sample(pool, k=min(2, len(pool))):
            items.append({
                "id": uuid.uuid4().hex,
                "text": text,
                "category_id": category_id,
                "category_label": CATEGORY_LABELS[category_id],
            })
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

실제로 질문/답변 내용과 관련이 있는 이슈만 뽑으세요. 억지로 채우지 말고, 어느 한
카테고리에 해당하는 이슈가 없으면 그 카테고리는 아예 비워두세요(둘 다 없으면 빈 배열도 가능).

아래 JSON 형식으로만 응답하세요:
{{"items": [{{"text": "이슈 설명", "category_id": "security 또는 it"}}]}}"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        match = re.search(r'\{.*\}', resp.content[0].text, re.DOTALL)
        raw_items = json.loads(match.group()).get("items", []) if match else []
        return [
            {
                "id": uuid.uuid4().hex,
                "text": it["text"],
                "category_id": it["category_id"],
                "category_label": CATEGORY_LABELS.get(it["category_id"], it["category_id"]),
            }
            for it in raw_items if it.get("category_id") in CATEGORY_LABELS and it.get("text")
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

    reply = "\n\n".join(random.choice(MOCK_RESPONSES[t]) for t in topics)
    if law_context:
        reply = law_context + "\n\n---\n\n" + reply

    for char in reply:
        yield f"data: {json.dumps({'type': 'text', 'text': char})}\n\n"
        await asyncio.sleep(0.010 if char not in "\n " else 0.003)

    yield f"data: {json.dumps({'type': 'answer_done'})}\n\n"

    relevant = relevant_issue_categories(question)
    issues = pick_mock_issues(relevant)
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
            "\n\n다음은 관련 법령 조문입니다. 필요한 경우 답변에 인용하여 근거를 명확히 제시하세요:\n\n"
            + law_context
        )

    yield f"data: {json.dumps({'type': 'answer_start'})}\n\n"

    collected = []
    try:
        with client.messages.stream(
            model=model, max_tokens=2000,
            system=system_prompt, messages=messages,
        ) as stream:
            for text in stream.text_stream:
                collected.append(text)
                yield f"data: {json.dumps({'type': 'text', 'text': text})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'text', 'text': f'[오류: {e}]'})}\n\n"

    yield f"data: {json.dumps({'type': 'answer_done'})}\n\n"

    reply = "".join(collected)
    issues = await extract_issues_real(last_question, reply)
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


class ChecklistItemIn(BaseModel):
    id: str
    text: str
    done: bool = False


class ChecklistCategoryIn(BaseModel):
    id: str
    title: str
    items: list[ChecklistItemIn]


class ChecklistExportRequest(BaseModel):
    categories: list[ChecklistCategoryIn]


@app.post("/export-checklist")
async def export_checklist(request: ChecklistExportRequest):
    doc = Document()
    doc.add_heading("IT 프로젝트 검토 체크리스트", level=1)

    for category in request.categories:
        if not category.items:
            continue
        doc.add_heading(category.title, level=2)
        for item in category.items:
            mark = "☑" if item.done else "☐"
            doc.add_paragraph(f"{mark}  {item.text}")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=checklist.docx"},
    )


@app.get("/health")
async def health():
    law_summary = await get_law_summary()
    return {
        "status": "ok",
        "mode": "mock" if USE_MOCK else "claude",
        "topics": list(TOPICS.keys()),
        "law_api_oc": bool(os.getenv("LAW_API_OC")),
        "law_mock_articles": law_summary,
    }