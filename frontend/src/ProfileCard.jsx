import React, { useMemo, useState } from "react";
import Timeline from "./Timeline.jsx";

// 첫 프로젝트 질문 뒤에 뜨는 프로파일링 카드.
// 프로젝트명을 받고, 질문에서 추론한 항목은 근거와 함께 보여주기만 하며,
// 추론하지 못한 항목만 보기 버튼으로 묻는다. depends_on이 걸린 질문은
// 앞 답변(또는 추론 값)이 not_in 값이면 숨긴다.

const UNANSWERED = "미확인";

// 영역 표시 순서. 서버(AI)가 새 영역을 추가하면 뒤에 붙는다.
const AREA_ORDER = ["데이터", "인프라", "계약", "서비스", "기술", "예산"];
const areaRank = (a) => (AREA_ORDER.indexOf(a) === -1 ? 99 : AREA_ORDER.indexOf(a));

function groupByArea(list) {
  const map = new Map();
  for (const it of list) {
    if (!map.has(it.area)) map.set(it.area, []);
    map.get(it.area).push(it);
  }
  return [...map.entries()].sort((a, b) => areaRank(a[0]) - areaRank(b[0]));
}

// 의존 항목의 현재 값: 사용자가 고른 답 → 없으면 추론 값
function currentValues(id, answers, inferred) {
  const ans = answers[id];
  if (Array.isArray(ans)) return ans;
  if (ans) return [ans];
  const inf = inferred.find(i => i.id === id);
  return inf ? inf.value.split(",").map(v => v.trim()) : [];
}

function isVisible(q, answers, inferred) {
  const dep = q.depends_on;
  if (!dep) return true;
  const values = currentValues(dep.id, answers, inferred);
  // 아직 답하지 않은 의존 항목이면 일단 보여준다.
  return values.length === 0 || values.some(v => !dep.not_in.includes(v));
}

export function buildProfile(name, dates, request, answers) {
  const inferred = request.inferred || [];
  const visible = (request.questions || []).filter(q => isVisible(q, answers, inferred));
  return {
    project_name: name.trim(),
    start_date: dates.start,
    end_date: dates.end,
    items: [
      ...inferred.map(i => ({ id: i.id, area: i.area, label: i.label, value: i.value, source: "inferred", reason: i.reason || "" })),
      ...visible.map(q => {
        const a = answers[q.id];
        const value = Array.isArray(a) ? a.join(", ") : a;
        return { id: q.id, area: q.area, label: q.label, value: value || UNANSWERED, source: "answered", reason: "" };
      }),
    ].sort((a, b) => areaRank(a.area) - areaRank(b.area)),
  };
}

// 단계를 나누려면 최소 5일이 필요하다(서버 timeline.MIN_DAYS와 같음).
const MIN_DAYS = 5;
const daysBetween = (a, b) => Math.round((new Date(`${b}T00:00:00`) - new Date(`${a}T00:00:00`)) / 86400000) + 1;

function dateError(start, end) {
  if (!start || !end) return "";
  const days = daysBetween(start, end);
  if (days < 1) return "종료일이 시작일보다 빨라요";
  if (days < MIN_DAYS) return `단계를 나누려면 기간이 ${MIN_DAYS}일 이상이어야 해요`;
  return "";
}

export default function ProfileCard({ msg, timeline, onSubmit }) {
  const { request, submitted } = msg;
  const inferred = request.inferred || [];
  const [name, setName] = useState("");
  const [dates, setDates] = useState({ start: "", end: "" });
  const [answers, setAnswers] = useState({});
  const dError = dateError(dates.start, dates.end);
  const canSubmit = name.trim() && dates.start && dates.end && !dError;
  const submit = () => canSubmit && onSubmit(buildProfile(name, dates, request, answers));

  const visibleQuestions = useMemo(
    () => (request.questions || []).filter(q => isVisible(q, answers, inferred)),
    [request.questions, answers, inferred]
  );
  const unanswered = visibleQuestions.filter(q => !answers[q.id] || answers[q.id].length === 0).length;

  const pick = (q, option) => {
    setAnswers(prev => {
      if (!q.multi) return { ...prev, [q.id]: prev[q.id] === option ? undefined : option };
      const cur = prev[q.id] || [];
      return { ...prev, [q.id]: cur.includes(option) ? cur.filter(o => o !== option) : [...cur, option] };
    });
  };

  // 제출 후에는 수집된 프로파일을 읽기 전용 요약으로 보여준다.
  if (submitted) {
    return (
      <div className="msg-row msg-agent">
        <div className="profile-card done">
          <div className="profile-head">
            <span className="profile-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 12l5 5L19 7" />
              </svg>
            </span>
            <span><b>{submitted.project_name}</b> 프로젝트 기본 정보</span>
          </div>
          {submitted.start_date && (
            <div className="profile-summary-row">
              <span className="profile-area-tag">일정</span>
              <span className="profile-summary-item">
                {submitted.start_date} ~ {submitted.end_date} ({daysBetween(submitted.start_date, submitted.end_date)}일)
              </span>
            </div>
          )}
          {groupByArea(submitted.items).map(([area, items]) => (
            <div key={area} className="profile-summary-row">
              <span className="profile-area-tag">{area}</span>
              <span>
                {items.map(i => (
                  <span key={i.id || i.label} className={`profile-summary-item ${i.value === UNANSWERED ? "unknown" : ""}`}>
                    {i.label}: {i.value}
                  </span>
                ))}
              </span>
            </div>
          ))}
          {timeline && (
            <div className="profile-block">
              <div className="profile-block-title">단계별 예상 일정</div>
              <Timeline timeline={timeline} compact />
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="msg-row msg-agent">
      <div className="profile-card">
        <div className="profile-head">
          <span className="profile-icon">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" aria-hidden="true">
              <path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />
            </svg>
          </span>
          <span>
            검토를 시작하기 전에 프로젝트 기본 정보를 확인할게요.
            <span className="profile-head-sub">질문에서 파악한 내용은 묻지 않았어요.</span>
          </span>
        </div>

        <label className="profile-name">
          <span className="profile-label">프로젝트명 <em>*</em></span>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="예: AI 상담 챗봇 도입"
            onKeyDown={e => e.key === "Enter" && submit()}
            autoFocus
          />
        </label>
        {request.suggested_name && name.trim() !== request.suggested_name && (
          <button className="profile-suggest" onClick={() => setName(request.suggested_name)}>
            추천: {request.suggested_name}
          </button>
        )}

        {/* 시작·종료일로 단계별(기획~오픈) 예상 일정을 산출해 타임라인을 그린다 */}
        <div className="profile-dates">
          <label>
            <span className="profile-label">시작일 <em>*</em></span>
            <input type="date" value={dates.start} max={dates.end || undefined}
                   onChange={e => setDates(d => ({ ...d, start: e.target.value }))} />
          </label>
          <span className="profile-dates-sep">~</span>
          <label>
            <span className="profile-label">종료(오픈)일 <em>*</em></span>
            <input type="date" value={dates.end} min={dates.start || undefined}
                   onChange={e => setDates(d => ({ ...d, end: e.target.value }))} />
          </label>
          <span className={`profile-dates-info ${dError ? "error" : ""}`}>
            {dError || (dates.start && dates.end ? `총 ${daysBetween(dates.start, dates.end)}일` : "")}
          </span>
        </div>

        {inferred.length > 0 && (
          <div className="profile-block">
            <div className="profile-block-title">질문에서 파악한 내용</div>
            {groupByArea(inferred).map(([area, items]) => (
              <div key={area} className="profile-inferred-row">
                <span className="profile-area-tag">{area}</span>
                <span className="profile-inferred-items">
                  {items.map(i => (
                    <span key={i.id} className="profile-inferred" title={i.reason}>
                      {i.label}: <b>{i.value}</b>
                    </span>
                  ))}
                </span>
              </div>
            ))}
          </div>
        )}

        {visibleQuestions.length > 0 && (
          <div className="profile-block">
            <div className="profile-block-title">추가로 확인할 내용 <span className="profile-hint">(모르면 비워두세요 · 미확인으로 기록)</span></div>
            {groupByArea(visibleQuestions).map(([area, qs]) => (
              <div key={area} className="profile-area">
                <span className="profile-area-tag">{area}</span>
                {qs.map(q => (
                  <div key={q.id} className="profile-q">
                    <div className="profile-q-text">{q.question}{q.multi && <span className="profile-hint"> (복수 선택)</span>}</div>
                    <div className="profile-options">
                      {q.options.map(o => {
                        const on = q.multi ? (answers[q.id] || []).includes(o) : answers[q.id] === o;
                        return (
                          <button key={o} className={`profile-opt ${on ? "on" : ""}`} onClick={() => pick(q, o)}>{o}</button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        <div className="profile-foot">
          {unanswered > 0 && <span className="profile-hint">미응답 {unanswered}개는 '미확인'으로 기록돼요</span>}
          <button
            className="issue-add-btn"
            disabled={!canSubmit}
            title={canSubmit ? undefined : "프로젝트명과 시작·종료일을 입력해 주세요"}
            onClick={submit}
          >
            검토 시작
          </button>
        </div>
      </div>
    </div>
  );
}
