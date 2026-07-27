import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  Database,
  Download,
  FileText,
  Play,
  RefreshCw,
  Settings,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import "./style.css";
import "./crud.css";

type Article = {
  id: number;
  title: string;
  title_options: string[];
  content: any;
  status: string;
  risk_notes: string[];
  originality_notes: string;
  updated_at: string;
};
type Run = {
  id: number;
  name: string;
  status: string;
  details: any;
  started_at: string;
  finished_at?: string;
};
const API = "/api";
const tables = [
  "sources",
  "feed_items",
  "event_clusters",
  "articles",
  "article_versions",
  "citations",
  "assets",
  "workflow_runs",
];
const tableNames: any = {
  sources: "信息源",
  feed_items: "原始资讯",
  event_clusters: "聚类事件",
  articles: "候选稿",
  article_versions: "稿件版本",
  citations: "事实引用",
  assets: "图片资源",
  workflow_runs: "运行记录",
};
const fieldNames: any = {
  id: "编号",
  name: "名称",
  kind: "类型",
  url: "链接",
  official: "官方来源",
  enabled: "启用",
  health: "健康状态",
  last_checked_at: "最后检查时间",
  source_id: "信息源编号",
  title: "标题",
  summary: "摘要",
  author: "作者",
  normalized_url: "规范化链接",
  published_at: "发布时间",
  collected_at: "采集时间",
  raw: "原始数据",
  event_id: "事件编号",
  canonical_title: "标准标题",
  topic: "主题",
  primary_item_id: "主资讯编号",
  score: "评分",
  needs_review: "需要人工核验",
  analysis: "分析结果",
  created_at: "创建时间",
  updated_at: "更新时间",
  title_options: "备选标题",
  content: "文章内容",
  status: "状态",
  risk_notes: "风险提示",
  originality_notes: "原创说明",
  article_id: "文章编号",
  version: "版本号",
  snapshot: "版本快照",
  feed_item_id: "资讯编号",
  claim: "事实声明",
  path: "文件路径",
  metadata_json: "资源信息",
  details: "执行详情",
  started_at: "开始时间",
  finished_at: "完成时间",
  idempotency_key: "幂等键",
  mode: "模式",
  response: "响应结果",
};
const workflows = [
  ["01", "资讯到候选稿", "依次完成资讯采集、当天评分和最多5篇候选稿生成"],
  ["04", "公众号成品生成", "为已批准稿生成网页、Markdown、封面和章节配图"],
  ["05", "失败检查", "查看需要人工处理的失败任务"],
];
function shanghaiDate(value?: string) {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(
    value ? new Date(value) : new Date(),
  );
}

function Scoreboard({ run }: { run?: Run }) {
  const [order, setOrder] = useState<"desc" | "asc">("desc");
  if (!run || !["success", "partial_success"].includes(run.status)) return null;
  if (run.details?.date !== shanghaiDate())
    return (
      <p className="muted">今天尚未运行工作流 2，昨天的评分结果不会显示。</p>
    );
  const rankings = [...(run.details?.rankings || [])].sort((a: any, b: any) =>
    order === "desc"
      ? Number(b.score) - Number(a.score)
      : Number(a.score) - Number(b.score),
  );
  return (
    <div className="scoreboard">
      <div className="scorehead">
        <h3>今日评分排名</h3>
        <div className="scoretools">
          <span>
            {rankings.length} 个项目 · {run.details.date}
          </span>
          <select
            aria-label="评分排序"
            value={order}
            onChange={(e) => setOrder(e.target.value as "desc" | "asc")}
          >
            <option value="desc">评分降序</option>
            <option value="asc">评分升序</option>
          </select>
        </div>
      </div>
      {rankings.length ? (
        <table>
          <thead>
            <tr>
              <th>排名</th>
              <th>项目</th>
              <th>主题</th>
              <th>评分</th>
              <th>核验状态</th>
            </tr>
          </thead>
          <tbody>
            {rankings.map((x: any, index: number) => (
              <tr key={x.event_id}>
                <td>#{index + 1}</td>
                <td>{x.title}</td>
                <td>{x.topic}</td>
                <td>
                  <b>{Number(x.score).toFixed(1)}</b>
                </td>
                <td>{x.needs_review ? "需人工核验" : "可用"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">今天暂时没有可评分的资讯。</p>
      )}
    </div>
  );
}

function PublicationResults({ run }: { run?: Run }) {
  const publications = run?.details?.publications || [];
  if (!run || run.status === "running") return null;
  if (!publications.length)
    return (
      <p className="muted">
        {run.status === "failed"
          ? "生成失败，请查看执行详情。"
          : "没有已批准的稿件可生成。"}
      </p>
    );
  return (
    <div className="publicationresults">
      <h3>已生成公众号素材</h3>
      {publications.map((item: any) => (
        <div className="publicationitem" key={item.preview_url}>
          <b>{item.title}</b>
          <div className="publicationlinks">
            <a href={item.preview_url} target="_blank" rel="noreferrer">
              打开网页
            </a>
            {item.html_url && <a href={item.html_url} download>下载 HTML</a>}
            {item.markdown_url && <a href={item.markdown_url} download>下载 Markdown</a>}
            {item.cover_url && <a href={item.cover_url} download>下载封面</a>}
            {item.bundle_url && <a className="bundlelink" href={item.bundle_url} download>下载完整素材包</a>}
          </div>
        </div>
      ))}
    </div>
  );
}

function DisableCoverControls() {
  useEffect(() => {
    document.querySelectorAll<HTMLButtonElement>("button").forEach((button) => {
      if (button.textContent?.includes("生成封面")) {
        button.disabled = true;
        button.title = "封面生成功能已停用";
      }
      if (button.textContent?.includes("导出素材包")) {
        const label = [...button.childNodes].find(
          (node) => node.nodeType === Node.TEXT_NODE,
        );
        if (label) label.textContent = "导出 Markdown";
      }
    });
  });
  return null;
}

function factText(c: any) {
  return (c.fact_summary || c.facts || [])
    .map((x: any) => (typeof x === "string" ? x : x.fact || ""))
    .join("\n");
}
function updateFacts(c: any, text: string) {
  const lines = text.split("\n");
  if (Array.isArray(c.fact_summary)) {
    return {
      ...c,
      fact_summary: lines.map((fact, i) =>
        typeof c.fact_summary[i] === "object"
          ? { ...c.fact_summary[i], fact }
          : { fact },
      ),
    };
  }
  return { ...c, facts: lines };
}
function ArticleSource({ content }: { content: any }) {
  const sources = Array.isArray(content?.sources) ? content.sources : [];
  const source = sources.find((item: any) => item && typeof item === "object");
  const url = String(source?.url || "").trim();
  const label = String(source?.title || (url ? url : "用户上传文件")).trim();
  return (
    <div className="articlesource">
      <span className="sourcebadge">{url ? "网站" : "文件"}</span>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" title={url}>
          {label}
        </a>
      ) : (
        <span>{label}</span>
      )}
    </div>
  );
}
function show(value: any) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object")
    return JSON.stringify(value, (_, v) =>
      typeof v === "string" && v.length > 180 ? v.slice(0, 180) + "…" : v,
    );
  return String(value);
}

function App() {
  const [view, setView] = useState<"articles" | "workflows" | "database">(
    "articles",
  );
  const [articles, setArticles] = useState<Article[]>([]),
    [selected, setSelected] = useState<Article | null>(null),
    [error, setError] = useState("");
  const [runs, setRuns] = useState<Run[]>([]),
    [starting, setStarting] = useState<number | null>(null);
  const [summary, setSummary] = useState<any>({}),
    [table, setTable] = useState("feed_items"),
    [rows, setRows] = useState<any[]>([]);
  const [workflowOne, setWorkflowOne] = useState<any>(null),
    [settingsStatus, setSettingsStatus] = useState("");
  const [newSource, setNewSource] = useState({
    name: "",
    url: "",
    official: false,
  }),
    [sourceStatus, setSourceStatus] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState(""),
    [websiteStatus, setWebsiteStatus] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null),
    [fileStatus, setFileStatus] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showAddSource, setShowAddSource] = useState(false);
  const [showWorkflowSettings, setShowWorkflowSettings] = useState(false);
  const [dbPage, setDbPage] = useState(1),
    [pageSize, setPageSize] = useState(10),
    [totalPages, setTotalPages] = useState(1),
    [totalRows, setTotalRows] = useState(0);
  const [dbScoreOrder, setDbScoreOrder] = useState<"desc" | "asc">("desc");
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({});
  const [editingId, setEditingId] = useState<number | null | undefined>(
      undefined,
    ),
    [editorText, setEditorText] = useState("{}");
  const [dbSchema, setDbSchema] = useState<any[]>([]),
    [newForm, setNewForm] = useState<any>({});
  const headers = {
    "Content-Type": "application/json",
  };
  async function get(path: string, options: any = {}) {
    const r = await fetch(API + path, {
      ...options,
      headers: { ...headers, ...options.headers },
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
  function resizeColumn(
    key: string,
    event: React.PointerEvent<HTMLSpanElement>,
  ) {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth =
      event.currentTarget.parentElement?.getBoundingClientRect().width || 180;
    const move = (moveEvent: PointerEvent) => {
      setColumnWidths((current) => ({
        ...current,
        [key]: Math.max(90, startWidth + moveEvent.clientX - startX),
      }));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }
  async function loadArticles() {
    const x = await get("/articles");
    setArticles(x);
    setSelected((s) => x.find((a: Article) => a.id === s?.id) || x[0] || null);
  }
  async function loadRuns() {
    const all = await get("/runs");
    const today = shanghaiDate();
    setRuns(all.filter((run: Run) => shanghaiDate(run.started_at) === today));
  }
  async function loadWorkflowOne() {
    setWorkflowOne(await get("/workflows/1/settings"));
  }
  async function loadDb(
    chosen = table,
    page = dbPage,
    size = pageSize,
    scoreOrder = dbScoreOrder,
  ) {
    const sorting =
      chosen === "event_clusters"
        ? `&sort_by=score&sort_order=${scoreOrder}`
        : "";
    const [s, r] = await Promise.all([
      get("/database/summary"),
      get(`/database/${chosen}?page=${page}&page_size=${size}${sorting}`),
    ]);
    setSummary(s);
    setRows(r.items);
    setDbPage(r.page);
    setTotalPages(r.pages);
    setTotalRows(r.total);
  }
  async function login() {
    try {
      await Promise.all([
        loadArticles(),
        loadRuns(),
        loadDb(),
        loadWorkflowOne(),
      ]);
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  }
  useEffect(() => {
    login();
  }, []);
  useEffect(() => {
    const id = setInterval(() => {
      if (view === "workflows") loadRuns().catch(() => {});
    }, 3000);
    return () => clearInterval(id);
  }, [view]);
  async function startWorkflow(n: number) {
    try {
      setStarting(n);
      await get(`/workflows/${n}/run`, { method: "POST" });
      await loadRuns();
      setError("");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setStarting(null);
    }
  }
  async function saveWorkflowOne() {
    try {
      setSettingsStatus("保存中…");
      setWorkflowOne(
        await get("/workflows/1/settings", {
          method: "PUT",
          body: JSON.stringify(workflowOne),
        }),
      );
      setSettingsStatus("设置已保存，下次运行生效");
      setShowWorkflowSettings(false);
      setError("");
    } catch (e: any) {
      setSettingsStatus("");
      setError(e.message);
    }
  }
  async function addSource() {
    try {
      setSourceStatus("新增中…");
      await get("/sources", {
        method: "POST",
        body: JSON.stringify(newSource),
      });
      setNewSource({ name: "", url: "", official: false });
      await loadWorkflowOne();
      setShowAddSource(false);
      setSourceStatus("新增成功，下次运行工作流 1 时生效");
      setError("");
    } catch (e: any) {
      setSourceStatus("");
      setError(e.message);
    }
  }
  async function chooseTable(t: string) {
    setTable(t);
    setEditingId(undefined);
    try {
      await loadDb(t, 1, pageSize);
    } catch (e: any) {
      setError(e.message);
    }
  }
  async function beginCreate() {
    try {
      const schema = await get(`/database/${table}/schema`);
      setDbSchema(schema.filter((x: any) => x.editable));
      const initial: any = {};
      schema
        .filter((x: any) => x.editable)
        .forEach((x: any) => {
          initial[x.name] = x.type.includes("boolean")
            ? false
            : x.type.includes("json")
              ? x.name.endsWith("s")
                ? "[]"
                : "{}"
              : "";
        });
      setNewForm(initial);
      setEditingId(null);
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  }
  function beginEdit(row: any) {
    setEditingId(row.id);
    setEditorText(JSON.stringify(row, null, 2));
  }
  async function saveRow() {
    try {
      const body =
        editingId === null
          ? Object.fromEntries(
              Object.entries(newForm).filter(([, v]) => v !== ""),
            )
          : JSON.parse(editorText);
      if (editingId === null)
        await get(`/database/${table}`, {
          method: "POST",
          body: JSON.stringify(body),
        });
      else
        await get(`/database/${table}/${editingId}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
      setEditingId(undefined);
      await loadDb(table, dbPage, pageSize);
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  }
  async function deleteRow(row: any) {
    if (
      !confirm(
        `确定删除 ${tableNames[table]} ID=${row.id}？关联数据可能同时删除。`,
      )
    )
      return;
    try {
      await get(`/database/${table}/${row.id}`, { method: "DELETE" });
      await loadDb(table, Math.min(dbPage, totalPages), pageSize);
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  }
  async function changePage(page: number) {
    try {
      await loadDb(table, Math.max(1, Math.min(page, totalPages)), pageSize);
    } catch (e: any) {
      setError(e.message);
    }
  }
  async function changePageSize(size: number) {
    setPageSize(size);
    try {
      await loadDb(table, 1, size);
    } catch (e: any) {
      setError(e.message);
    }
  }
  async function changeScoreOrder(order: "desc" | "asc") {
    setDbScoreOrder(order);
    try {
      await loadDb("event_clusters", 1, pageSize, order);
    } catch (e: any) {
      setError(e.message);
    }
  }
  async function save(status?: string) {
    if (!selected) return;
    const x = await get(`/articles/${selected.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: selected.title,
        content: selected.content,
        ...(status ? { status } : {}),
      }),
    });
    setSelected(x);
    await loadArticles();
  }
  async function exportZip() {
    if (!selected) return;
    const r = await fetch(`${API}/exports/${selected.id}`, {
      method: "POST",
      headers,
    });
    if (!r.ok) {
      setError(await r.text());
      return;
    }
    const b = await r.blob(),
      u = URL.createObjectURL(b),
      a = document.createElement("a");
    a.href = u;
    a.download = "article.md";
    a.click();
    URL.revokeObjectURL(u);
  }
  async function importWebsite() {
    const url = websiteUrl.trim();
    if (!url) return;
    try {
      setWebsiteStatus("正在读取网站并生成公众号稿件，通常需要 1 至 3 分钟…");
      const result = await get("/articles/from-website", {
        method: "POST",
        body: JSON.stringify({ url, preserve_images: false }),
      });
      const list = await get("/articles");
      setArticles(list);
      setSelected(
        list.find((article: Article) => article.id === result.article_id) ||
          list[0] ||
          null,
      );
      setWebsiteUrl("");
      setWebsiteStatus(
        result.reused
          ? "该网站已生成过稿件，已打开原有稿件。"
          : "公众号稿件已生成并进入待审核列表。",
      );
      setError("");
    } catch (e: any) {
      setWebsiteStatus("");
      setError(e.message);
    }
  }
  async function importFile() {
    if (!uploadFile) return;
    try {
      setFileStatus("正在读取文件并生成公众号稿件，通常需要 1 至 3 分钟…");
      const form = new FormData();
      form.append("file", uploadFile);
      form.append("preserve_images", "false");
      const response = await fetch(`${API}/articles/from-file`, {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      const list = await get("/articles");
      setArticles(list);
      setSelected(
        list.find((article: Article) => article.id === result.article_id) ||
          list[0] ||
          null,
      );
      setUploadFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setFileStatus(
        result.reused
          ? "该文件已生成过稿件，已打开原有稿件。"
          : "公众号稿件已生成并进入待审核列表。",
      );
      setError("");
    } catch (e: any) {
      setFileStatus("");
      setError(e.message);
    }
  }
  async function deleteArticle(target: Article) {
    if (!window.confirm(`确定删除稿件“${target.title}”吗？删除后无法恢复。`))
      return;
    try {
      await get(`/articles/${target.id}`, { method: "DELETE" });
      const list = await get("/articles");
      setArticles(list);
      setSelected((current) =>
        current?.id === target.id
          ? list[0] || null
          : list.find((article: Article) => article.id === current?.id) ||
            list[0] ||
            null,
      );
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  }
  return (
    <div className="app">
      <aside>
        <div className="brand">
          <Sparkles /> AI 实战
        </div>
        <p className="muted">公众号内容工作台</p>
        <div className="viewnav">
          <button
            className={view === "articles" ? "primary" : ""}
            onClick={() => setView("articles")}
          >
            <FileText size={16} />
            稿件审核
          </button>
          <button
            className={view === "workflows" ? "primary" : ""}
            onClick={() => setView("workflows")}
          >
            <Play size={16} />
            工作流
          </button>
          <button
            className={view === "database" ? "primary" : ""}
            onClick={() => {
              setView("database");
              loadDb().catch(() => {});
            }}
          >
            <Database size={16} />
            数据库
          </button>
        </div>
        {view === "articles" && (
          <nav>
            {articles.map((a) => (
              <div
                className={"card " + (selected?.id === a.id ? "active" : "")}
                onClick={() => setSelected(a)}
                key={a.id}
              >
                <div className="cardhead">
                  <b>{a.title}</b>
                  <button
                    className="carddelete"
                    title="删除稿件"
                    aria-label={`删除稿件：${a.title}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      deleteArticle(a);
                    }}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
                <span>
                  {a.status} · {new Date(a.updated_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </nav>
        )}
      </aside>
      <main>
        {error && <div className="error">{error}</div>}
        {view === "articles" && (
          <section className="websiteimport">
            <div className="importintro">
              <h2>从网站或文件生成公众号文章</h2>
            </div>
            <div className="importforms">
              <div className="websiteform">
                <input
                  type="url"
                  value={websiteUrl}
                  onChange={(event) => setWebsiteUrl(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") importWebsite();
                  }}
                  placeholder="粘贴公开文章网址"
                  disabled={websiteStatus.startsWith("正在")}
                />
                <button
                  className="primary"
                  onClick={importWebsite}
                  disabled={!websiteUrl.trim() || websiteStatus.startsWith("正在")}
                >
                  {websiteStatus.startsWith("正在") ? "生成中…" : "从网站生成"}
                </button>
              </div>
              <div className="fileform">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".txt,.md,.markdown,.html,.htm,.json,.doc,.docx,.pdf"
                  onChange={(event) => setUploadFile(event.target.files?.[0] || null)}
                  disabled={fileStatus.startsWith("正在")}
                />
                <button
                  onClick={importFile}
                  disabled={!uploadFile || fileStatus.startsWith("正在")}
                >
                  <Upload size={16} />
                  {fileStatus.startsWith("正在") ? "生成中…" : "从文件生成"}
                </button>
              </div>
              <p className="muted filehint">
                支持 TXT、Markdown、HTML、JSON、DOC、DOCX、PDF，单个文件不超过 15 MB。
              </p>
              {websiteStatus && <p className="ok">{websiteStatus}</p>}
              {fileStatus && <p className="ok">{fileStatus}</p>}
            </div>
          </section>
        )}
        {view === "workflows" && (
          <>
            <header>
              <div>
                <h1>工作流控制</h1>
              </div>
              <button onClick={loadRuns}>
                <RefreshCw size={16} />
                刷新状态
              </button>
            </header>
            <section className="workflowgrid">
              {workflows.map((w) => {
                const last = runs.find((r) => r.name.startsWith(w[0]));
                return (
                  <article
                    className="workflowcard"
                    key={w[0]}
                  >
                    <h2>{w[1]}</h2>
                    {w[0] === "01" && workflowOne && showWorkflowSettings && (
                      <div
                        className="settingsoverlay"
                        onClick={() => setShowWorkflowSettings(false)}
                      >
                      <div
                        className="workflowsettings"
                        role="dialog"
                        aria-modal="true"
                        aria-label="工作流设置"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <div className="settingshead">
                          <div>
                            <h2>资讯到候选稿设置</h2>
                            <p className="muted">保存后将在下次运行工作流 01 时生效。</p>
                          </div>
                          <button
                            className="iconbutton"
                            title="关闭设置"
                            onClick={() => setShowWorkflowSettings(false)}
                          >
                            <X size={18} />
                          </button>
                        </div>
                        <label>每个平台获取数量（1–20）</label>
                        <input
                          type="number"
                          min="1"
                          max="20"
                          value={workflowOne.item_limit}
                          onChange={(e) =>
                            setWorkflowOne({
                              ...workflowOne,
                              item_limit: Number(e.target.value),
                            })
                          }
                        />
                        <label>候选稿数量（1–5）</label>
                        <select
                          value={workflowOne.article_limit ?? 5}
                          onChange={(e) =>
                            setWorkflowOne({
                              ...workflowOne,
                              article_limit: Number(e.target.value),
                            })
                          }
                        >
                          {[1, 2, 3, 4, 5].map((count) => (
                            <option key={count} value={count}>
                              {count} 篇
                            </option>
                          ))}
                        </select>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            marginTop: 24,
                          }}
                        >
                          <h3 style={{ margin: 0 }}>信息源网站</h3>
                          <button
                            onClick={() => {
                              setShowAddSource(!showAddSource);
                              setSourceStatus("");
                            }}
                          >
                            ＋ 新增
                          </button>
                        </div>
                        {showAddSource && (
                          <div
                            style={{
                              margin: "16px 0",
                              padding: 16,
                              border: "1px solid #303047",
                              borderRadius: 12,
                            }}
                          >
                            <p className="muted">
                              填写公开的 RSS/Atom
                              订阅地址；普通网页地址无法保证被正确采集。
                            </p>
                            <div
                              style={{
                                display: "grid",
                                gridTemplateColumns:
                                  "220px minmax(320px,1fr) auto",
                                gap: 12,
                                alignItems: "end",
                              }}
                            >
                              <label>
                                名称
                                <input
                                  value={newSource.name}
                                  onChange={(e) =>
                                    setNewSource({
                                      ...newSource,
                                      name: e.target.value,
                                    })
                                  }
                                  placeholder="例如：MIT Technology Review"
                                />
                              </label>
                              <label>
                                RSS / Atom 地址
                                <input
                                  value={newSource.url}
                                  onChange={(e) =>
                                    setNewSource({
                                      ...newSource,
                                      url: e.target.value,
                                    })
                                  }
                                  placeholder="https://example.com/feed.xml"
                                />
                              </label>
                              <button
                                className="primary"
                                disabled={
                                  !newSource.name.trim() ||
                                  !newSource.url.trim()
                                }
                                onClick={addSource}
                              >
                                确认新增
                              </button>
                            </div>
                            <label
                              style={{
                                display: "flex",
                                gap: 8,
                                alignItems: "center",
                                marginTop: 12,
                              }}
                            >
                              <input
                                style={{ width: "auto", margin: 0 }}
                                type="checkbox"
                                checked={newSource.official}
                                onChange={(e) =>
                                  setNewSource({
                                    ...newSource,
                                    official: e.target.checked,
                                  })
                                }
                              />
                              标记为官方一手来源
                            </label>
                          </div>
                        )}
                        {sourceStatus && <p className="ok">{sourceStatus}</p>}
                        {workflowOne.sources.map((s: any) => (
                          <div
                            style={{
                              display: "grid",
                              gridTemplateColumns: "190px minmax(300px,1fr)",
                              gap: 12,
                              alignItems: "center",
                            }}
                            key={s.id}
                          >
                            <label
                              style={{
                                display: "flex",
                                gap: 8,
                                alignItems: "center",
                              }}
                            >
                              <input
                                style={{ width: "auto", margin: 0 }}
                                type="checkbox"
                                checked={s.enabled}
                                onChange={(e) =>
                                  setWorkflowOne({
                                    ...workflowOne,
                                    sources: workflowOne.sources.map(
                                      (x: any) =>
                                        x.id === s.id
                                          ? { ...x, enabled: e.target.checked }
                                          : x,
                                    ),
                                  })
                                }
                              />
                              {s.name}
                            </label>
                            <input
                              value={s.url}
                              onChange={(e) =>
                                setWorkflowOne({
                                  ...workflowOne,
                                  sources: workflowOne.sources.map((x: any) =>
                                    x.id === s.id
                                      ? { ...x, url: e.target.value }
                                      : x,
                                  ),
                                })
                              }
                            />
                          </div>
                        ))}
                        <button onClick={saveWorkflowOne}>
                          <Check size={16} />
                          保存设置
                        </button>
                        {settingsStatus && (
                          <span className="ok" style={{ marginLeft: 12 }}>
                            {settingsStatus}
                          </span>
                        )}
                      </div>
                      </div>
                    )}
                    <p>
                      状态：<b>{last?.status || "尚未运行"}</b>
                    </p>
                    {w[0] === "01" && <Scoreboard run={last} />}
                    {w[0] === "04" && <PublicationResults run={last} />}
                    <div className="workflowactions">
                      <button
                        className="primary"
                        disabled={
                          starting === Number(w[0]) ||
                          last?.status === "running"
                        }
                        onClick={() => startWorkflow(Number(w[0]))}
                      >
                        <Play size={16} />
                        {last?.status === "running" ? "运行中…" : "启动"}
                      </button>
                      {w[0] === "01" && (
                        <button
                          onClick={() => {
                            setShowWorkflowSettings(true);
                            setSourceStatus("");
                          }}
                          aria-expanded={showWorkflowSettings}
                        >
                          <Settings size={16} />
                          设置
                        </button>
                      )}
                    </div>
                  </article>
                );
              })}
            </section>
          </>
        )}
        {view === "database" && (
          <>
            <header>
              <div>
                <h1>数据库</h1>
              </div>
              <div className="actions">
                <button onClick={beginCreate}>＋ 新增记录</button>
                <button onClick={() => loadDb()}>
                  <RefreshCw size={16} />
                  刷新数据
                </button>
              </div>
            </header>
            <section className="stats">
              {tables.map((t) => (
                <button
                  className={table === t ? "active" : ""}
                  onClick={() => chooseTable(t)}
                  key={t}
                >
                  <b>{tableNames[t]}</b>
                  <span>{summary[t] ?? 0}</span>
                </button>
              ))}
            </section>
            {editingId !== undefined && (
              <div className="editor">
                <h3>
                  {editingId === null ? "新增" : "编辑"} {tableNames[table]}
                </h3>
                {editingId === null ? (
                  <div className="formgrid">
                    {dbSchema.map((f: any) => (
                      <label key={f.name}>
                        <span>
                          {fieldNames[f.name] || f.name}
                          {f.required && <em> *</em>}
                        </span>
                        {f.enum?.length ? (
                          <select
                            value={newForm[f.name] ?? ""}
                            onChange={(e) =>
                              setNewForm({
                                ...newForm,
                                [f.name]: e.target.value,
                              })
                            }
                          >
                            <option value="">请选择</option>
                            {f.enum.map((x: string) => (
                              <option key={x}>{x}</option>
                            ))}
                          </select>
                        ) : f.type.includes("boolean") ? (
                          <select
                            value={String(newForm[f.name])}
                            onChange={(e) =>
                              setNewForm({
                                ...newForm,
                                [f.name]: e.target.value === "true",
                              })
                            }
                          >
                            <option value="true">是</option>
                            <option value="false">否</option>
                          </select>
                        ) : f.type.includes("json") ? (
                          <textarea
                            value={newForm[f.name] ?? ""}
                            onChange={(e) =>
                              setNewForm({
                                ...newForm,
                                [f.name]: e.target.value,
                              })
                            }
                            placeholder="复杂字段内容，如 [] 或 {}"
                          />
                        ) : (
                          <input
                            type={
                              f.type.includes("integer") ||
                              f.type.includes("float")
                                ? "number"
                                : f.type.includes("datetime")
                                  ? "datetime-local"
                                  : "text"
                            }
                            value={newForm[f.name] ?? ""}
                            onChange={(e) =>
                              setNewForm({
                                ...newForm,
                                [f.name]: e.target.value,
                              })
                            }
                          />
                        )}
                        <small>{f.name}</small>
                      </label>
                    ))}
                  </div>
                ) : (
                  <>
                    <p className="muted">
                      编辑模式使用原始字段，ID 和系统时间字段不会被修改。
                    </p>
                    <textarea
                      value={editorText}
                      onChange={(e) => setEditorText(e.target.value)}
                    />
                  </>
                )}
                <div className="actions">
                  <button className="primary" onClick={saveRow}>
                    保存
                  </button>
                  <button onClick={() => setEditingId(undefined)}>取消</button>
                </div>
              </div>
            )}
            <div className="datatable">
              <div className="tablebar">
                <h2>{tableNames[table]}</h2>
                <div className="actions">
                  <span className="muted">共 {totalRows} 条</span>
                  <label>
                    每页{" "}
                    <select
                      value={pageSize}
                      onChange={(e) => changePageSize(Number(e.target.value))}
                    >
                      {[5, 10, 20, 50].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>{" "}
                    条
                  </label>
                  <button
                    disabled={dbPage <= 1}
                    onClick={() => changePage(dbPage - 1)}
                  >
                    上一页
                  </button>
                  <span>
                    {dbPage} / {totalPages}
                  </span>
                  <button
                    disabled={dbPage >= totalPages}
                    onClick={() => changePage(dbPage + 1)}
                  >
                    下一页
                  </button>
                </div>
              </div>
              {rows.length === 0 ? (
                <p className="muted">暂无数据</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      {Object.keys(rows[0]).map((k) => (
                        <th
                          key={k}
                          title={k}
                          style={
                            columnWidths[`${table}:${k}`]
                              ? {
                                  width: columnWidths[`${table}:${k}`],
                                  minWidth: columnWidths[`${table}:${k}`],
                                  maxWidth: columnWidths[`${table}:${k}`],
                                }
                              : undefined
                          }
                        >
                          {fieldNames[k] || k}
                          <span
                            className="columnresizer"
                            title="拖动调整列宽"
                            onPointerDown={(event) =>
                              resizeColumn(`${table}:${k}`, event)
                            }
                          />
                        </th>
                      ))}
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr key={row.id || i}>
                        {Object.keys(rows[0]).map((k) => (
                          <td
                            key={k}
                            title={show(row[k])}
                            style={
                              columnWidths[`${table}:${k}`]
                                ? {
                                    width: columnWidths[`${table}:${k}`],
                                    minWidth: columnWidths[`${table}:${k}`],
                                    maxWidth: columnWidths[`${table}:${k}`],
                                  }
                                : undefined
                            }
                          >
                            {show(row[k])}
                          </td>
                        ))}
                        <td>
                          <div className="rowactions">
                            <button onClick={() => beginEdit(row)}>编辑</button>
                            <button
                              className="danger"
                              onClick={() => deleteRow(row)}
                            >
                              删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
        {view === "articles" &&
          (!selected ? (
            <div className="empty">
              <Sparkles size={42} />
              <h2>等待候选稿</h2>
              <p>请先在“工作流”页面按顺序启动流程。</p>
            </div>
          ) : (
            <>
              <header>
                <div>
                  <span className="pill">{selected.status}</span>
                  <h1>{selected.title}</h1>
                </div>
                <div className="actions">
                  <button className="primary" onClick={() => save("已批准")}>
                    <Check size={16} />
                    批准
                  </button>
                  <button
                    className="publicationaction"
                    onClick={() => startWorkflow(4)}
                    disabled={
                      !["已批准", "已导出"].includes(selected.status) ||
                      starting === 4
                    }
                    title={
                      ["已批准", "已导出"].includes(selected.status)
                        ? "启动工作流 04，生成网页、Markdown、封面和配图"
                        : "请先批准当前稿件"
                    }
                  >
                    <Play size={16} />
                    {starting === 4 ? "启动中…" : "生成公众号成品"}
                  </button>
                  <button onClick={exportZip}>
                    <Download size={16} />
                    导出素材包
                  </button>
                </div>
              </header>
              <section className="grid">
                <article>
                  <label>主标题</label>
                  <input
                    className="title"
                    value={selected.title}
                    onChange={(e) =>
                      setSelected({ ...selected, title: e.target.value })
                    }
                  />
                  <label>导语</label>
                  <textarea
                    value={selected.content.lead || ""}
                    onChange={(e) =>
                      setSelected({
                        ...selected,
                        content: { ...selected.content, lead: e.target.value },
                      })
                    }
                  />
                  <label>事实概述</label>
                  <textarea
                    value={factText(selected.content)}
                    onChange={(e) =>
                      setSelected({
                        ...selected,
                        content: updateFacts(selected.content, e.target.value),
                      })
                    }
                  />
                  <label>价值解读</label>
                  <textarea
                    value={
                      selected.content.value_interpretation ||
                      selected.content.analysis ||
                      ""
                    }
                    onChange={(e) =>
                      setSelected({
                        ...selected,
                        content: {
                          ...selected.content,
                          value_interpretation: e.target.value,
                        },
                      })
                    }
                  />
                  <label>信息来源</label>
                  <ArticleSource content={selected.content} />
                  <button
                    className="primary save"
                    onClick={() => save("编辑中")}
                  >
                    保存当前版本
                  </button>
                </article>
                <aside className="inspect">
                  <h3>标题备选</h3>
                  {selected.title_options.map((t) => (
                    <button
                      className="option"
                      key={t}
                      onClick={() => setSelected({ ...selected, title: t })}
                    >
                      {t}
                    </button>
                  ))}
                  <h3>风险提示</h3>
                  {selected.risk_notes.map((x) => (
                    <p className="risk" key={x}>
                      {x}
                    </p>
                  ))}
                </aside>
              </section>
            </>
          ))}
        <DisableCoverControls />
        {view === "database" && table === "event_clusters" && (
          <label className="dbsort">
            评分排序
            <select
              value={dbScoreOrder}
              onChange={(e) =>
                changeScoreOrder(e.target.value as "desc" | "asc")
              }
            >
              <option value="desc">评分降序</option>
              <option value="asc">评分升序</option>
            </select>
          </label>
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
