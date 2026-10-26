import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Target = { id: string; school: string; college: string; major: string; exam_subject: string; exam_code: string; target_year: number; source_url: string; source_checked_at: string | null; verified: number };
type Topic = { id: string; subject: string; module: string; name: string; summary: string };
type Question = { id: string; target_id: string; topic_id: string; source_type: string; source_name: string; question_type: string; difficulty: number; stem: string; answer: string; analysis: string; review_status: string };
type Attempt = { id: number; question_id: string; answer_text: string; self_rating: number; created_at: string };
type Stats = { attempt_count: number; topic_stats: { topic_id: string; name: string; attempts: number; average_self_rating: number }[]; method: string };
type Nav = '今日学习' | '知识地图' | '真题' | '兄弟院校' | '精品练习' | 'AI练习' | '学习统计' | '在线论坛' | '设置';

const NAV: Nav[] = ['今日学习', '知识地图', '真题', '兄弟院校', '精品练习', 'AI练习', '学习统计', '在线论坛', '设置'];
const API = 'http://127.0.0.1:8000';
async function get<T>(path: string): Promise<T> { const r = await fetch(API + path); if (!r.ok) throw new Error('读取失败'); return r.json(); }
async function send<T>(path: string, body?: object): Promise<T> { const r = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); if (!r.ok) { const e = await r.json().catch(() => null); throw new Error(e?.detail || '保存失败'); } return r.json(); }
async function put<T>(path: string, body: object): Promise<T> { const r = await fetch(API + path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); if (!r.ok) { const e = await r.json().catch(() => null); throw new Error(e?.detail || '保存失败'); } return r.json(); }
const emptyTarget = { id: '', school: '', college: '', major: '', exam_subject: '', exam_code: '', target_year: new Date().getFullYear() + 2, source_url: '' };

function App() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [targetId, setTargetId] = useState(localStorage.getItem('econ-target') || 'demo-pku');
  const [nav, setNav] = useState<Nav>('今日学习');
  const [admin, setAdmin] = useState(false);
  const [adminSection, setAdminSection] = useState<'院校与考试' | '题目中心'>('院校与考试');
  const [targetDraft, setTargetDraft] = useState(emptyTarget);
  const [editingTarget, setEditingTarget] = useState(false);
  const [star, setStar] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<string>('consumer');
  const [selectedQuestion, setSelectedQuestion] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState('');
  const [reveal, setReveal] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const [yearMode, setYearMode] = useState<'年份' | '知识点'>('年份');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState({ id: '', target_id: 'demo-pku', topic_id: 'consumer', source_type: 'CURATED_EXERCISE', source_name: '平台原创练习', question_type: '简答题', difficulty: 2, stem: '', answer: '', analysis: '' });

  async function refresh() {
    try {
      const [ts, ks, qs, ats, st] = await Promise.all([get<Target[]>('/api/targets'), get<Topic[]>('/api/topics'), get<Question[]>('/api/questions?admin=true'), get<Attempt[]>('/api/attempts'), get<Stats>(`/api/stats?target_id=${encodeURIComponent(targetId)}`)]);
      setTargets(ts); setTopics(ks); setQuestions(qs); setAttempts(ats); setStats(st); setError('');
    } catch { setError('无法连接本地服务。请先启动 FastAPI 后端，然后点击“重试”。'); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, [targetId]);
  useEffect(() => { localStorage.setItem('econ-target', targetId); }, [targetId]);
  const target = targets.find(t => t.id === targetId);
  const topic = topics.find(t => t.id === selectedTopic);
  const question = questions.find(q => q.id === selectedQuestion);
  const topicQuestions = questions.filter(q => q.target_id === targetId && q.topic_id === selectedTopic && q.review_status === 'APPROVED');
  const visibleQuestions = questions.filter(q => q.target_id === targetId && q.review_status === 'APPROVED');
  const focusQuestion = visibleQuestions[0];
  const focusTopic = topics.find(t => t.id === focusQuestion?.topic_id);
  const completed = new Set(attempts.map(a => a.question_id));
  const bodyTitle = admin ? '内容管理' : star ? '择校信息中心' : nav;
  const content = useMemo(() => {
    if (admin) return adminSection === '院校与考试' ? '目标考试配置' : '题目中心 · 审核与发布';
    if (star) return '目标考试信息';
    if (nav === '真题') return `按${yearMode}浏览`;
    return nav === '知识地图' ? '知识目录' : nav === '精品练习' ? '题目列表' : nav === '学习统计' ? '诊断维度' : '工作目录';
  }, [admin, adminSection, star, nav, yearMode]);

  function openQuestion(id: string) { setSelectedQuestion(id); setAnswerText(''); setReveal(false); setRating(null); }
  async function saveAttempt() {
    if (!question || !answerText.trim() || rating === null) return;
    try { await send('/api/attempts', { question_id: question.id, answer_text: answerText, self_rating: rating }); await refresh(); setSelectedQuestion(null); }
    catch (e) { setError((e as Error).message); }
  }
  async function createQuestion() {
    try { await send('/api/admin/questions', draft); await refresh(); setDraft({ ...draft, id: '', stem: '', answer: '', analysis: '' }); }
    catch (e) { setError((e as Error).message); }
  }
  async function approveQuestion(id: string) { try { await send(`/api/admin/questions/${id}/approve`); await refresh(); } catch (e) { setError((e as Error).message); } }
  async function saveTarget() {
    try {
      if (editingTarget) await put(`/api/admin/targets/${encodeURIComponent(targetDraft.id)}`, targetDraft);
      else await send('/api/admin/targets', targetDraft);
      await refresh(); setTargetDraft(emptyTarget); setEditingTarget(false);
    } catch (e) { setError((e as Error).message); }
  }
  function editTarget(item: Target) {
    setTargetDraft({ id: item.id, school: item.school, college: item.college, major: item.major, exam_subject: item.exam_subject, exam_code: item.exam_code, target_year: item.target_year, source_url: item.source_url });
    setEditingTarget(true);
  }
  async function verifyTarget(id: string) {
    if (!window.confirm('请确认已人工打开并核对该来源中的院校、专业、科目和年份。核验后信息会在用户端标记为已核验。')) return;
    try { await send(`/api/admin/targets/${encodeURIComponent(id)}/verify`); await refresh(); }
    catch (e) { setError((e as Error).message); }
  }

  const questionRows = (items: Question[]) => items.length ? items.map(q => <button className="question-row" key={q.id} onClick={() => openQuestion(q.id)}>
    <span className="question-main"><b>{q.stem}</b><small>{topics.find(t => t.id === q.topic_id)?.name} · {q.question_type} · 难度 {q.difficulty}/5</small></span>
    <span className="question-end">{completed.has(q.id) ? '已练习' : '开始练习'} <span aria-hidden="true">→</span></span>
  </button>) : <div className="empty">当前没有可用题目。管理员审核发布后会显示在这里。</div>;

  return <div className="app">
    <header className="topbar"><div className="header-leading">
      <div className="target-control"><span className="tiny-label">切换院校：</span><select aria-label="切换目标院校" value={targetId} onChange={e => { setTargetId(e.target.value); const first = questions.find(q => q.target_id === e.target.value && q.review_status === 'APPROVED'); if (first) setSelectedTopic(first.topic_id); }}>{targets.map(t => <option value={t.id} key={t.id}>{t.school} · {t.exam_code || t.exam_subject} · {t.target_year}{t.id.startsWith('demo-') ? '（演示）' : ''}</option>)}</select></div>
      <button className={`star ${star ? 'active' : ''}`} onClick={() => { setStar(!star); setAdmin(false); }} aria-label="择校信息中心" title="择校信息中心">★</button>
    </div><div className="platform-title">经济学考研学习平台</div><div className="header-trailing"><span className="demo-badge">本地演示版</span><button className="mode-button" onClick={() => { setAdmin(!admin); setStar(false); setSelectedQuestion(null); }}>{admin ? '返回用户端' : '管理员端'}</button></div>
    </header>
    <div className="shell">
      <aside className="rail"><div className="rail-section">{admin ? '管理工作台' : '学习工作台'}</div>{admin ? <><button className={`rail-item ${adminSection === '院校与考试' ? 'active' : ''}`} onClick={() => setAdminSection('院校与考试')}>院校与考试</button><button className={`rail-item ${adminSection === '题目中心' ? 'active' : ''}`} onClick={() => setAdminSection('题目中心')}>题目中心</button><div className="rail-note">知识、真题等管理能力按 P0 顺序继续接入。</div></> : NAV.map((item, i) => <button key={item} className={`rail-item ${nav === item && !star ? 'active' : ''}`} onClick={() => { setNav(item); setStar(false); setSelectedQuestion(null); }}><span className="rail-index">{String(i + 1).padStart(2, '0')}</span>{item}</button>)}</aside>
      <aside className="catalog"><div className="catalog-head"><span>{content}</span><small>{admin ? `${questions.length} 道题目` : target?.school || '选择目标'}</small></div>
        {admin ? adminSection === '院校与考试' ? <><button className={`catalog-item ${!editingTarget ? 'selected' : ''}`} onClick={() => { setTargetDraft(emptyTarget); setEditingTarget(false); }}>新增目标考试</button>{targets.map(t => <button className={`catalog-item ${editingTarget && targetDraft.id === t.id ? 'selected' : ''}`} key={t.id} onClick={() => editTarget(t)}>{t.school} · {t.target_year}<small>{t.verified ? '已人工核验' : '待核验'}</small></button>)}</> : <><button className="catalog-item selected">录入题目</button><button className="catalog-item">待审核 · {questions.filter(q => q.review_status === 'DRAFT').length}</button></>
        : star ? <><button className="catalog-item selected">目标院校</button><button className="catalog-item">信息须知</button></>
        : nav === '知识地图' ? topics.map(t => <button className={`catalog-item ${selectedTopic === t.id ? 'selected' : ''}`} key={t.id} onClick={() => setSelectedTopic(t.id)}><small>{t.subject} / {t.module}</small>{t.name}</button>)
        : nav === '真题' ? <><button className={`catalog-item ${yearMode === '年份' ? 'selected' : ''}`} onClick={() => setYearMode('年份')}>按年份</button><button className={`catalog-item ${yearMode === '知识点' ? 'selected' : ''}`} onClick={() => setYearMode('知识点')}>按知识点</button></>
        : nav === '精品练习' ? <><button className="catalog-item selected">全部练习</button>{topics.map(t => <button className="catalog-item" key={t.id} onClick={() => { setSelectedTopic(t.id); setNav('知识地图'); }}>{t.name}</button>)}</>
        : nav === '学习统计' ? <><button className="catalog-item selected">学习总览</button><button className="catalog-item">知识掌握度</button><button className="catalog-item">错题记录</button></>
        : <><button className="catalog-item selected">{nav === '今日学习' ? '今日总览' : nav === 'AI练习' ? '能力规划' : nav === '在线论坛' ? '社区动态' : '账户信息'}</button></>}
        <div className="catalog-foot">内容范围随目标院校切换<br />学习记录会保留</div>
      </aside>
      <main className={`workspace ${admin && adminSection === '院校与考试' ? 'target-admin-view' : ''}`}>
        {error && <div className="error" role="alert">{error}<button onClick={() => void refresh()}>重试</button></div>}
        {admin && adminSection === '院校与考试' && <section className="target-admin-content">
          <div className="page-heading"><div><h1>院校与考试</h1><p>维护用户目标考试的院校、专业、科目与来源。新建或编辑后默认为待核验。</p></div><span className="status-pill">本机开发 · 人工核验</span></div>
          <div className="admin-grid"><div className="panel"><h2>{editingTarget ? '编辑目标考试' : '新增目标考试'}</h2>
            <div className="form-grid">
              <label>配置 ID<input value={targetDraft.id} disabled={editingTarget} placeholder="如 pku-econ-2028" onChange={e => setTargetDraft({ ...targetDraft, id: e.target.value })} /></label>
              <label>目标年份<input type="number" min="2020" max="2100" value={targetDraft.target_year} onChange={e => setTargetDraft({ ...targetDraft, target_year: Number(e.target.value) })} /></label>
              <label>院校<input value={targetDraft.school} onChange={e => setTargetDraft({ ...targetDraft, school: e.target.value })} /></label>
              <label>学院 / 培养单位<input value={targetDraft.college} onChange={e => setTargetDraft({ ...targetDraft, college: e.target.value })} /></label>
              <label>专业<input value={targetDraft.major} onChange={e => setTargetDraft({ ...targetDraft, major: e.target.value })} /></label>
              <label>考试科目<input value={targetDraft.exam_subject} onChange={e => setTargetDraft({ ...targetDraft, exam_subject: e.target.value })} /></label>
              <label>考试代码<input value={targetDraft.exam_code} onChange={e => setTargetDraft({ ...targetDraft, exam_code: e.target.value })} /></label>
            </div>
            <label>信息来源链接（HTTPS）<input type="url" value={targetDraft.source_url} placeholder="https://..." onChange={e => setTargetDraft({ ...targetDraft, source_url: e.target.value })} /></label>
            <p className="data-note">“已核验”仅表示管理员人工对照来源；平台不会自动判定官网真实性。编辑已核验配置会重新变为待核验。</p>
            <div className="action-row"><button className="primary" disabled={!targetDraft.id || !targetDraft.school || !targetDraft.major || !targetDraft.exam_subject} onClick={() => void saveTarget()}>{editingTarget ? '保存修改' : '保存新配置'}</button>{editingTarget && <button className="back" onClick={() => { setEditingTarget(false); setTargetDraft(emptyTarget); }}>取消编辑</button>}</div>
          </div><div className="panel"><h2>配置与核验状态</h2>{targets.map(t => <div className="review-row" key={t.id}><b>{t.school} · {t.target_year}</b><small>{t.college ? `${t.college} · ` : ''}{t.major} · {t.exam_code ? `${t.exam_code} ` : ''}{t.exam_subject}</small><small>{t.verified ? `已核验 · ${t.source_checked_at?.slice(0, 10)}` : '待核验'}{t.id.startsWith('demo-') ? ' · 演示配置' : ''}</small>{t.source_url ? <p><a href={t.source_url} target="_blank" rel="noopener noreferrer">打开来源核对 ↗</a></p> : <small>尚无来源链接</small>}<div className="target-actions"><button onClick={() => editTarget(t)}>编辑</button>{!t.verified && t.source_url && <button onClick={() => void verifyTarget(t.id)}>确认人工核验</button>}</div></div>)}</div></div>
        </section>}
        {loading ? <p>正在载入工作台…</p> : question ? <section className="content-sheet"><button className="back" onClick={() => setSelectedQuestion(null)}>← 返回列表</button><div className="sheet-label">练习 / {question.source_name}</div><h1>题目训练</h1><div className="meta-row"><span>{topics.find(t => t.id === question.topic_id)?.name}</span><span>{question.question_type}</span><span>难度 {question.difficulty}/5</span></div><p className="stem">{question.stem}</p><label className="field-label" htmlFor="answer">我的作答</label><textarea id="answer" rows={6} placeholder="写下你的解题过程或回答要点" value={answerText} onChange={e => setAnswerText(e.target.value)} /><div className="action-row"><button className="primary" onClick={() => setReveal(true)} disabled={!answerText.trim()}>查看参考答案</button><span className="hint">主观题由你自评，不进行自动判分。</span></div>{reveal && <div className="answer-panel"><h2>参考答案</h2><p>{question.answer}</p><h3>解析</h3><p>{question.analysis}</p><div className="rating"><b>对照答案后，你掌握了多少？</b>{[0,1,2,3].map(n => <button className={rating === n ? 'chosen' : ''} key={n} onClick={() => setRating(n)}>{['未掌握','部分理解','基本掌握','能够独立完成'][n]}</button>)}</div><button className="primary" disabled={rating === null} onClick={() => void saveAttempt()}>保存作答与自评</button></div>}</section>
        : admin ? <section><div className="page-heading"><div><h1>题目中心</h1><p>录入练习题后先保存为草稿，审核通过才对学习端可见。</p></div><span className="status-pill">开发环境 · 无登录保护</span></div><div className="admin-grid"><div className="panel"><h2>新建练习题</h2><div className="form-grid"><label>题目 ID<input value={draft.id} placeholder="如 q-new-001" onChange={e => setDraft({ ...draft, id: e.target.value })} /></label><label>关联目标<select value={draft.target_id} onChange={e => setDraft({ ...draft, target_id: e.target.value })}>{targets.map(t => <option value={t.id} key={t.id}>{t.school}</option>)}</select></label><label>知识点<select value={draft.topic_id} onChange={e => setDraft({ ...draft, topic_id: e.target.value })}>{topics.map(t => <option value={t.id} key={t.id}>{t.name}</option>)}</select></label><label>题型<select value={draft.question_type} onChange={e => setDraft({ ...draft, question_type: e.target.value })}>{['简答题','计算题','论述题','图形分析题','名词解释'].map(x => <option key={x}>{x}</option>)}</select></label><label>难度 1–5<input type="number" min="1" max="5" value={draft.difficulty} onChange={e => setDraft({ ...draft, difficulty: Number(e.target.value) })} /></label><label>来源类型<select value={draft.source_type} onChange={e => setDraft({ ...draft, source_type: e.target.value })}><option value="CURATED_EXERCISE">精品练习</option><option value="AI_GENERATED">AI 草稿</option></select></label></div><label>来源说明<input value={draft.source_name} onChange={e => setDraft({ ...draft, source_name: e.target.value })} /></label><label>题干<textarea rows={3} value={draft.stem} onChange={e => setDraft({ ...draft, stem: e.target.value })} /></label><label>参考答案<textarea rows={2} value={draft.answer} onChange={e => setDraft({ ...draft, answer: e.target.value })} /></label><label>解析<textarea rows={2} value={draft.analysis} onChange={e => setDraft({ ...draft, analysis: e.target.value })} /></label><button className="primary" disabled={!draft.id || !draft.stem || !draft.answer || !draft.analysis} onClick={() => void createQuestion()}>保存草稿</button></div><div className="panel"><h2>审核队列</h2>{questions.map(q => <div className="review-row" key={q.id}><b>{q.stem}</b><small>{q.source_name} · {q.review_status}</small>{q.review_status !== 'APPROVED' && <button onClick={() => void approveQuestion(q.id)}>审核通过</button>}</div>)}</div></div></section>
        : star ? <section><div className="page-heading"><div><h1>择校信息中心</h1><p>围绕当前目标院校汇总考试信息与核验状态。</p></div></div><div className="notice-box"><b>{target?.school || '尚未选择院校'} · {target?.target_year}</b><p>{target?.college ? `${target.college} · ` : ''}{target?.major} · {target?.exam_code ? `${target.exam_code} ` : ''}{target?.exam_subject}</p><strong>{target?.verified ? '考试配置已人工核验' : '考试配置待核验'}</strong>{target?.source_url && <p><a href={target.source_url} target="_blank" rel="noopener noreferrer">查看信息来源 ↗</a>{target.source_checked_at ? ` · 核验日期 ${target.source_checked_at.slice(0, 10)}` : ''}</p>}<p>这里仅展示目标考试配置。招生简章、参考书、分数线和最新通知尚未接入；请以院校官网公布的信息为准。{target?.id.startsWith('demo-') ? '当前目标为演示配置。' : ''}</p></div></section>
        : nav === '今日学习' ? <section><div className="page-heading"><div><h1>今天，从目标出发。</h1><p>{target?.school} · {target?.target_year} 届备考工作台</p></div><span className="status-pill">考试日期待确认</span></div><div className="hero-strip"><div><span>当前阶段</span><h2>建立知识与题目的第一条联系</h2><p>先熟悉一个知识点，再完成一道练习，系统会保存你的作答与自评。</p><button className="primary" onClick={() => { setNav('知识地图'); if (focusTopic) setSelectedTopic(focusTopic.id); }}>进入知识地图 <span aria-hidden="true">→</span></button></div><div className="hero-aside"><span>已保存作答</span><strong>{attempts.length}</strong><small>仅统计本地演示用户</small></div></div><div className="section-heading"><h2>今日可做</h2><span>从一项具体任务开始</span></div><div className="task-list"><button onClick={() => { setNav('知识地图'); if (focusTopic) setSelectedTopic(focusTopic.id); }}><span className="task-num">01</span><span><b>{focusTopic ? `理解${focusTopic.name}` : '浏览知识地图'}</b><small>知识地图 · {focusTopic?.subject || '经济学'}</small></span><span>查看知识点 →</span></button><button disabled={!focusQuestion} onClick={() => { setNav('精品练习'); if (focusQuestion) openQuestion(focusQuestion.id); }}><span className="task-num">02</span><span><b>{focusQuestion ? `完成${focusTopic?.name}演示题` : '当前目标暂无演示题'}</b><small>精品练习 · {focusQuestion?.question_type || '等待内容审核'}</small></span><span>{focusQuestion ? completed.has(focusQuestion.id) ? '再练一次 →' : '开始练习 →' : '暂无内容'}</span></button><button onClick={() => setNav('学习统计')}><span className="task-num">03</span><span><b>查看学习反馈</b><small>学习统计 · 自评记录</small></span><span>查看统计 →</span></button></div><p className="data-note">当前所有学习内容均为演示样本；尚未接入已核验的院校真题和通知。</p></section>
        : nav === '知识地图' ? <section><div className="page-heading"><div><h1>{topic?.name}</h1><p>{topic?.subject} / {topic?.module}</p></div><span className="status-pill">知识卡 · 演示内容</span></div><div className="knowledge-layout"><div className="panel knowledge-main"><h2>核心理解</h2><p>{topic?.summary}</p><div className="divider" /><h3>如何练习</h3><p>阅读概念与解题方法后，尝试不看答案独立作答。提交后对照解析，并记录自己的掌握程度。</p><button className="primary" disabled={!topicQuestions.length} onClick={() => topicQuestions[0] && openQuestion(topicQuestions[0].id)}>练习关联题目 →</button></div><div className="knowledge-side"><div className="plain-stat"><span>关联练习</span><strong>{topicQuestions.length}</strong><small>已审核演示题</small></div><div className="plain-stat"><span>我的作答</span><strong>{attempts.filter(a => topicQuestions.some(q => q.id === a.question_id)).length}</strong><small>可反复练习</small></div></div></div><div className="section-heading"><h2>关联题目</h2></div>{questionRows(topicQuestions)}</section>
        : nav === '真题' ? <section><div className="page-heading"><div><h1>目标院校真题</h1><p>{target?.school} · {target?.exam_subject}</p></div><span className="status-pill">按{yearMode}浏览</span></div><div className="empty-feature"><h2>真题资料正在核验</h2><p>目前没有已确认来源的真题。管理员端后续会建立试卷、单题、年份与知识点关系；核验完成后才能展示。</p><button onClick={() => setNav('精品练习')}>先练习演示题 →</button></div></section>
        : nav === '兄弟院校' ? <section><div className="page-heading"><div><h1>兄弟院校</h1><p>补充与目标院校难度相近或稍难的近五年真题。</p></div></div><div className="empty-feature"><h2>院校关联待审核</h2><p>关联理由、真题年份与来源需要逐项核验。当前还没有可发布的兄弟院校真题。</p></div></section>
        : nav === '精品练习' ? <section><div className="page-heading"><div><h1>精品练习</h1><p>按知识点与题型组织高质量练习。当前为平台原创演示题。</p></div><span className="status-pill">{visibleQuestions.length} 道已审核题目</span></div>{questionRows(visibleQuestions)}</section>
        : nav === 'AI练习' ? <section><div className="page-heading"><div><h1>AI 练习</h1><p>组卷、答疑与错题分析将依赖可靠的题库和学习记录。</p></div></div><div className="empty-feature"><h2>先积累可解释的学习数据</h2><p>当前版本已支持知识点学习、题目作答、自评记录与基础反馈。AI 能力会在内容来源与数据闭环稳定后接入。</p><button onClick={() => setNav('精品练习')}>开始第一道练习 →</button></div></section>
        : nav === '学习统计' ? <section><div className="page-heading"><div><h1>学习统计</h1><p>用实际作答记录观察知识点表现。</p></div><span className="status-pill">本地演示用户</span></div><div className="stats-summary"><div><span>有效作答</span><strong>{stats?.attempt_count ?? 0}</strong><small>次提交与自评</small></div><div><span>已练知识点</span><strong>{stats?.topic_stats.length ?? 0}</strong><small>个知识节点</small></div></div><div className="section-heading"><h2>按知识点查看</h2><span>自评均值 / 3</span></div>{stats?.topic_stats.length ? stats.topic_stats.map(s => <button className="stat-row" key={s.topic_id} onClick={() => { setSelectedTopic(s.topic_id); setNav('知识地图'); }}><span><b>{s.name}</b><small>{s.attempts} 次作答</small></span><strong>{s.average_self_rating.toFixed(1)}</strong><span>复习知识点 →</span></button>) : <div className="empty">完成一次练习并保存自评后，这里会出现对应知识点的记录。</div>}<p className="data-note">{stats?.method}</p></section>
        : nav === '在线论坛' ? <section><div className="page-heading"><div><h1>在线论坛</h1><p>学习打卡与知识点交流将在后续版本开放。</p></div></div><div className="empty-feature"><h2>社区空间已预留</h2><p>完整的帖子、图片上传、回答与内容审核流程尚未开发。</p></div></section>
        : <section><div className="page-heading"><div><h1>设置</h1><p>管理当前学习目标与本地演示环境。</p></div></div><div className="panel"><h2>目标院校</h2><p>切换院校会更新页面上下文，历史作答保持不变。</p><select aria-label="设置目标院校" value={targetId} onChange={e => setTargetId(e.target.value)}>{targets.map(t => <option key={t.id} value={t.id}>{t.school} · {t.target_year}</option>)}</select><p className="data-note">当前无账号体系，所有记录属于同一个本地演示用户。请勿录入真实个人资料。</p></div></section>}
      </main>
    </div>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
