"""전결기준표(YH-ADM-001)·계약 관련 업무준칙(YH-CON-001) 기반 전결 체크리스트.

질문 문장에서 계약총액과 계약 특성(반복계약, 수의계약, 선급금 …)을 읽어
규정에 맞는 점검 항목과 전결권자를 규칙으로 판단한다. AI 추출이 아니라 규정을
그대로 코드로 옮긴 것이므로 mock/실제 모드 모두 같은 결과가 나온다.
"""
import re

MAN = 10_000
EOK = 100_000_000

# 본사 금액 구간별 전결권자 (전결기준표 2-라, 3-나·다, 4-가·바). 금액은 부가세 포함 총부담액.
AUTHORITY_TIERS = [
    (5_000_000, "팀장", "5백만원 이하"),
    (30_000_000, "부서장", "5백만원 초과 3천만원 이하"),
    (100_000_000, "총괄임원", "3천만원 초과 1억원 이하"),
    (None, "대표이사", "1억원 초과"),
]
TIER_GUIDE = "5백만원 이하 팀장 · 3천만원 이하 부서장 · 1억원 이하 총괄임원 · 초과 대표이사"

FLAGS = {
    "contract": ["계약", "구매", "발주", "용역", "외주", "업체", "입찰",
                 "납품", "공사", "라이선스", "유지보수", "구독", "임차", "렌탈", "리스"],
    # 도입·구축만 있고 금액·계약 표현이 없으면 핵심 항목만 제시한다.
    "project": ["도입", "구축"],
    "recurring": ["유지보수", "구독", "임차", "렌탈", "리스", "단가", "연간", "매년", "매월"],
    "sole": ["수의", "독점", "단독", "호환"],
    "urgent": ["긴급", "급하게", "사후결재"],
    "advance": ["선급", "선금", "착수금"],
    "major": ["지급보증", "무제한", "지식재산", "소스코드 양도"],
    "related": ["특수관계", "계열사", "이해관계", "친인척"],
    "privacy": ["개인정보", "재위탁", "위탁", "지식재산"],
    "change": ["변경계약", "증액", "추가과업", "추가 과업", "계약 연장", "기간 연장"],
    "budget_out": ["미편성", "예산 초과", "추가 예산", "예산이 없"],
    "invest": ["투자계획", "투자 계획", "신규 투자"],
    "data_out": ["외부 제공", "반출", "제3자 제공"],
    "new_biz": ["신규", "구축", "도입", "추진", "사업"],
    "competition": ["입찰", "경쟁", "제안요청", "rfp"],
}

# "1억 2천만원", "2천5백만원", "4,000만원", "1.5억", "12,000,000원" 같은 금액 표현
_AMOUNT = (r"(?:\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|십만|만|천|백|십)\s*)+(?:\d[\d,]*\s*)?원?"
           r"|\d{1,3}(?:,\d{3}){2,}\s*원|\d{7,}\s*원")
_SMALL = {"천": 1000, "백": 100, "십": 10}
_BIG = {"만": MAN, "억": EOK}
# 연간/월 금액 앞 글자가 한글이면(예: "관련 5천만원"의 '연') 반복 금액으로 보지 않는다.
_ANNUAL = re.compile(rf"(?<![가-힣\d])(연간|매년|해마다|연)\s*({_AMOUNT})")
_MONTHLY = re.compile(rf"(?<![가-힣\d])(월|매월)\s*({_AMOUNT})")
_YEARS = re.compile(r"(?<!\d)(\d{1,2})\s*(?:개년|년)(?:간|동안)?")
_MONTHS = re.compile(r"(?<!\d)(\d{1,3})\s*개월")
_SPLIT = re.compile(rf"({_AMOUNT})\s*씩\s*(\d{{1,2}})\s*(?:회|건|차|번)")


def _to_won(token: str) -> int:
    """한국어 금액 표현을 원 단위 정수로. 천·백·십은 만·억 단위 안의 자릿수로 누적한다."""
    total, group = 0.0, 0.0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(천만|백만|십만|억|만|천|백|십)?", token.replace(",", "").replace(" ", "")):
        value = float(num)
        if unit in _SMALL:
            group += value * _SMALL[unit]
        elif unit in _BIG:
            total += (group + value) * _BIG[unit]
            group = 0
        elif unit:  # 천만·백만·십만 = 작은 단위 × 만
            total += (group + value * _SMALL[unit[0]]) * MAN
            group = 0
        else:
            group += value
    # "1억5천"처럼 억 뒤에 만 없이 끝나면 관용적으로 "1억5천만"으로 본다.
    if total >= EOK and 0 < group < MAN:
        group *= MAN
    return int(round(total + group))


def format_won(amount: int) -> str:
    """120_000_000 → '1억 2,000만원', 25_000_000 → '2,500만원'."""
    eok, rest = divmod(int(round(amount / MAN)) * MAN, EOK)
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if rest:
        parts.append(f"{rest // MAN:,}만")
    return (" ".join(parts) or "0") + "원"


def parse_contract_amount(text: str) -> dict | None:
    """질문에서 계약총액을 읽는다. 반복계약(연간/월 금액)은 기간을 곱해 합산하고,
    기간이 없으면 준칙 제4조 5호에 따라 12개월로 본다. 부가세 별도면 10%를 더한다."""
    compact = text.replace(" ", "")
    amounts = [(m.start(), _to_won(m.group())) for m in re.finditer(_AMOUNT, text)]
    amounts = [(pos, won) for pos, won in amounts if won >= MAN]
    if not amounts:
        return None

    vat_excluded = bool(re.search(r"(부가세|부가가치세|vat)별도", compact, re.I))
    annual = _ANNUAL.search(text)
    monthly = _MONTHLY.search(text)
    years = _YEARS.search(text)
    months = _MONTHS.search(text)
    split = _SPLIT.search(text)

    if split:  # 동일 목적 분할 발주는 합산한다(전결기준표 공통 ②).
        unit, times = _to_won(split.group(1)), int(split.group(2))
        total, basis = unit * times, f"{format_won(unit)} × {times}회 분할분 합산"
    elif annual:
        unit = _to_won(annual.group(2))
        n_years = int(years.group(1)) if years else 1
        total, basis = unit * n_years, f"연간 {format_won(unit)} × {n_years}년" + ("" if years else "(기간 미정 → 12개월)")
    elif monthly:
        unit = _to_won(monthly.group(2))
        n_months = int(months.group(1)) if months else (int(years.group(1)) * 12 if years else 12)
        total, basis = unit * n_months, f"월 {format_won(unit)} × {n_months}개월" + ("" if (months or years) else "(기간 미정)")
    else:
        total, basis = max(won for _, won in amounts), ""

    if vat_excluded:
        total = int(round(total * 1.1))
        basis = (basis + " " if basis else "") + "+ 부가세 10%"
    return {"total": total, "basis": basis}


def authority_for(total: int) -> tuple[str, str]:
    for limit, who, tier in AUTHORITY_TIERS:
        if limit is None or total <= limit:
            return who, tier
    return AUTHORITY_TIERS[-1][1], AUTHORITY_TIERS[-1][2]


def _flags(text: str) -> set[str]:
    low = text.lower()
    return {name for name, words in FLAGS.items() if any(w in low for w in words)}


def _context(text: str) -> dict:
    amount = parse_contract_amount(text)
    flags = _flags(text)
    if amount:
        flags.add("contract")
    # 계약 신호가 약하면(도입·구축만) 핵심 항목만 보여준다.
    light = "contract" not in flags and "project" in flags
    if light:
        flags.add("contract")
    return {"amount": amount, "flags": flags, "light": light}


def _amount_desc(amount: dict) -> str:
    return format_won(amount["total"]) + (f" ({amount['basis']})" if amount["basis"] else "")


def approval_items(text: str, limit: int = 8) -> list[tuple[str, str, str]]:
    """(검토 분야, 점검 질문, 확인 필요사항) 목록. 중요한 항목부터 최대 limit개."""
    ctx = _context(text)
    flags, amount = ctx["flags"], ctx["amount"]
    if "contract" not in flags:
        return []
    if ctx["light"]:
        return [
            ("전결권자", "계약총액(부가세 포함) 기준 전결권자의 사전 승인을 받았는가?",
             f"계약총액(부가세 포함) 산정 후 확인: {TIER_GUIDE} · 전결기준표 4-가"),
            ("계약 방식", "계약총액 구간에 맞는 견적·경쟁 절차를 거쳤는가?",
             "5백만원 이하 1개 견적 / 3천만원 이하 2개 비교견적 / 초과 3개 이상 경쟁 · 준칙 제8조"),
            ("사전 검토", "중요 계약·신규 사업에 대해 총괄임원 사전 검토를 받았는가?",
             "사전 검토의견서(사업 승인과 구분) · 전결기준표 9-가"),
        ]
    total = amount["total"] if amount else None
    items = []

    if amount:
        who, tier = authority_for(total)
        check = f"계약총액 {_amount_desc(amount)} → 본사 {who} 전결({tier}) · 전결기준표 4-가"
    else:
        check = f"계약총액(부가세 포함) 산정 후 확인: {TIER_GUIDE} · 전결기준표 4-가"
    items.append(("전결권자", "계약총액(부가세 포함) 기준 전결권자의 사전 승인을 받았는가?", check))

    if "sole" in flags:
        approver = "본사 부서장" if total is not None and total <= 30_000_000 else \
            (f"총액별 본사 전결권자({authority_for(total)[0]})" if total else "3천만원 이하 본사 부서장, 초과 시 총액별 전결권자")
        items.append(("수의계약", "수의계약 사유서·대체업체 검토·가격 적정성 자료를 갖추어 승인받았는가?",
                      f"경쟁 곤란 사유, 승인권자 {approver} · 준칙 제9조"))
    elif total is None:
        items.append(("계약 방식", "계약총액 구간에 맞는 견적·경쟁 절차를 거쳤는가?",
                      "5백만원 이하 1개 견적 / 3천만원 이하 2개 비교견적 / 초과 3개 이상 경쟁 · 준칙 제8조"))
    elif total <= 5_000_000:
        items.append(("계약 방식", "1개 이상 견적과 시장가격 자료를 확인하였는가?", "견적서, 시장가격 자료 · 준칙 제8조 1호"))
    elif total <= 30_000_000:
        items.append(("비교견적", "2개 이상 업체의 비교견적을 받았는가?", "업체별 견적서, 조건 비교표 · 준칙 제8조 2호"))
    else:
        items.append(("경쟁 절차", "3개 이상 업체에 제안·견적을 요청하여 경쟁 절차를 진행하였는가?",
                      "제안요청서, 제출 업체 수, 평가표 · 준칙 제8조 3호"))

    if "recurring" in flags:
        items.append(("금액 합산", "반복·단가계약의 전체 계약기간 예상 지급액을 합산하였는가?",
                      (amount["basis"] if amount and amount["basis"] else "계약기간, 예상 수량·단가") + " · 준칙 제4조"))
    if total is not None and total > 30_000_000:
        items.append(("이행보증", "계약총액의 10%에 해당하는 이행보증을 확보하였는가?",
                      f"보증금액 {format_won(total // 10)}, 보증서 · 준칙 제11조①"))
    if "advance" in flags:
        items.append(("선급금", "선급금이 계약총액의 20% 이내이며 반환보증을 확보하였는가?",
                      "선급 비율, 선급금 보증서 · 20% 초과 시 대표이사(준칙 제11조②)"))
    if "major" in flags:
        items.append(("중대 조건", "지급보증·무제한 배상·핵심 지식재산 양도 등 중대 조건에 대표이사 승인을 받았는가?",
                      "계약 조건 검토서 · 금액과 무관 대표이사(금액산정 ④)"))
    if "related" in flags:
        items.append(("이해관계 거래", "특수관계자·이해관계자 거래에 대해 준법 검토와 대표이사 승인을 받았는가?",
                      "이해관계 확인서, 준법 검토의견 · 준칙 제9조③"))
    if "privacy" in flags:
        items.append(("위탁 검토", "개인정보 처리·지식재산·재위탁 조건에 대해 관련 담당자 검토를 받았는가?",
                      "위탁 범위, 개인정보 처리 조건, 검토의견 · 준칙 제7조②"))
    if "change" in flags:
        items.append(("계약 변경", "변경 후 누적총액 기준 전결권자 승인을 받았는가? (기존 승인자보다 낮은 직급 불가)",
                      "최초금액, 누적 증감액 · 준칙 제12조①"))
    if "budget_out" in flags:
        items.append(("예산 외 집행", "예산 초과·미편성 경비에 대해 대표이사 승인을 받았는가?", "예산 조정안 · 전결기준표 2-사"))
    if "invest" in flags:
        items.append(("투자계획", "연간 투자계획 신설·총액 증액에 대해 대표이사 승인을 받았는가?",
                      "효과·회수기간·운영비 검토 · 전결기준표 3-라"))
    if "competition" in flags or (total is not None and total > 30_000_000 and "sole" not in flags):
        items.append(("평가기준", "경쟁 절차의 평가항목·배점을 제출 요청 전에 본사 부서장이 확정하였는가?",
                      "평가기준표, 확정일 · 전결기준표 4-다"))
    if "new_biz" in flags:
        items.append(("사전 검토", "중요 계약·신규 사업에 대해 총괄임원 사전 검토를 받았는가?",
                      "사전 검토의견서(사업 승인과 구분) · 전결기준표 9-가"))
    if "data_out" in flags:
        items.append(("자료 반출", "중요자료 외부 제공·반출에 대해 총괄임원 승인을 받았는가?",
                      "제공 자료 목록, 개인정보·기밀 여부 · 전결기준표 6-라"))
    if "urgent" in flags:
        items.append(("사전 승인", "긴급 사유라도 발주 전에 전자결재 등으로 사전승인을 확보하였는가?",
                      "결재 일시, 발주 일시 · 사후결재 불가(금액산정 ⑤)"))
    split_item = ("분할 금지", "동일 목적의 거래를 나누어 전결한도를 낮추지 않았는가?",
                  "관련 발주 내역, 합산 총액 · 전결기준표 공통 ②")
    # 분할 발주가 드러난 질문이면 전결권자 바로 다음에 둔다.
    if amount and "분할분" in amount["basis"]:
        items.insert(1, split_item)
    else:
        items.append(split_item)
    items.append(("검수 분리", "계약담당자와 구분되는 검수담당자를 지정하였는가?", "검수담당자, 검수기준 · 준칙 제13조①"))
    items.append(("계약대장", "체결 후 3영업일 이내 계약대장에 등록하였는가?", "계약번호, 등록일 · 준칙 제15조①"))
    return items[:limit]


def approval_brief(text: str) -> str:
    """답변에 붙일 전결 판단 한 줄. 계약 관련 질문이 아니면 빈 문자열."""
    ctx = _context(text)
    flags, amount = ctx["flags"], ctx["amount"]
    if "contract" not in flags:
        return ""
    if not amount:
        return "💼 **전결** 계약총액 확인 후 전결권자 결정 (금액 구간은 체크리스트 참고)"

    total = amount["total"]
    who, _ = authority_for(total)
    if "sole" in flags:
        method = "수의계약 사유서 필요"
    elif total <= 5_000_000:
        method = "1개 이상 견적"
    elif total <= 30_000_000:
        method = "2개 이상 비교견적"
    else:
        method = "3개 이상 업체 경쟁"
    basis = f" = {amount['basis']}" if amount["basis"] else ""
    parts = [f"본사 **{who}**", f"계약총액 {format_won(total)}{basis}", method]
    if total > 30_000_000:
        parts.append(f"이행보증 {format_won(total // 10)}")
    return "💼 **전결** " + " · ".join(parts)


def approval_summary(text: str) -> str:
    """답변에 붙일 전결 판단 요약. 계약 관련 질문이 아니면 빈 문자열."""
    ctx = _context(text)
    flags, amount = ctx["flags"], ctx["amount"]
    if "contract" not in flags:
        return ""
    lines = ["**💼 전결 기준 검토** (전결기준표·계약업무준칙)"]
    if not amount:
        lines.append(f"- 계약총액이 제시되지 않았어요. 금액 구간별 본사 전결권자: {TIER_GUIDE}")
        return "\n".join(lines)

    total = amount["total"]
    who, tier = authority_for(total)
    lines.append(f"- 계약총액: {_amount_desc(amount)}")
    lines.append(f"- 전결권자: 본사 **{who}** ({tier})")
    if "sole" in flags:
        approver = "본사 부서장" if total <= 30_000_000 else f"본사 {who}"
        lines.append(f"- 수의계약: 객관적 사유서·대체업체 검토 첨부 후 {approver} 승인 (준칙 제9조)")
    elif total <= 5_000_000:
        lines.append("- 계약 방식: 1개 이상 견적 + 시장가격 확인 (준칙 제8조)")
    elif total <= 30_000_000:
        lines.append("- 계약 방식: 2개 이상 업체 비교견적 (준칙 제8조)")
    else:
        lines.append("- 계약 방식: 3개 이상 업체 경쟁 절차 (준칙 제8조)")
    if total > 30_000_000:
        lines.append(f"- 이행보증: 계약총액의 10%인 {format_won(total // 10)} 확보 (준칙 제11조)")
    if total <= 3_000_000:
        lines.append("- 사업본부·지사 발주라면 3백만원 이하로 자체장 전결 가능")
    return "\n".join(lines)
