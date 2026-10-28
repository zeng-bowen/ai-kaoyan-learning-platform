import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import './admin.css';

type Target = { id: string; school: string; college: string; major: string; exam_subject: string; exam_code: string; target_year: number; source_url: string; source_checked_at: string | null; verified: number };
type Topic = { id: string; subject: string; module: string; name: string; summary: string; source_name: string; source_url: string; review_status: string };
type Question = QuestionDraft & { review_status: string; reviewed_at: string | null; review_note: string };
type QuestionDraft = { id: string; catalog_number: string; target_id: string; topic_id: string; source_type: string; source_name: string; source_url: string; source_verified: boolean; exam_year: number | null; question_type: string; difficulty: number; stem: string; answer: string; analysis: string; intake_id: string | null };
type Intake = { id: string; original_name: string; status: string; created_at: string };
type Metrics = { active_training_sessions: number; attempt_count: number; published_questions: number; correct_rate: number | null; difficulty_stats: { difficulty: number; attempts: number; average_self_rating: number }[]; method: string };
type Section = '总览' | '院校与考试' | '知识目录' | '题目中心' | '识图录题';
const API = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';
const emptyTarget = (): Target => ({ id: '', school: '', college: '', major: '', exam_subject: '', exam_code: '', target_year: new Date().getFullYear() + 2, source_url: '', source_checked_at: null, verified: 0 });
const emptyTopic = (): Topic => ({ id: '', subject: '', module: '', name: '', summary: '', source_name: '', source_url: '', review_status: 'DRAFT' });
const emptyQuestion = (): QuestionDraft => ({ id: '', catalog_number: '', target_id: '', topic_id: '', source_type: 'CURATED_EXERCISE', source_name: '', source_url: '', source_verified: false, exam_year: null, question_type: '简答题', difficulty: 2, stem: '', answer: '', analysis: '', intake_id: null });
const SOURCE_LABELS: Record<string, string> = { TARGET_PAST_EXAM: '目标院校真题', RELATED_PAST_EXAM: '兄弟院校真题', CURATED_EXERCISE: '精品练习', AI_GENERATED: 'AI 草稿' };

function App() {
  const [section, setSection] = useState<Section>('总览');
  const [targets, setTargets] = useState<Target[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [intakes, setIntakes] = useState<Intake[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [targetDraft, setTargetDraft] = useState<Target>(emptyTarget());
  const [topicDraft, setTopicDraft] = useState<Topic>(emptyTopic());
  const [questionDraft, setQuestionDraft] = useState<QuestionDraft>(emptyQuestion());
  const [editingTarget, setEditingTarget] = useState(false);
  const [editingTopic, setEditingTopic] = useState(false);
  const [editingQuestion, setEditingQuestion] = useState(false);
  const [filters, setFilters] = useState({ target_id: '', exam_year: '', topic_id: '', source_type: '', review_status: '', search: '' });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageName, setImageName] = useState('');
  const versions = useRef<{ content: number; activity: number } | null>(null);

  async function request<T>(path: string, method = 'GET', body?: object): Promise<T> {
    const response = await fetch(API + path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
    if (!response.ok) { const detail = await response.json().catch(() => null); throw new Error(detail?.detail || `请求失败（${response.status}）`); }
    return response.json();
  }
  async function refresh() {
    const [nextTargets, nextTopics, nextQuestions, nextIntakes, nextMetrics] = await Promise.all([
      request<Target[]>('/api/targets'), request<Topic[]>('/api/admin/topics'),
      request<Question[]>('/api/admin/questions'), request<Intake[]>('/api/admin/intakes'),
      request<Metrics>('/api/admin/stats'),
    ]);
    setTargets(nextTargets); setTopics(nextTopics); setQuestions(nextQuestions); setIntakes(nextIntakes); setMetrics(nextMetrics); setError('');
  }
  useEffect(() => {
    void refresh().catch(cause => setError((cause as Error).message));
  }, []);
  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(API + '/api/versions');
        const current = await response.json() as { content: number; activity: number };
        if (versions.current && (current.content !== versions.current.content || current.activity !== versions.current.activity)) void refresh();
        versions.current = current;
      } catch { /* Manual retry remains available. */ }
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  async function run(action: () => Promise<unknown>, success: string): Promise<boolean> {
    setBusy(true); setError(''); setNotice('');
    try { await action(); await refresh(); setNotice(success); return true; }
    catch (cause) { setError((cause as Error).message); return false; }
    finally { setBusy(false); }
  }
  function selectTarget(item: Target) { setTargetDraft({ ...item }); setEditingTarget(true); setSection('院校与考试'); }
  function selectTopic(item: Topic) { setTopicDraft({ ...item }); setEditingTopic(true); setSection('知识目录'); }
  function selectQuestion(item: Question) { const { review_status: _status, reviewed_at: _reviewed, review_note: _note, ...draft } = item; setQuestionDraft(draft); setEditingQuestion(true); setSection('题目中心'); }
  function newQuestion(intakeId: string | null = null) { setQuestionDraft({ ...emptyQuestion(), target_id: targets[0]?.id || '', topic_id: topics[0]?.id || '', intake_id: intakeId }); setEditingQuestion(false); setSection('题目中心'); }
  async function saveTarget() {
    const method = editingTarget ? 'PUT' : 'POST';
    const path = editingTarget ? `/api/admin/targets/${encodeURIComponent(targetDraft.id)}` : '/api/admin/targets';
    if (await run(() => request(path, method, targetDraft), editingTarget ? '院校信息已保存，核验状态已重置。' : '院校已添加，用户端将自动更新。')) { setTargetDraft(emptyTarget()); setEditingTarget(false); }
  }
  async function saveTopic() {
    const path = editingTopic ? `/api/admin/topics/${encodeURIComponent(topicDraft.id)}` : '/api/admin/topics';
    if (await run(() => request(path, editingTopic ? 'PUT' : 'POST', topicDraft), '知识点已保存为待审核草稿。')) { setTopicDraft(emptyTopic()); setEditingTopic(false); }
  }
  async function saveQuestion() {
    const data = { ...questionDraft, id: questionDraft.id || `q-${crypto.randomUUID()}`, catalog_number: questionDraft.catalog_number.trim() };
    const path = editingQuestion ? `/api/admin/questions/${encodeURIComponent(questionDraft.id)}` : '/api/admin/questions';
    if (await run(() => request(path, editingQuestion ? 'PUT' : 'POST', data), '题目已保存为草稿，请在列表中人工审核。')) { setQuestionDraft(emptyQuestion()); setEditingQuestion(false); }
  }
  async function review(item: Question, decision: 'APPROVED' | 'REJECTED') {
    if (decision === 'APPROVED' && !window.confirm(`确认已人工核对 ${item.catalog_number} 的来源、知识点、答案和解析？通过后用户端可见。`)) return;
    const note = decision === 'REJECTED' ? window.prompt('请填写退回原因（可选）') : '';
    if (note === null) return;
    await run(() => request(`/api/admin/questions/${encodeURIComponent(item.id)}/review`, 'POST', { decision, note }), decision === 'APPROVED' ? '审核已通过，用户端将自动更新。' : '题目已退回。');
  }
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true); setError(''); setNotice('');
    try {
      for (const file of Array.from(files)) {
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 8 * 1024 * 1024) throw new Error(`${file.name}：仅支持 8 MB 内的 PNG、JPEG、WebP 图片。`);
        const base64 = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error('图片读取失败')); reader.readAsDataURL(file); });
        await request('/api/admin/intakes', 'POST', { file_name: file.name, mime_type: file.type, base64_data: base64 });
      }
      await refresh(); setNotice(`${files.length} 张图片已进入待识别队列；模型尚未接入，可逐张人工录题。`);
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  }
  async function showImage(item: Intake) {
    try {
      const response = await fetch(API + `/api/admin/intakes/${item.id}/image`);
      if (!response.ok) throw new Error('图片读取失败');
      const url = URL.createObjectURL(await response.blob());
      if (imageUrl) URL.revokeObjectURL(imageUrl);
      setImageUrl(url); setImageName(item.original_name);
    } catch (cause) { setError((cause as Error).message); }
  }
  const matches = questions.filter(item => (!filters.target_id || item.target_id === filters.target_id) && (!filters.exam_year || item.exam_year === Number(filters.exam_year)) && (!filters.topic_id || item.topic_id === filters.topic_id) && (!filters.source_type || item.source_type === filters.source_type) && (!filters.review_status || item.review_status === filters.review_status) && (!filters.search || `${item.catalog_number} ${item.id} ${item.stem}`.toLowerCase().includes(filters.search.toLowerCase())));
  const years = [...new Set(questions.map(item => item.exam_year).filter((value): value is number => value !== null))].sort((a, b) => b - a);

  function topicSection() {
    if (section !== '知识目录') return null;
    return <section><div className="admin-heading"><div><h1>知识目录</h1><p>更新知识点后先核验来源，再发布到用户端。</p></div><button className="primary" onClick={() => { setTopicDraft(emptyTopic()); setEditingTopic(false); }}>新增知识点</button></div><div className="admin-columns"><div className="admin-panel"><h2>{editingTopic ? '编辑知识点' : '新增知识点'}</h2><div className="form-grid"><label>知识点 ID<input disabled={editingTopic} value={topicDraft.id} onChange={event => setTopicDraft({ ...topicDraft, id: event.target.value })} /></label><label>科目<input value={topicDraft.subject} onChange={event => setTopicDraft({ ...topicDraft, subject: event.target.value })} /></label><label>模块<input value={topicDraft.module} onChange={event => setTopicDraft({ ...topicDraft, module: event.target.value })} /></label><label>知识点名称<input value={topicDraft.name} onChange={event => setTopicDraft({ ...topicDraft, name: event.target.value })} /></label><label>来源名称<input value={topicDraft.source_name} onChange={event => setTopicDraft({ ...topicDraft, source_name: event.target.value })} /></label><label>来源链接（HTTPS）<input type="url" value={topicDraft.source_url} onChange={event => setTopicDraft({ ...topicDraft, source_url: event.target.value })} /></label></div><label>知识概要<textarea rows={6} value={topicDraft.summary} onChange={event => setTopicDraft({ ...topicDraft, summary: event.target.value })} /></label><div className="admin-actions"><button className="primary" disabled={busy || !topicDraft.id || !topicDraft.subject || !topicDraft.module || !topicDraft.name || !topicDraft.summary || !topicDraft.source_name} onClick={() => void saveTopic()}>{editingTopic ? '保存修改并重新审核' : '保存为待审核草稿'}</button>{editingTopic && <button onClick={() => { setTopicDraft(emptyTopic()); setEditingTopic(false); }}>取消编辑</button>}</div></div><div className="admin-panel"><h2>知识点 · {topics.length}</h2><div className="admin-list">{topics.map(item => <div key={item.id}><div><strong>{item.name}</strong><small>{item.subject} / {item.module} · {item.review_status === 'APPROVED' ? '已发布' : '待审核'}</small><small>{item.source_name}</small></div><div className="admin-actions"><button onClick={() => selectTopic(item)}>编辑</button>{item.review_status !== 'APPROVED' && <button onClick={() => { if (window.confirm(`确认已核对“${item.name}”的来源与内容？`)) void run(() => request(`/api/admin/topics/${item.id}/approve`, 'POST'), '知识点已发布，用户端将自动更新。'); }}>审核发布</button>}</div></div>)}</div></div></div></section>;
  }

  return <div className="admin-app"><header className="admin-topbar"><div><strong>经济学考研 · 内容管理</strong><span>本地管理工作台</span></div><div><span className="demo-badge">仅限本机开发</span></div></header><div className="admin-shell"><nav className="admin-nav" aria-label="管理导航"><h2>工作区</h2>{(['总览', '院校与考试', '知识目录', '题目中心', '识图录题'] as Section[]).map(item => <button key={item} className={section === item ? 'current' : ''} onClick={() => setSection(item)}>{item}</button>)}<p>题目发布以人工审核为准。数据每 2 秒检查更新。</p></nav><main className="admin-main">{error && <div className="error" role="alert">{error}<button onClick={() => void refresh()}>重试</button></div>}{notice && <div className="admin-notice" role="status">{notice}</div>}{topicSection()}
    {section === '总览' && <section><div className="admin-heading"><div><h1>平台总览</h1><p>查看当前内容发布与学习行为。统计基于本地演示数据。</p></div><button className="quiet-button" onClick={() => void refresh()}>刷新数据</button></div><div className="admin-metrics"><div><span>正在做题</span><strong>{metrics?.active_training_sessions ?? 0}</strong><small>近 30 秒内的活跃会话</small></div><div><span>做题总量</span><strong>{metrics?.attempt_count ?? 0}</strong><small>累计提交次数</small></div><div><span>已发布题目</span><strong>{metrics?.published_questions ?? 0}</strong><small>用户端可见</small></div><div><span>题目正确率</span><strong>{metrics?.correct_rate === null ? '—' : `${metrics?.correct_rate}%`}</strong><small>待客观判分能力上线</small></div></div><div className="admin-panel"><h2>难度表现</h2>{metrics?.difficulty_stats.length ? <div className="admin-table-wrap"><table><thead><tr><th>难度</th><th>作答次数</th><th>自评均值 / 3</th></tr></thead><tbody>{metrics.difficulty_stats.map(item => <tr key={item.difficulty}><td>{item.difficulty} / 5</td><td>{item.attempts}</td><td>{item.average_self_rating.toFixed(2)}</td></tr>)}</tbody></table></div> : <p>尚无作答记录，用户完成练习后这里会出现统计。</p>}<p className="data-note">{metrics?.method}</p></div><div className="admin-panel"><h2>待处理内容</h2><p>{questions.filter(item => item.review_status === 'DRAFT').length} 道待审核题目 · {intakes.length} 张待识别图片</p><div className="admin-actions"><button onClick={() => setSection('题目中心')}>去审核题目</button><button onClick={() => setSection('识图录题')}>查看图片队列</button></div></div></section>}
    {section === '院校与考试' && <section><div className="admin-heading"><div><h1>院校与考试</h1><p>维护目标院校、考试科目和来源；修改后需重新核验。</p></div><button className="primary" onClick={() => { setTargetDraft(emptyTarget()); setEditingTarget(false); }}>新增院校</button></div><div className="admin-columns"><div className="admin-panel"><h2>{editingTarget ? '编辑院校信息' : '新增院校信息'}</h2><div className="form-grid"><label>配置 ID<input disabled={editingTarget} value={targetDraft.id} onChange={event => setTargetDraft({ ...targetDraft, id: event.target.value })} placeholder="如 school-exam-2028" /></label><label>目标年份<input type="number" value={targetDraft.target_year} onChange={event => setTargetDraft({ ...targetDraft, target_year: Number(event.target.value) })} /></label><label>院校<input value={targetDraft.school} onChange={event => setTargetDraft({ ...targetDraft, school: event.target.value })} /></label><label>学院 / 培养单位<input value={targetDraft.college} onChange={event => setTargetDraft({ ...targetDraft, college: event.target.value })} /></label><label>专业<input value={targetDraft.major} onChange={event => setTargetDraft({ ...targetDraft, major: event.target.value })} /></label><label>考试科目<input value={targetDraft.exam_subject} onChange={event => setTargetDraft({ ...targetDraft, exam_subject: event.target.value })} /></label><label>考试代码<input value={targetDraft.exam_code} onChange={event => setTargetDraft({ ...targetDraft, exam_code: event.target.value })} /></label></div><label>信息来源链接（HTTPS）<input type="url" value={targetDraft.source_url} onChange={event => setTargetDraft({ ...targetDraft, source_url: event.target.value })} /></label><div className="admin-actions"><button className="primary" disabled={busy || !targetDraft.id || !targetDraft.school || !targetDraft.major || !targetDraft.exam_subject} onClick={() => void saveTarget()}>{editingTarget ? '保存修改' : '保存院校'}</button>{editingTarget && <button onClick={() => { setTargetDraft(emptyTarget()); setEditingTarget(false); }}>取消编辑</button>}</div></div><div className="admin-panel"><h2>院校资源 · {targets.length}</h2><div className="admin-list">{targets.map(item => <div key={item.id}><div><strong>{item.school} · {item.target_year}</strong><small>{item.major} · {item.exam_code || item.exam_subject}</small><small>{item.verified ? '来源已核验' : '待核验'}{item.id.startsWith('demo-') ? ' · 演示配置' : ''}</small></div><div className="admin-actions"><button onClick={() => selectTarget(item)}>编辑</button>{!item.verified && item.source_url && <button onClick={() => { if (window.confirm('确认已人工核对来源中的院校、专业、科目和年份？')) void run(() => request(`/api/admin/targets/${item.id}/verify`, 'POST'), '院校来源已核验。'); }}>人工核验</button>}</div></div>)}</div></div></div></section>}
    {section === '题目中心' && <section><div className="admin-heading"><div><h1>题目中心</h1><p>按院校、年份或知识点筛选；所有修改回到待审核状态。</p></div><button className="primary" onClick={() => newQuestion()}>新增题目</button></div><div className="admin-panel"><div className="admin-filters"><label>院校<select value={filters.target_id} onChange={event => setFilters({ ...filters, target_id: event.target.value })}><option value="">全部院校</option>{targets.map(item => <option key={item.id} value={item.id}>{item.school} · {item.target_year}</option>)}</select></label><label>真题年份<select value={filters.exam_year} onChange={event => setFilters({ ...filters, exam_year: event.target.value })}><option value="">全部年份</option>{years.map(year => <option key={year} value={year}>{year}</option>)}</select></label><label>知识点<select value={filters.topic_id} onChange={event => setFilters({ ...filters, topic_id: event.target.value })}><option value="">全部知识点</option>{topics.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>栏目<select value={filters.source_type} onChange={event => setFilters({ ...filters, source_type: event.target.value })}><option value="">全部栏目</option>{Object.entries(SOURCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>审核状态<select value={filters.review_status} onChange={event => setFilters({ ...filters, review_status: event.target.value })}><option value="">全部状态</option><option value="DRAFT">待审核</option><option value="APPROVED">已发布</option><option value="REJECTED">已退回</option></select></label><label>编号 / 题干<input value={filters.search} onChange={event => setFilters({ ...filters, search: event.target.value })} placeholder="搜索题目" /></label></div><div className="admin-table-wrap"><table><thead><tr><th>管理编号</th><th>题目 / 来源</th><th>院校 / 年份</th><th>知识点</th><th>状态</th><th>操作</th></tr></thead><tbody>{matches.map(item => <tr key={item.id}><td className="code-cell">{item.catalog_number}</td><td><strong>{item.stem}</strong><small>{SOURCE_LABELS[item.source_type]} · {item.source_name}</small></td><td>{targets.find(t => t.id === item.target_id)?.school || item.target_id}{item.exam_year ? ` · ${item.exam_year}` : ''}</td><td>{topics.find(t => t.id === item.topic_id)?.name || item.topic_id}</td><td><span className={`review-state ${item.review_status.toLowerCase()}`}>{item.review_status === 'APPROVED' ? '已发布' : item.review_status === 'REJECTED' ? '已退回' : '待审核'}</span></td><td><div className="admin-actions"><button onClick={() => selectQuestion(item)}>编辑</button>{item.review_status !== 'APPROVED' && <button onClick={() => void review(item, 'APPROVED')}>审核发布</button>}{item.review_status === 'DRAFT' && <button onClick={() => void review(item, 'REJECTED')}>退回</button>}</div></td></tr>)}</tbody></table>{!matches.length && <p className="admin-empty">当前筛选条件下没有题目。</p>}</div></div><div className="admin-panel" id="question-editor"><h2>{editingQuestion ? `编辑题目 · ${questionDraft.catalog_number}` : '录入新题目'}</h2><p>管理编号可自定义；留空会自动分配。截图录题可先保存图片，再关联到草稿。</p><div className="form-grid"><label>题目 ID<input disabled={editingQuestion} value={questionDraft.id} placeholder="留空自动生成" onChange={event => setQuestionDraft({ ...questionDraft, id: event.target.value })} /></label><label>管理编号<input value={questionDraft.catalog_number} placeholder="如 Q-000125" onChange={event => setQuestionDraft({ ...questionDraft, catalog_number: event.target.value })} /></label><label>关联院校<select value={questionDraft.target_id} onChange={event => setQuestionDraft({ ...questionDraft, target_id: event.target.value })}><option value="">请选择院校</option>{targets.map(item => <option key={item.id} value={item.id}>{item.school} · {item.target_year}</option>)}</select></label><label>知识点<select value={questionDraft.topic_id} onChange={event => setQuestionDraft({ ...questionDraft, topic_id: event.target.value })}><option value="">请选择知识点</option>{topics.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>题目栏目<select value={questionDraft.source_type} onChange={event => setQuestionDraft({ ...questionDraft, source_type: event.target.value })}>{Object.entries(SOURCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>题型<input value={questionDraft.question_type} onChange={event => setQuestionDraft({ ...questionDraft, question_type: event.target.value })} /></label><label>难度（1–5）<input type="number" min="1" max="5" value={questionDraft.difficulty} onChange={event => setQuestionDraft({ ...questionDraft, difficulty: Number(event.target.value) })} /></label><label>真题年份<input type="number" min="1990" max="2100" value={questionDraft.exam_year ?? ''} onChange={event => setQuestionDraft({ ...questionDraft, exam_year: event.target.value ? Number(event.target.value) : null })} /></label><label>来源名称<input value={questionDraft.source_name} onChange={event => setQuestionDraft({ ...questionDraft, source_name: event.target.value })} placeholder="如平台原创、试卷名称" /></label><label>来源链接（HTTPS）<input type="url" value={questionDraft.source_url} onChange={event => setQuestionDraft({ ...questionDraft, source_url: event.target.value })} /></label><label>关联截图<select value={questionDraft.intake_id || ''} onChange={event => setQuestionDraft({ ...questionDraft, intake_id: event.target.value || null })}><option value="">无截图</option>{intakes.map(item => <option key={item.id} value={item.id}>{item.original_name}</option>)}</select></label><label className="check-label"><input type="checkbox" checked={questionDraft.source_verified} onChange={event => setQuestionDraft({ ...questionDraft, source_verified: event.target.checked })} />已人工核对来源与图片</label></div><label>题干<textarea rows={4} value={questionDraft.stem} onChange={event => setQuestionDraft({ ...questionDraft, stem: event.target.value })} /></label><label>参考答案<textarea rows={4} value={questionDraft.answer} onChange={event => setQuestionDraft({ ...questionDraft, answer: event.target.value })} /></label><label>解析<textarea rows={4} value={questionDraft.analysis} onChange={event => setQuestionDraft({ ...questionDraft, analysis: event.target.value })} /></label><div className="admin-actions"><button className="primary" disabled={busy || !questionDraft.target_id || !questionDraft.topic_id || !questionDraft.source_name || !questionDraft.stem || !questionDraft.answer || !questionDraft.analysis} onClick={() => void saveQuestion()}>{editingQuestion ? '保存修改并重新审核' : '保存为待审核草稿'}</button>{editingQuestion && <button onClick={() => newQuestion()}>取消编辑</button>}</div></div></section>}
    {section === '识图录题' && <section><div className="admin-heading"><div><h1>识图录题</h1><p>批量上传题目截图，保留原图供人工录入与审核。</p></div></div><div className="admin-panel"><h2>上传截图</h2><p>支持 PNG、JPEG、WebP，每张不超过 8 MB。上传后只进入管理员待处理队列，不会自动发布。</p><label className="upload-control">选择图片<input type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={busy} onChange={event => { void upload(event.target.files); event.target.value = ''; }} /></label><p className="data-note">国产大模型识别接口已预留，目前未配置模型。后续可自动草拟题干、科目、难度和参考答案，仍需人工审核后发布。</p></div><div className="admin-panel"><h2>图片队列 · {intakes.length}</h2><div className="admin-list">{intakes.map(item => <div key={item.id}><div><strong>{item.original_name}</strong><small>{new Date(item.created_at).toLocaleString('zh-CN')} · 待接入模型</small></div><div className="admin-actions"><button onClick={() => void showImage(item)}>查看原图</button><button onClick={() => newQuestion(item.id)}>人工录题</button></div></div>)}{!intakes.length && <p className="admin-empty">上传截图后会在这里逐张列出。</p>}</div></div>{imageUrl && <div className="admin-image-preview"><div><strong>{imageName}</strong><button onClick={() => { URL.revokeObjectURL(imageUrl); setImageUrl(null); }}>关闭</button></div><img src={imageUrl} alt={`上传题目截图：${imageName}`} /></div>}</section>}
  </main></div></div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
