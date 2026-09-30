"""담당자 자동 지정에 쓰는 더미 인사파일(data/employees.csv)을 만든다.

시드를 고정해 두었으므로 몇 번을 다시 돌려도 같은 파일이 나온다.
실행: python scripts/generate_employees.py  (backend 폴더에서)
"""
import csv
import random
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "employees.csv"

# 부서 → 팀 → 팀 업무명 목록. 업무명에 들어간 단어가 곧 담당자 매칭 근거가 된다.
ORG = {
    "IT기획부": {
        "IT전략팀": ["IT 중장기 전략 수립", "IT 성과관리(KPI)", "IT 투자 심의"],
        "IT거버넌스팀": ["IT 변경관리 시스템 운영", "IT 프로젝트 관리(PMO)", "IT 내부통제 점검"],
    },
    "디지털플랫폼부": {
        "API플랫폼팀": ["API Gateway 운영", "오픈API 개발", "API 트래픽 제어(Rate Limiting)"],
        "모바일개발팀": ["모바일뱅킹 앱 개발", "모바일 생체인증 연동", "모바일 앱 배포 관리"],
        "인증서비스팀": ["통합인증(SSO) 개발", "토큰·세션 관리", "MFA 인증 운영", "인증서(공동·민간) 연동"],
    },
    "IT인프라부": {
        "클라우드팀": ["클라우드 인프라 운영", "쿠버네티스 플랫폼 운영", "CI/CD 파이프라인 운영"],
        "시스템운영팀": ["계정계 시스템 운영", "레거시 연동(EAI) 운영", "장애 대응·Circuit Breaker 설계"],
        "데이터베이스팀": ["DB 운영", "데이터 정합성 검증", "데이터 이관"],
        "네트워크팀": ["네트워크 운영", "TLS 인증서 관리", "방화벽 정책 관리"],
    },
    "정보보호부": {
        "보안정책팀": ["정보보호 정책 수립", "접근통제 정책 관리", "보안성 심의"],
        "보안관제팀": ["보안관제 운영", "접근 로그 관리·보관", "침해사고 대응"],
        "보안기술팀": ["암호화·키관리(HSM)", "취약점 점검", "모의해킹"],
        "개인정보보호팀": ["개인정보 안전조치 점검", "개인정보 영향평가", "개인정보 암호화 기준 관리"],
    },
    "준법감시부": {
        "IT준법팀": ["전자금융감독규정 준수 검토", "IT 준법감시 사전 승인", "금융규제 대응"],
        "법무지원팀": ["IT 법령 해석 지원", "전자서명법 검토", "IT 계약 검토"],
    },
    # 전결기준표·계약업무준칙의 계약담당·재무담당 역할
    "경영지원부": {
        "계약관리팀": ["계약 체결·계약대장 관리", "견적·예정가격 산정", "수의계약·입찰 평가 관리"],
        "재무팀": ["예산 편성·조정", "대금 지급·선급금 관리", "투자계획·자산대장 관리"],
    },
}

# 팀원 수: 업무 4개 팀 6명, 소규모 팀 4명, 나머지 5명
# → 부장 6 + 팀장 17 + 팀원 77 = 100명
LARGE_TEAMS = {"인증서비스팀"}
SMALL_TEAMS = {"IT전략팀", "IT거버넌스팀", "모바일개발팀", "클라우드팀", "데이터베이스팀",
               "네트워크팀", "보안정책팀", "법무지원팀", "재무팀"}
MEMBER_TITLES = {4: ["차장", "과장", "대리", "주임"],
                 5: ["차장", "과장", "과장", "대리", "주임"],
                 6: ["차장", "과장", "과장", "대리", "대리", "주임"]}
HIRE_YEARS = {"부장": (1995, 2000), "팀장": (2000, 2006), "차장": (2004, 2010),
              "과장": (2010, 2015), "대리": (2015, 2019), "주임": (2019, 2024)}

SURNAMES = list("김이박최정강조윤장임한오서신권황안송류홍")
GIVEN = ["민준", "서연", "도윤", "지우", "하준", "서윤", "시우", "하은", "주원", "지민",
         "예준", "수아", "지호", "지유", "준우", "채원", "현우", "다은", "건우", "은서",
         "우진", "예린", "선우", "수빈", "연우", "지안", "유준", "소윤", "정우", "예은",
         "승현", "가은", "준혁", "민서", "지훈", "윤서", "성민", "혜원", "재원", "나연"]


def main():
    rng = random.Random(20260930)
    used_names = set()
    seq = 0

    def person(dept, team, title, duty):
        nonlocal seq
        seq += 1
        while True:
            name = rng.choice(SURNAMES) + rng.choice(GIVEN)
            if name not in used_names:
                used_names.add(name)
                break
        year = rng.randint(*HIRE_YEARS[title])
        return [f"{year}{seq:04d}", name, dept, team, title, duty]

    rows = []
    for dept, teams in ORG.items():
        rows.append(person(dept, "", "부장", f"{dept} 총괄"))
        for team, duties in teams.items():
            rows.append(person(dept, team, "팀장", f"{team} 총괄"))
            size = 6 if team in LARGE_TEAMS else 4 if team in SMALL_TEAMS else 5
            for i, title in enumerate(MEMBER_TITLES[size]):
                rows.append(person(dept, team, title, duties[i % len(duties)]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 엑셀에서 한글이 깨지지 않도록 BOM 포함 UTF-8로 저장
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["사번", "성명", "부서", "팀명", "직명", "업무명"])
        writer.writerows(rows)
    print(f"{len(rows)}명 → {OUT_PATH}")


if __name__ == "__main__":
    main()
