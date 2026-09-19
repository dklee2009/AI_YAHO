import React, { useState, useRef, useEffect, useCallback } from "react";
import "./App.css";

const API_URL = "http://localhost:8001";

const MODELS = [
  { id: "claude-sonnet-5", label: "Claude Sonnet 5" },
  { id: "claude-opus-5",   label: "Claude Opus 5" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
];

// 체크리스트 카테고리 색상 테마. 지금은 두 개뿐이지만 새 category_id가 오면
// CATEGORY_THEME_FALLBACK으로 처리되므로 카테고리는 앞으로 계속 늘어날 수 있다.
const CATEGORY_THEME = {
  security: { accent: "#B91C1C", dot: "#EF4444" },
  it:       { accent: "#1D4ED8", dot: "#3B82F6" },
};
const CATEGORY_THEME_FALLBACK = { accent: "#475569", dot: "#94A3B8" };

// 체크리스트 시작 카테고리 (보안 / IT). 백엔드 CATEGORY_LABELS와 id·제목을 맞춤.
const SEED_CATEGORIES = [
  { id: "security", title: "보안 (개인정보보호·정보보안 법/규정)", items: [] },
  { id: "it",       title: "IT (서비스 구현 체크리스트)",          items: [] },
];
const CATEGORY_LABEL_BY_ID = Object.fromEntries(SEED_CATEGORIES.map(c => [c.id, c.title]));

function formatText(text) {
  const parts = text.split(/(```[\s\S]*?```)/g);
  return parts.map((part, i) => {
    if (part.startsWith("```")) {
      const lines = part.slice(3).split("\n");
      const code = lines.slice(1).join("\n").replace(/```$/, "").trimEnd();
      return <pre key={i} className="code-block"><code>{code}</code></pre>;
    }
    const inlineParts = part.split(/(`[^`]+`)/g);
    return (
      <span key={i}>
        {inlineParts.map((s, j) =>
          s.startsWith("`") && s.endsWith("`")
            ? <code key={j} className="inline-code">{s.slice(1, -1)}</code>
            : s.split(/(\*\*[^*]+\*\*)/g).map((t, k) =>
                t.startsWith("**") && t.endsWith("**")
                  ? <strong key={k}>{t.slice(2, -2)}</strong>
                  : <span key={k} style={{ whiteSpace: "pre-wrap" }}>{t}</span>
              )
        )}
      </span>
    );
  });
}

function AnswerMessage({ msg }) {
  return (
    <div className="msg-row msg-agent">
      <div className="agent-avatar">🤖</div>
      <div className="agent-bubble">
        <div className="agent-content">
          {msg.streaming && msg.content === ""
            ? (msg.phase === "law"
                ? <span className="law-loading">📚 관련 법령 확인 중…</span>
                : <span className="typing-dots"><span /><span /><span /></span>)
            : <>
                {formatText(msg.content)}
                {msg.streaming && <span className="cursor">▍</span>}
              </>
          }
        </div>
      </div>
    </div>
  );
}

function ClarifyNotice({ text }) {
  return (
    <div className="msg-row msg-agent">
      <div className="clarify-notice">
        <span className="clarify-icon">🤔</span>
        <span>{text}</span>
      </div>
    </div>
  );
}

function IssueSuggestion({ group, added, onAdd }) {
  const theme = CATEGORY_THEME[group.category_id] || CATEGORY_THEME_FALLBACK;
  const shortLabel = group.category_label.split(" (")[0];
  const hasItems = group.items.length > 0;
  // 기본은 전부 선택된 상태로 시작 - 필요 없는 항목만 체크 해제하면 됨
  const [checked, setChecked] = useState(() => new Set(group.items.map(it => it.id)));

  const toggle = (id) => {
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleDone = () => {
    onAdd(group.items.filter(it => checked.has(it.id)));
  };

  return (
    <div className="msg-row msg-agent">
      <div className="issue-suggestion">
        <div className="issue-suggestion-head">
          <span>🔍</span>
          {hasItems ? (
            <span>
              <b style={{ color: theme.accent }}>{shortLabel}</b> 관점에서 검토가 필요해 보이는 이슈를 찾았어요. 체크리스트에 추가할 항목을 선택하고 완료를 눌러주세요.
            </span>
          ) : (
            <span>
              <b style={{ color: theme.accent }}>{shortLabel}</b> 관점에서는 특별히 검토할 이슈를 찾지 못했어요.
            </span>
          )}
        </div>
        {hasItems && (
          <ul className="issue-checklist">
            {group.items.map(it => (
              <li key={it.id}>
                <label className={`issue-check-item ${added ? "readonly" : ""}`}>
                  <input
                    type="checkbox"
                    checked={checked.has(it.id)}
                    onChange={() => toggle(it.id)}
                    disabled={added}
                    style={{ accentColor: theme.accent }}
                  />
                  <span>{it.text}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
        <button className="issue-add-btn" onClick={handleDone} disabled={added}>
          {added ? "✔ 확인됨" : hasItems ? "완료" : "확인"}
        </button>
      </div>
    </div>
  );
}

// checked_categories를 보안 → IT 순으로 정렬해 슬롯을 만들고, 실제로 이슈가
// 있는 카테고리는 항목을 채우고 없는 카테고리는 빈 슬롯(= "이슈 없음" 카드)으로 둔다.
// 한 번에 다 보여주지 않고 카테고리별로 순차적으로 물어보기 위한 큐를 만든다.
const ISSUE_CATEGORY_ORDER = ["it", "security"];
function groupIssuesByCategory(items, checkedCategories) {
  const byCategory = new Map();
  for (const it of items) {
    if (!byCategory.has(it.category_id)) {
      byCategory.set(it.category_id, { category_id: it.category_id, category_label: it.category_label, items: [] });
    }
    byCategory.get(it.category_id).items.push(it);
  }
  // checked_categories에 있는데 이슈가 없던 카테고리도 빈 슬롯으로 추가
  for (const catId of checkedCategories || []) {
    if (!byCategory.has(catId)) {
      byCategory.set(catId, { category_id: catId, category_label: CATEGORY_LABEL_BY_ID[catId] || catId, items: [] });
    }
  }
  const groups = [...byCategory.values()];
  groups.sort((a, b) => {
    const ai = ISSUE_CATEGORY_ORDER.indexOf(a.category_id);
    const bi = ISSUE_CATEGORY_ORDER.indexOf(b.category_id);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
  return groups;
}

function ChatMessage({ msg, onAddIssues }) {
  if (msg.type === "user") {
    return (
      <div className="msg-row msg-user">
        <div className="bubble bubble-user">{msg.content}</div>
      </div>
    );
  }
  if (msg.type === "answer")   return <AnswerMessage msg={msg} />;
  if (msg.type === "clarify")  return <ClarifyNotice text={msg.content} />;
  if (msg.type === "issues")   return <IssueSuggestion group={msg.group} added={msg.added} onAdd={onAddIssues} />;
  return null;
}

function buildHistory(messages) {
  const history = [];
  for (const msg of messages) {
    if (msg.type === "user") {
      history.push({ role: "user", content: msg.content });
    } else if (msg.type === "answer" && !msg.streaming && msg.content) {
      history.push({ role: "assistant", content: msg.content });
    }
  }
  return history;
}

function DocumentPreview({ categories }) {
  const visible = categories.filter(c => c.items.length > 0);
  return (
    <div className="doc-preview">
      <div className="doc-page">
        <h2 className="doc-title">IT 프로젝트 검토 체크리스트</h2>
        {visible.length === 0 && (
          <p className="doc-empty">아직 체크리스트에 추가된 항목이 없어요.<br />채팅에서 이슈를 제안받으면 여기에 문서로 쌓여요.</p>
        )}
        {visible.map(cat => (
          <div key={cat.id} className="doc-section">
            <h3>{cat.title}</h3>
            <ul>
              {cat.items.map(item => (
                <li key={item.id} className={item.done ? "doc-item-done" : ""}>
                  <span className="doc-check">{item.done ? "☑" : "☐"}</span> {item.text}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function SidePanel({ categories, onToggle, onAddManual, onDelete, onClose }) {
  const [tab, setTab] = useState("checklist"); // "checklist" | "preview"
  const [newTexts, setNewTexts] = useState({});
  const [downloading, setDownloading] = useState(false);

  const total = categories.reduce((a, c) => a + c.items.length, 0);
  const done  = categories.reduce((a, c) => a + c.items.filter(i => i.done).length, 0);
  const pct   = total ? Math.round((done / total) * 100) : 0;

  const handleAdd = (catId) => {
    const text = (newTexts[catId] || "").trim();
    if (!text) return;
    onAddManual(catId, text);
    setNewTexts(prev => ({ ...prev, [catId]: "" }));
  };

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const res = await fetch(`${API_URL}/export-checklist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          categories: categories.map(c => ({
            id: c.id, title: c.title,
            items: c.items.map(i => ({ id: i.id, text: i.text, done: i.done })),
          })),
        }),
      });
      if (!res.ok) throw new Error("서버 응답 오류");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "checklist.docx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`다운로드에 실패했어요: ${err.message}`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <aside className={`checklist-panel ${tab === "preview" ? "wide" : ""}`}>
      <div className="cl-header">
        <div className="cl-tabs">
          <button className={`cl-tab ${tab === "checklist" ? "active" : ""}`} onClick={() => setTab("checklist")}>
            체크리스트
          </button>
          <button className={`cl-tab ${tab === "preview" ? "active" : ""}`} onClick={() => setTab("preview")}>
            문서 미리보기
          </button>
        </div>
        <button className="icon-btn dark" onClick={onClose} title="닫기">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <div className="cl-progress-wrap">
        <div className="cl-progress-bar-bg">
          <div className="cl-progress-bar-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="cl-progress-label">
          <span>{done}/{total} 완료</span>
          <span className="cl-pct">{pct}%</span>
        </div>
      </div>

      {tab === "checklist" ? (
        <div className="cl-body">
          {categories.map(cat => {
            const theme = CATEGORY_THEME[cat.id] || CATEGORY_THEME_FALLBACK;
            const catDone = cat.items.filter(i => i.done).length;
            return (
              <div key={cat.id} className="cl-section">
                <div className="cl-sec-head">
                  <span className="cl-sec-dot" style={{ background: theme.dot }} />
                  <span className="cl-sec-title" style={{ color: theme.accent }}>{cat.title}</span>
                  <span className="cl-sec-count" style={{ color: theme.dot }}>
                    {catDone}/{cat.items.length}
                  </span>
                </div>
                <div className="cl-items">
                  {cat.items.length === 0 && (
                    <p className="cl-empty-hint">아직 항목이 없어요</p>
                  )}
                  {cat.items.map(item => (
                    <div key={item.id} className={`cl-item ${item.done ? "cl-done" : ""}`}>
                      <label className="cl-item-label">
                        <input
                          type="checkbox"
                          checked={item.done}
                          onChange={() => onToggle(cat.id, item.id)}
                          style={{ accentColor: theme.accent }}
                        />
                        <span className="cl-item-text">{item.text}</span>
                      </label>
                      <button
                        className="cl-item-del"
                        onClick={() => onDelete(cat.id, item.id)}
                        title="삭제"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
                <div className="cl-add-row">
                  <input
                    className="cl-add-input"
                    placeholder="항목 추가…"
                    value={newTexts[cat.id] || ""}
                    onChange={e => setNewTexts(p => ({ ...p, [cat.id]: e.target.value }))}
                    onKeyDown={e => e.key === "Enter" && handleAdd(cat.id)}
                  />
                  <button
                    className="cl-add-btn"
                    style={{ color: theme.accent }}
                    onClick={() => handleAdd(cat.id)}
                  >+</button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <DocumentPreview categories={categories} />
      )}

      <div className="cl-footer">
        <button className="cl-download-btn" onClick={handleDownload} disabled={downloading || total === 0}>
          {downloading ? "생성 중…" : "📄 워드(.docx)로 다운로드"}
        </button>
      </div>
    </aside>
  );
}

let _nextId = 1;
const uid = () => _nextId++;

export default function App() {
  const [conversations, setConversations] = useState([
    { id: 1, title: "새 대화", messages: [] }
  ]);
  const [activeId, setActiveId] = useState(1);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState(MODELS[0].id);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [checklistOpen, setChecklistOpen] = useState(true);
  const [categories, setCategories] = useState(() =>
    SEED_CATEGORIES.map(c => ({ ...c, items: [...c.items] }))
  );
  const nextConvId = useRef(2);
  const bottomRef = useRef(null);
  const textareaRef = useRef(null);

  const activeConv = conversations.find(c => c.id === activeId);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeConv?.messages]);

  const updateConv = useCallback((id, updater) => {
    setConversations(prev => prev.map(c => c.id === id ? { ...c, ...updater(c) } : c));
  }, []);

  const toggleChecklistItem = useCallback((catId, itemId) => {
    setCategories(prev => prev.map(c =>
      c.id !== catId ? c : {
        ...c, items: c.items.map(i => i.id === itemId ? { ...i, done: !i.done } : i)
      }
    ));
  }, []);

  const deleteChecklistItem = useCallback((catId, itemId) => {
    setCategories(prev => prev.map(c =>
      c.id !== catId ? c : {
        ...c, items: c.items.filter(i => i.id !== itemId)
      }
    ));
  }, []);

  const addManualItem = useCallback((catId, text) => {
    setCategories(prev => prev.map(c =>
      c.id !== catId ? c : {
        ...c, items: [...c.items, { id: `${catId}_${Date.now()}`, text, done: false }]
      }
    ));
  }, []);

  // AI가 제안한 이슈들을 카테고리별로 체크리스트에 추가. 없는 카테고리는 새로 만든다
  // (지금은 보안/IT 두 개뿐이지만 이후 카테고리가 늘어나도 그대로 동작).
  const addIssuesToChecklist = useCallback((items) => {
    setCategories(prev => {
      const next = prev.map(c => ({ ...c, items: [...c.items] }));
      for (const issue of items) {
        let cat = next.find(c => c.id === issue.category_id);
        if (!cat) {
          cat = { id: issue.category_id, title: issue.category_label || issue.category_id, items: [] };
          next.push(cat);
        }
        cat.items.push({ id: issue.id, text: issue.text, done: false });
      }
      return next;
    });
  }, []);

  // 이슈 카드에서 체크한 항목만 체크리스트에 추가하고, 큐에 다음 카테고리가
  // 남아있으면 이어서 새 이슈 카드를 하나 더 띄운다 (보안 → IT 순으로 하나씩 물어보기 위함).
  const handleAddIssues = useCallback((convId, msg, selectedItems) => {
    if (selectedItems.length > 0) addIssuesToChecklist(selectedItems);
    updateConv(convId, c => {
      const messages = c.messages.map(m => m.id === msg.id ? { ...m, added: true } : m);
      if (msg.queue && msg.queue.length > 0) {
        const [nextGroup, ...restQueue] = msg.queue;
        messages.push({ id: uid(), type: "issues", group: nextGroup, queue: restQueue, added: false });
      }
      return { messages };
    });
  }, [addIssuesToChecklist, updateConv]);

  const newChat = () => {
    const id = nextConvId.current++;
    setConversations(prev => [...prev, { id, title: "새 대화", messages: [] }]);
    setActiveId(id);
    setInput("");
  };

  const deleteChat = (id, e) => {
    e.stopPropagation();
    setConversations(prev => {
      const next = prev.filter(c => c.id !== id);
      if (!next.length) {
        const newId = nextConvId.current++;
        setActiveId(newId);
        return [{ id: newId, title: "새 대화", messages: [] }];
      }
      if (activeId === id) setActiveId(next.at(-1).id);
      return next;
    });
  };

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsgId   = uid();
    const answerMsgId = uid();
    const targetId = activeId;

    const userMsg   = { id: userMsgId,   type: "user",   content: text };
    const answerMsg = { id: answerMsgId, type: "answer", content: "", streaming: true, phase: null };

    const prevMessages = activeConv?.messages ?? [];
    updateConv(targetId, c => ({
      messages: [...c.messages, userMsg, answerMsg],
      title: c.messages.length === 0 ? text.slice(0, 28) : c.title,
    }));

    setInput("");
    textareaRef.current && (textareaRef.current.style.height = "auto");
    setLoading(true);

    const history = buildHistory(prevMessages);
    history.push({ role: "user", content: text });

    try {
      const res = await fetch(`${API_URL}/agent-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history, model }),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = JSON.parse(line.slice(6));

          if (data.type === "clarify") {
            updateConv(targetId, c => ({
              messages: c.messages.map(m =>
                m.id === answerMsgId ? { ...m, type: "clarify", content: data.message } : m
              ),
            }));
          } else if (data.type === "law_searching") {
            updateConv(targetId, c => ({
              messages: c.messages.map(m =>
                m.id === answerMsgId ? { ...m, phase: "law" } : m
              ),
            }));
          } else if (data.type === "answer_start") {
            updateConv(targetId, c => ({
              messages: c.messages.map(m =>
                m.id === answerMsgId ? { ...m, phase: null } : m
              ),
            }));
          } else if (data.type === "text") {
            updateConv(targetId, c => ({
              messages: c.messages.map(m =>
                m.id === answerMsgId ? { ...m, content: m.content + data.text } : m
              ),
            }));
          } else if (data.type === "answer_done") {
            updateConv(targetId, c => ({
              messages: c.messages.map(m =>
                m.id === answerMsgId ? { ...m, streaming: false } : m
              ),
            }));
          } else if (data.type === "issue_suggestion") {
            const groups = groupIssuesByCategory(data.items, data.checked_categories);
            if (groups.length > 0) {
              const [firstGroup, ...restQueue] = groups;
              updateConv(targetId, c => ({
                messages: [...c.messages, { id: uid(), type: "issues", group: firstGroup, queue: restQueue, added: false }],
              }));
            }
          }
        }
      }
    } catch (err) {
      updateConv(targetId, c => ({
        messages: c.messages.map(m =>
          m.id === answerMsgId
            ? { ...m, content: `요청 처리 중 오류가 발생했습니다: ${err.message}`, streaming: false, phase: null }
            : m
        ),
      }));
    } finally {
      setLoading(false);
      textareaRef.current?.focus();
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const autoResize = (e) => {
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
  };

  return (
    <div className="app">
      {/* 사이드바 */}
      <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <span className="sidebar-logo">NH</span>
            <span className="sidebar-title">AI 어시스턴트</span>
          </div>
          <button className="icon-btn" onClick={() => setSidebarOpen(false)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M15 18l-6-6 6-6"/>
            </svg>
          </button>
        </div>

        <button className="new-chat-btn" onClick={newChat}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M12 5v14M5 12h14"/>
          </svg>
          새 대화
        </button>

        <nav className="conv-list">
          {[...conversations].reverse().map(c => (
            <div
              key={c.id}
              className={`conv-item ${c.id === activeId ? "active" : ""}`}
              onClick={() => setActiveId(c.id)}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" style={{ flexShrink: 0, opacity: 0.5 }}>
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
              </svg>
              <span className="conv-title">{c.title}</span>
              <button className="del-btn" onClick={(e) => deleteChat(c.id, e)}>×</button>
            </div>
          ))}
        </nav>
      </aside>

      {/* 메인 */}
      <div className="main">
        <header className="top-bar">
          {!sidebarOpen && (
            <button className="icon-btn dark" onClick={() => setSidebarOpen(true)}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 18l6-6-6-6"/>
              </svg>
            </button>
          )}
          <span className="conv-name">{activeConv?.title || "새 대화"}</span>
          <select className="model-select" value={model} onChange={e => setModel(e.target.value)}>
            {MODELS.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <button
            className={`checklist-toggle-btn ${checklistOpen ? "active" : ""}`}
            onClick={() => setChecklistOpen(o => !o)}
            title="체크리스트"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
            </svg>
            체크리스트
          </button>
        </header>

        <main className="chat-area">
          {activeConv?.messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">🤖</div>
              <p className="empty-title">IT 프로젝트나 사업 아이디어를 알려주세요</p>
              <p className="empty-sub">플랫폼·보안·규정·인증을 종합적으로 검토해 드려요</p>
            </div>
          ) : (
            activeConv.messages.map((msg) => (
              <ChatMessage
                key={msg.id}
                msg={msg}
                onAddIssues={(selectedItems) => handleAddIssues(activeId, msg, selectedItems)}
              />
            ))
          )}
          <div ref={bottomRef} />
        </main>

        <div className="input-area">
          <div className="input-box">
            <textarea
              ref={textareaRef}
              className="chat-input"
              placeholder="질문을 입력하세요… (Shift+Enter: 줄바꿈, Enter: 전송)"
              value={input}
              onChange={e => { setInput(e.target.value); autoResize(e); }}
              onKeyDown={onKeyDown}
              rows={1}
              disabled={loading}
            />
            <button className={`send-btn ${loading ? "loading" : ""}`} onClick={send} disabled={!input.trim() || loading}>
              {loading
                ? <span className="spinner" />
                : <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
                    <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
              }
            </button>
          </div>
          <p className="input-hint">{MODELS.find(m => m.id === model)?.label}</p>
        </div>
      </div>

      {/* 체크리스트 / 문서 미리보기 패널 */}
      {checklistOpen && (
        <SidePanel
          categories={categories}
          onToggle={toggleChecklistItem}
          onAddManual={addManualItem}
          onDelete={deleteChecklistItem}
          onClose={() => setChecklistOpen(false)}
        />
      )}
    </div>
  );
}
