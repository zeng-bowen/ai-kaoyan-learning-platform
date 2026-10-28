import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Target = { id: string; school: string; exam_label: string; note: string; target_year: number };
type Topic = { id: string; subject: string; module: string; name: string; summary: string; target_ids: string[] };
type Question = { id: string; catalog_number: string; target_id: string; topic_id: string; source_type: string; source_name: string; exam_year: number | null; question_type: string; difficulty: number; stem: string; answer: string; analysis: string };
type Attempt = { id: number; question_id: string; answer_text: string; self_rating: number };
type Stats = { attempt_count: number; topic_stats: { topic_id: string; name: string; attempts: number; average_self_rating: number }[]; method: string };
type Nav = '今日学习' | '知识地图' | '真题' | '兄弟院校' | '精品练习' | 'AI练习' | '学习统计' | '在线论坛' | '设置';
const NAV: Nav[] = ['今日学习', '知识地图', '真题', '兄弟院校', '精品练习', 'AI练习', '学习统计', '在线论坛', '设置'];
const API = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';
async function get<T>(path: string): Promise<T> { const response = await fetch(API + path); if (!response.ok) throw new Error('读取失败'); return response.json(); }
async function post<T>(path: string, body: object): Promise<T> { const response = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); if (!response.ok) throw new Error('保存失败'); return response.json(); }
const SESSION = sessionStorage.getItem('econ-study-session') || crypto.randomUUID();
sessionStorage.setItem('econ-study-session', SESSION);

function App() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [targetId, setTargetId] = useState(localStorage.getItem('econ-target') || 'demo-pku');
  const [nav, setNav] = useState<Nav>('今日学习');
  const [star, setStar] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState('consumer');
  const [selectedQuestion, setSelectedQuestion] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState('');
  const [reveal, setReveal] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const [yearMode, setYearMode] = useState<'年份' | '知识点'>('年份');
  const [examYear, setExamYear] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const contentVersion = useRef<number | null>(null);

  async function refresh() {
    try {
      const [ts, ks, qs, ats, st] = await Promise.all([
        get<Target[]>('/api/targets'), get<Topic[]>('/api/topics'), get<Question[]>('/api/questions'),
        get<Attempt[]>('/api/attempts'), get<Stats>(`/api/stats?target_id=${encodeURIComponent(targetId)}`),
      ]);
      setTargets(ts); setTopics(ks); setQuestions(qs); setAttempts(ats); setStats(st); setError('');
    } catch { setError('无法连接本地数据服务。请启动后端后重试。'); }
    finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, [targetId]);
  useEffect(() => { localStorage.setItem('econ-target', targetId); }, [targetId]);
  useEffect(() => { if (targets.length && !targets.some(item => item.id === targetId)) setTargetId(targets[0].id); }, [targets, targetId]);
  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        const current = await get<{ content: number }>('/api/versions');
        if (contentVersion.current !== null && current.content !== contentVersion.current) void refresh();
        contentVersion.current = current.content;
      } catch { /* The visible error is shown on the next explicit refresh. */ }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [targetId]);
  useEffect(() => {
    const active = Boolean(selectedQuestion);
    const heartbeat = () => { void post('/api/study-presence', { session_id: SESSION, active }).catch(() => undefined); };
    heartbeat();
    const timer = active ? window.setInterval(heartbeat, 10000) : undefined;
    return () => { if (timer) window.clearInterval(timer); if (active) void post('/api/study-presence', { session_id: SESSION, active: false }).catch(() => undefined); };
  }, [selectedQuestion]);

  const target = targets.find(item => item.id === targetId);
  const targetTopics = topics.filter(item => item.target_ids.includes(targetId));
  const currentTopicId = targetTopics.some(item => item.id === selectedTopic) ? selectedTopic : targetTopics[0]?.id;
  const topic = targetTopics.find(item => item.id === currentTopicId);
  const question = questions.find(item => item.id === selectedQuestion);
  const visible = questions.filter(item => item.target_id === targetId);
  const related = visible.filter(item => item.topic_id === currentTopicId);
  const past = visible.filter(item => item.source_type === 'TARGET_PAST_EXAM' && (examYear === null || item.exam_year === examYear));
  const years = [...new Set(visible.filter(item => item.source_type === 'TARGET_PAST_EXAM').map(item => item.exam_year).filter((year): year is number => year !== null))].sort((a, b) => b - a);
  const completed = new Set(attempts.map(item => item.question_id));
  const focus = visible.find(item => item.source_type === 'CURATED_EXERCISE');

  function openQuestion(id: string) { setSelectedQuestion(id); setAnswerText(''); setReveal(false); setRating(null); }
  async function saveAttempt() {
    if (!question || !answerText.trim() || rating === null) return;
    try { await post('/api/attempts', { question_id: question.id, answer_text: answerText, self_rating: rating }); await refresh(); setSelectedQuestion(null); }
    catch { setError('作答保存失败，请检查连接后重试。'); }
  }
  function questionRows(items: Question[]) {
    return items.length ? items.map(item => <button className="question-row" key={item.id} onClick={() => openQuestion(item.id)}>
      <span className="question-main"><b>{item.catalog_number} · {item.stem}</b><small>{topics.find(t => t.id === item.topic_id)?.name} · {item.source_name} · {item.question_type} · 难度 {item.difficulty}/5</small></span>
      <span className="question-end">{completed.has(item.id) ? '再练一次' : '开始练习'} →</span>
    </button>) : <div className="empty">当前没有已审核发布的题目。请稍后查看。</div>;
  }

  function knowledgeSection() {
    return <section>
      <div className="page-heading"><div><h1>{topic?.name || '知识地图'}</h1><p>{topic ? `${topic.subject} / ${topic.module}` : target ? `${target.school} · ${target.exam_label}` : '请选择考试标签'}</p></div><span className="status-pill">知识目录</span></div>
      {!topic ? <div className="empty">当前考试标签下暂无已审核发布的知识点。切换标签或稍后查看。</div> : <>
        <div className="knowledge-layout"><div className="panel knowledge-main"><h2>核心理解</h2><p>{topic.summary}</p><div className="divider" /><h3>如何练习</h3><p>阅读概念后，尝试独立作答，再对照解析记录掌握程度。</p><button className="primary" disabled={!related.length} onClick={() => related[0] && openQuestion(related[0].id)}>练习关联题目 →</button></div><div className="knowledge-side"><div className="plain-stat"><span>关联练习</span><strong>{related.length}</strong><small>已审核题目</small></div><div className="plain-stat"><span>我的作答</span><strong>{attempts.filter(item => related.some(q => q.id === item.question_id)).length}</strong><small>可反复练习</small></div></div></div>
        <div className="section-heading"><h2>关联题目</h2></div>{questionRows(related)}
      </>}
    </section>;
  }

  return <div className="app user-app">
    <header className="topbar"><div className="header-leading"><div className="target-control"><span className="tiny-label">切换院校：</span><select aria-label="切换目标院校" value={targets.some(item => item.id === targetId) ? targetId : ''} onChange={event => { setTargetId(event.target.value); setExamYear(null); }}><option value="" disabled>请选择</option>{targets.map(item => <option value={item.id} key={item.id}>{item.school} · {item.exam_label}{item.id.startsWith('demo-') ? '（演示）' : ''}</option>)}</select></div><button className={`star ${star ? 'active' : ''}`} onClick={() => { setStar(!star); setSelectedQuestion(null); }} aria-label="择校信息中心" title="择校信息中心">★</button></div><div className="platform-title">经济学考研学习平台</div><div className="header-trailing"><span className="demo-badge">本地演示版</span></div></header>
    <div className="shell"><aside className="rail" aria-label="学习导航"><div className="rail-section">学习工作台</div>{NAV.map((item, index) => <button key={item} className={`rail-item ${nav === item && !star ? 'active' : ''}`} onClick={() => { setNav(item); setStar(false); setSelectedQuestion(null); }}><span className="rail-index">{String(index + 1).padStart(2, '0')}</span>{item}</button>)}</aside>
      <aside className="catalog"><div className="catalog-head"><span>{star ? '目标考试信息' : nav === '真题' ? `按${yearMode}浏览` : nav === '知识地图' ? '知识目录' : '工作目录'}</span><small>{target?.school || '选择目标'}</small></div>
        {star ? <><button className="catalog-item selected">目标院校</button><button className="catalog-item">信息须知</button></>
          : nav === '知识地图' ? targetTopics.map(item => <button className={`catalog-item ${currentTopicId === item.id ? 'selected' : ''}`} key={item.id} onClick={() => setSelectedTopic(item.id)}><small>{item.subject} / {item.module}</small>{item.name}</button>)
          : nav === '真题' ? <><button className={`catalog-item ${yearMode === '年份' ? 'selected' : ''}`} onClick={() => setYearMode('年份')}>按年份</button><button className={`catalog-item ${yearMode === '知识点' ? 'selected' : ''}`} onClick={() => setYearMode('知识点')}>按知识点</button>{yearMode === '年份' && <><button className={`catalog-item ${examYear === null ? 'selected' : ''}`} onClick={() => setExamYear(null)}>全部年份</button>{years.map(year => <button key={year} className={`catalog-item ${examYear === year ? 'selected' : ''}`} onClick={() => setExamYear(year)}>{year} 年</button>)}</>}</>
          : nav === '精品练习' ? <><button className="catalog-item selected">全部练习</button>{targetTopics.map(item => <button className="catalog-item" key={item.id} onClick={() => { setSelectedTopic(item.id); setNav('知识地图'); }}>{item.name}</button>)}</>
          : <button className="catalog-item selected">{nav === '今日学习' ? '今日总览' : nav === '学习统计' ? '学习总览' : nav === 'AI练习' ? '能力规划' : nav === '在线论坛' ? '社区动态' : '账户信息'}</button>}
        <div className="catalog-foot">内容随目标院校切换<br />学习记录会保留</div></aside>
      <main className="workspace">{error && <div className="error" role="alert">{error}<button onClick={() => void refresh()}>重试</button></div>}
        {loading ? <p>正在载入工作台…</p> : question ? <section className="content-sheet"><button className="back" onClick={() => setSelectedQuestion(null)}>← 返回列表</button><div className="sheet-label">{question.catalog_number} / {question.source_name}</div><h1>题目训练</h1><div className="meta-row"><span>{topics.find(item => item.id === question.topic_id)?.name}</span><span>{question.question_type}</span><span>难度 {question.difficulty}/5</span></div><p className="stem">{question.stem}</p><label className="field-label" htmlFor="answer">我的作答</label><textarea id="answer" rows={6} placeholder="写下你的解题过程或回答要点" value={answerText} onChange={event => setAnswerText(event.target.value)} /><div className="action-row"><button className="primary" onClick={() => setReveal(true)} disabled={!answerText.trim()}>查看参考答案</button><span className="hint">主观题由你自评。</span></div>{reveal && <div className="answer-panel"><h2>参考答案</h2><p>{question.answer}</p><h3>解析</h3><p>{question.analysis}</p><div className="rating"><b>对照答案后，你掌握了多少？</b>{[0, 1, 2, 3].map(value => <button className={rating === value ? 'chosen' : ''} key={value} onClick={() => setRating(value)}>{['未掌握', '部分理解', '基本掌握', '能够独立完成'][value]}</button>)}</div><button className="primary" disabled={rating === null} onClick={() => void saveAttempt()}>保存作答与自评</button></div>}</section>
          : star ? <section><div className="page-heading"><div><h1>择校信息中心</h1><p>查看当前考试筛选标签与备注。</p></div></div><div className="notice-box"><b>{target?.school || '请选择目标院校'}</b><p>{target?.exam_label}</p><p>{target?.note || '暂无备注'}</p><p className="data-note">请以院校官方最新招生公告为准。</p></div></section>
          : nav === '今日学习' ? <section><div className="page-heading"><div><h1>今天，从一道题开始</h1><p>{target?.school} · {target?.exam_label} · {target?.target_year}</p></div><span className="status-pill">演示学习内容</span></div><div className="hero-strip"><div><span>今日学习</span><h2>把知识点、练习和复盘连起来</h2><p>当前已完成 {stats?.attempt_count ?? 0} 次作答。选择一道题，记录你的解题过程与自评。</p><button className="primary" disabled={!focus} onClick={() => focus && openQuestion(focus.id)}>继续练习 →</button></div><div className="hero-aside"><small>当前目标</small><strong>{target?.target_year || '—'}</strong><small>考研届次</small></div></div><div className="section-heading"><h2>已发布练习</h2><span>{visible.length} 道题目</span></div>{questionRows(visible.filter(item => item.source_type === 'CURATED_EXERCISE'))}<p className="data-note">演示题已明确标注；考试标签备注不是官方招生信息，真题请以来源核验状态为准。</p></section>
          : nav === '知识地图' ? knowledgeSection()
          : nav === '真题' ? <section><div className="page-heading"><div><h1>目标院校真题</h1><p>{target?.school} · {target?.exam_label}</p></div><span className="status-pill">按{yearMode}浏览</span></div>{yearMode === '知识点' ? <>{targetTopics.map(item => { const items = past.filter(q => q.topic_id === item.id); return items.length ? <div key={item.id}><div className="section-heading"><h2>{item.name}</h2><span>{items.length} 题</span></div>{questionRows(items)}</div> : null; })}{!past.length && <div className="empty">尚无已核验发布的真题。</div>}</> : questionRows(past)}<p className="data-note">仅展示来源经人工核验并通过审核的题目。</p></section>
          : nav === '兄弟院校' ? <section><div className="page-heading"><div><h1>兄弟院校</h1><p>补充难度相近或稍难的院校真题。</p></div></div>{questionRows(visible.filter(item => item.source_type === 'RELATED_PAST_EXAM'))}</section>
          : nav === '精品练习' ? <section><div className="page-heading"><div><h1>精品练习</h1><p>按知识点与题型组织练习。</p></div><span className="status-pill">{visible.filter(item => item.source_type === 'CURATED_EXERCISE').length} 道已审核题目</span></div>{questionRows(visible.filter(item => item.source_type === 'CURATED_EXERCISE'))}</section>
          : nav === '学习统计' ? <section><div className="page-heading"><div><h1>学习统计</h1><p>从真实作答记录观察知识点表现。</p></div><span className="status-pill">本地演示用户</span></div><div className="stats-summary"><div><span>有效作答</span><strong>{stats?.attempt_count ?? 0}</strong><small>次提交与自评</small></div><div><span>已练知识点</span><strong>{stats?.topic_stats.length ?? 0}</strong><small>个知识节点</small></div></div><div className="section-heading"><h2>按知识点查看</h2><span>自评均值 / 3</span></div>{stats?.topic_stats.length ? stats.topic_stats.map(item => <button className="stat-row" key={item.topic_id} onClick={() => { setSelectedTopic(item.topic_id); setNav('知识地图'); }}><span><b>{item.name}</b><small>{item.attempts} 次作答</small></span><strong>{item.average_self_rating.toFixed(1)}</strong><span>复习知识点 →</span></button>) : <div className="empty">完成练习并保存自评后，这里会出现学习记录。</div>}<p className="data-note">{stats?.method}</p></section>
          : nav === 'AI练习' ? <section><div className="page-heading"><div><h1>AI 练习</h1><p>组卷、答疑与错题分析将依赖可靠的题库和学习记录。</p></div></div><div className="empty-feature"><h2>功能建设中</h2><p>当前先支持结构化练习与自评。AI 接入将在模型选型和内容审核流程确定后上线。</p></div></section>
          : nav === '在线论坛' ? <section><div className="page-heading"><div><h1>在线论坛</h1><p>学习打卡与知识点交流将在后续版本开放。</p></div></div><div className="empty-feature"><h2>社区空间已预留</h2><p>帖子、图片上传、回答与内容审核流程尚未开发。</p></div></section>
          : <section><div className="page-heading"><div><h1>设置</h1><p>管理学习目标与本地演示环境。</p></div></div><div className="panel"><h2>目标院校</h2><p>切换目标后，历史作答仍会保留。</p><select aria-label="设置目标院校" value={targetId} onChange={event => setTargetId(event.target.value)}>{targets.map(item => <option key={item.id} value={item.id}>{item.school} · {item.exam_label}</option>)}</select><p className="data-note">当前无正式账号体系，记录属于同一个本地演示用户。</p></div></section>}
      </main></div>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
