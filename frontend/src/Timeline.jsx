import React, { useState } from "react";

// 프로젝트 단계별 예상 일정 간트 차트.
// 서버(/timeline)가 프로파일의 시작·종료일과 응답으로 나눈 단계 일정을 그린다.
// - 막대 색은 단계 고유색(App.css --phase-0~4, 검증된 범주형 팔레트 1~5번 순서 고정)
// - 단계명·기간·일수를 행마다 글자로 함께 적어 색만으로 구분하지 않게 한다(표 역할도 겸함)
// - 막대에 마우스를 올리면 비중·체크리스트 건수·산출물·산정 근거를 툴팁으로 보여준다

const PHASES = ["기획", "설계", "개발", "테스트", "오픈"];
const DAY = 24 * 60 * 60 * 1000;
const toDate = (s) => new Date(`${s}T00:00:00`);
const fmt = (s) => s.slice(5).replace("-", ".");

// 눈금: 14주 이하면 주, 18개월 이하면 월, 더 길면 분기 (워드 간트 표와 같은 규칙)
function ticks(start, end, totalDays) {
  const s = toDate(start), e = toDate(end);
  const pos = (d) => ((d - s) / DAY) / totalDays * 100;
  if (totalDays <= 98) {
    const out = [];
    for (let i = 0, d = new Date(s); d <= e; i++, d = new Date(d.getTime() + 7 * DAY)) {
      out.push({ label: `${i + 1}주`, left: pos(d) });
    }
    return out;
  }
  const months = [];
  for (let d = new Date(s.getFullYear(), s.getMonth(), 1); d <= e; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
    months.push({ date: d < s ? s : d, y: d.getFullYear() % 100, m: d.getMonth() + 1 });
  }
  if (months.length <= 18) {
    return months.map(({ date, y, m }) => ({ label: `${y}.${String(m).padStart(2, "0")}`, left: pos(date) }));
  }
  return months.filter((mm, i) => i === 0 || (mm.m - 1) % 3 === 0)
    .map(({ date, y, m }) => ({ label: `${y} Q${Math.floor((m - 1) / 3) + 1}`, left: pos(date) }));
}

export default function Timeline({ timeline, categories = [], compact = false }) {
  const [hover, setHover] = useState(null); // { phase, x, y }
  if (!timeline) return null;
  const { start, end, total_days: total, phases, notes } = timeline;
  const s = toDate(start);
  const left = (d) => ((toDate(d) - s) / DAY) / total * 100;
  const width = (p) => p.days / total * 100;

  // 단계별 체크리스트 건수·작성 서식 (체크리스트에 담긴 항목 기준)
  const stats = Object.fromEntries(PHASES.map(ph => [ph, { items: 0, forms: new Set() }]));
  for (const cat of categories) {
    for (const item of cat.items) {
      if (stats[item.phase]) stats[item.phase].items++;
      for (const d of item.deliverables || []) stats[d.phase]?.forms.add(d.code);
    }
  }

  const now = new Date(); // 로컬(한국) 날짜 기준 — toISOString은 UTC라 오전 9시 전엔 하루 밀린다
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const showToday = todayStr >= start && todayStr <= end;
  const hovered = hover && phases.find(p => p.phase === hover.phase);

  return (
    <div className={`timeline ${compact ? "compact" : ""}`}>
      <div className="tl-grid">
        <div className="tl-head-label" />
        <div className="tl-axis">
          {ticks(start, end, total).map(t => (
            <span key={t.label} className="tl-tick" style={{ left: `${t.left}%` }}>{t.label}</span>
          ))}
        </div>

        {phases.map((p, i) => (
          <React.Fragment key={p.phase}>
            <div className="tl-label">
              <span className="tl-phase">{p.phase}</span>
              <span className="tl-dates">{fmt(p.start)}~{fmt(p.end)} · {p.days}일</span>
            </div>
            <div className="tl-track">
              {ticks(start, end, total).map(t => (
                <span key={t.label} className="tl-gridline" style={{ left: `${t.left}%` }} />
              ))}
              {showToday && <span className="tl-today" style={{ left: `${left(todayStr)}%` }} />}
              <span
                className="tl-bar"
                style={{ left: `${left(p.start)}%`, width: `${width(p)}%`, background: `var(--phase-${i})` }}
                onMouseMove={e => setHover({ phase: p.phase, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setHover(null)}
                aria-label={`${p.phase} ${p.start}~${p.end} ${p.days}일`}
              />
            </div>
          </React.Fragment>
        ))}
      </div>

      <div className="tl-foot">
        <span>총 {total}일 ({start} ~ {end})</span>
        {showToday && <span className="tl-today-key"><span className="tl-today-swatch" />오늘</span>}
      </div>

      {!compact && notes.length > 0 && (
        <div className="tl-notes">
          <b>산정 근거</b> 기본 비중(기획 15 · 설계 20 · 개발 40 · 테스트 18 · 오픈 7%)에서 프로파일에 따라 조정
          <ul>{notes.map(n => <li key={n}>{n}</li>)}</ul>
        </div>
      )}

      {hovered && (
        <div className="tl-tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <div className="tl-tt-title">{hovered.phase} · {hovered.days}일 ({hovered.share}%)</div>
          <div>{hovered.start} ~ {hovered.end}</div>
          {categories.length > 0 && (
            <div>체크리스트 {stats[hovered.phase].items}건
              {stats[hovered.phase].forms.size > 0 && ` · 서식 ${[...stats[hovered.phase].forms].join(", ")}`}
            </div>
          )}
          {hovered.reasons.length > 0 && <ul>{hovered.reasons.map(r => <li key={r}>{r}</li>)}</ul>}
        </div>
      )}
    </div>
  );
}
