"""프로파일의 프로젝트 시작·종료일로 단계별(기획·설계·개발·테스트·오픈) 예상 기간을 나눈다.

기본 비중(BASE_WEIGHTS)에서 시작해, 프로파일 응답이 특정 단계의 일을 늘리거나 줄이면
비중을 더하거나 뺀다(ADJUSTMENTS). 조정마다 사유를 남겨 화면·문서에 '산정 근거'로 보여준다.
기간은 달력일 기준이며 단계는 겹치지 않고 이어진다(기획 → 설계 → 개발 → 테스트 → 오픈).
"""
from datetime import date, timedelta

PHASES = ["기획", "설계", "개발", "테스트", "오픈"]
BASE_WEIGHTS = {"기획": 15, "설계": 20, "개발": 40, "테스트": 18, "오픈": 7}
MIN_DAYS = 5  # 이보다 짧은 기간은 단계를 나눌 수 없다


def _has(profile: dict, item_id: str, *needles: str) -> bool:
    """프로파일 항목 값에 needles 중 하나가 들어 있는지."""
    for it in profile.get("items", []):
        if it.get("id") == item_id:
            return any(n in it.get("value", "") for n in needles)
    return False


def _only(profile: dict, item_id: str, value: str) -> bool:
    for it in profile.get("items", []):
        if it.get("id") == item_id:
            return [v.strip() for v in it.get("value", "").split(",")] == [value]
    return False


# (조건, {단계: 비중 증감}, 사유)
ADJUSTMENTS = [
    (lambda p: _has(p, "vendor", "개발·구축"), {"기획": 3},
     "외부 업체 개발 — 업체 선정·계약 절차로 기획 기간 확대"),
    (lambda p: _only(p, "vendor", "외부 업체가 유지보수·운영"), {"기획": 5, "개발": -15},
     "유지보수 계약 중심 — 개발 비중 축소"),
    (lambda p: _has(p, "hosting", "SaaS"), {"설계": 2, "개발": -12},
     "SaaS 이용 — 자체 개발 축소, 연동·설정 설계 비중 확대"),
    (lambda p: _has(p, "hosting", "클라우드"), {"설계": 2},
     "클라우드 이용 — 이용 중요도 평가·보고 절차"),
    (lambda p: _has(p, "overseas", "있음"), {"기획": 3},
     "해외 이전 — 국외 이전 검토·고지·동의 절차"),
    (lambda p: _has(p, "outsourcing", "있음"), {"기획": 2},
     "개인정보 처리 위탁 — 위탁 계약·검토"),
    (lambda p: _has(p, "personal", "처리함"), {"설계": 3},
     "개인정보 처리 — 영향평가·암호화 설계"),
    (lambda p: _has(p, "sensitive", "고유식별", "민감"), {"설계": 2},
     "민감·고유식별정보 — 별도 보호조치 설계"),
    (lambda p: _has(p, "network", "인터넷"), {"테스트": 4},
     "인터넷 노출 — 취약점 점검·모의해킹"),
    (lambda p: _has(p, "external_api", "연동함"), {"설계": 1, "테스트": 3},
     "외부 API 연동 — 인터페이스 설계·연동 테스트"),
    (lambda p: _has(p, "impact", "금융거래 중단"), {"테스트": 4, "오픈": 3},
     "장애 시 금융거래 중단 — 성능·장애복구 테스트, 오픈 안정화"),
    (lambda p: _has(p, "genai", "사용("), {"테스트": 3},
     "생성형 AI — 응답 품질·안전성 검증"),
    (lambda p: _has(p, "scale", "100만"), {"테스트": 2},
     "이용자 100만 명 이상 — 부하 테스트"),
]


def _parse(d: str) -> date | None:
    try:
        return date.fromisoformat(d)
    except (TypeError, ValueError):
        return None


def _allocate(total: int, weights: dict[str, float]) -> dict[str, int]:
    """total일을 비중대로 나눈다(최대 잔여법). 단계마다 최소 1일."""
    wsum = sum(weights.values())
    raw = {ph: total * w / wsum for ph, w in weights.items()}
    days = {ph: max(1, int(r)) for ph, r in raw.items()}
    # 내림으로 남은 날은 소수점이 큰 단계부터 하루씩 더한다.
    by_fraction = sorted(PHASES, key=lambda ph: raw[ph] - int(raw[ph]), reverse=True)
    for i in range(total - sum(days.values())):
        days[by_fraction[i % len(PHASES)]] += 1
    # 최소 1일 보정으로 넘친 날은 가장 긴 단계에서 뺀다.
    while sum(days.values()) > total:
        days[max(PHASES, key=lambda ph: days[ph])] -= 1
    return days


def build_timeline(profile: dict | None) -> dict | None:
    """프로파일의 start_date·end_date로 단계별 일정을 만든다. 날짜가 없거나 잘못되면 None."""
    if not profile:
        return None
    start, end = _parse(profile.get("start_date")), _parse(profile.get("end_date"))
    if not start or not end or (end - start).days + 1 < MIN_DAYS:
        return None
    total = (end - start).days + 1

    weights = dict(BASE_WEIGHTS)
    reasons = {ph: [] for ph in PHASES}
    notes = []
    for cond, delta, why in ADJUSTMENTS:
        if cond(profile):
            for ph, d in delta.items():
                weights[ph] = max(2, weights[ph] + d)  # 어떤 단계도 사라지지 않게 최소 비중 유지
                reasons[ph].append(why)
            notes.append(why)

    days = _allocate(total, weights)
    phases, cursor = [], start
    for ph in PHASES:
        ph_end = cursor + timedelta(days=days[ph] - 1)
        phases.append({
            "phase": ph, "start": cursor.isoformat(), "end": ph_end.isoformat(),
            "days": days[ph], "share": round(days[ph] * 100 / total),
            "reasons": reasons[ph],
        })
        cursor = ph_end + timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "total_days": total,
            "phases": phases, "notes": notes}
