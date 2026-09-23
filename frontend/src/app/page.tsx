"use client";

import Image from "next/image";
import { FormEvent, useState } from "react";
import {
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  CircleAlert,
  Database,
  FileSearch,
  LoaderCircle,
  Play,
  Radio,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  XCircle,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Step = {
  id: string;
  label: string;
  detail: string;
  status: "pending" | "active" | "complete" | "error";
};
type RecordValue = string | number | null;
type SqlRecord = Record<string, RecordValue>;

const initialSteps: Step[] = [
  {
    id: "planner",
    label: "Planning",
    detail: "Waiting to analyze your request",
    status: "pending",
  },
  {
    id: "sql_executor",
    label: "Transaction audit",
    detail: "Waiting for live database query",
    status: "pending",
  },
  {
    id: "rag_executor",
    label: "Policy retrieval",
    detail: "Waiting for contract evidence",
    status: "pending",
  },
  {
    id: "synthesizer",
    label: "Audit synthesis",
    detail: "Waiting for cross-reference",
    status: "pending",
  },
];
const starterPrompt =
  "Audit APAC enterprise orders for discounts above the partner agreement cap";

function formatValue(value: RecordValue) {
  if (value === null || value === undefined) return "-";
  return typeof value === "number" ? value.toLocaleString("en-US") : value;
}

function stepForNode(node: string) {
  return node === "sql_executor" ||
    node === "rag_executor" ||
    node === "synthesizer"
    ? node
    : "planner";
}

export default function Home() {
  const [query, setQuery] = useState(starterPrompt);
  const [steps, setSteps] = useState(initialSteps);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState("");
  const [sqlQuery, setSqlQuery] = useState("");
  const [records, setRecords] = useState<SqlRecord[]>([]);
  const [ragResults, setRagResults] = useState<
    { text: string; source: string; score: number }[]
  >([]);
  const [report, setReport] = useState("");
  const [activeTab, setActiveTab] = useState<"records" | "query" | "evidence">(
    "records",
  );

  function updateStep(node: string, status: Step["status"], detail?: string) {
    const id = stepForNode(node);
    setSteps((current) =>
      current.map((step) =>
        step.id === id
          ? { ...step, status, detail: detail || step.detail }
          : step,
      ),
    );
  }

  async function runAudit(event?: FormEvent) {
    event?.preventDefault();
    if (!query.trim() || isRunning) return;
    setIsRunning(true);
    setError("");
    setReport("");
    setRecords([]);
    setRagResults([]);
    setSqlQuery("");
    setSteps(
      initialSteps.map((step, index) =>
        index === 0
          ? {
              ...step,
              status: "active",
              detail: "Decomposing the audit request",
            }
          : step,
      ),
    );
    try {
      const response = await fetch("http://127.0.0.1:8000/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: query.trim() }),
      });
      if (!response.ok || !response.body)
        throw new Error(`Backend returned ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "message";
      const handleEvent = (eventName: string, data: string) => {
        if (!data) return;
        const payload = JSON.parse(data);
        if (eventName === "error")
          throw new Error(payload.error || "The audit failed");
        if (eventName === "step") {
          const node = payload.node || "planner";
          updateStep(
            node,
            "complete",
            payload.trace?.message || "Completed successfully",
          );
          const next =
            node === "planner"
              ? "sql_executor"
              : node === "sql_executor"
                ? "rag_executor"
                : node === "rag_executor"
                  ? "synthesizer"
                  : "";
          if (next) updateStep(next, "active");
          if (payload.trace?.sql_generated)
            setSqlQuery(payload.trace.sql_generated);
        }
        if (eventName === "final") {
          setReport(payload.final_response || "No report was returned.");
          setSqlQuery(payload.sql_query || "");
          setRecords(payload.sql_results?.data || []);
          setRagResults(payload.rag_results?.results || []);
          setSteps((current) =>
            current.map((step) => ({
              ...step,
              status: "complete",
              detail: "Completed successfully",
            })),
          );
        }
      };
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const rawEvent of events) {
          let data = "";
          for (const line of rawEvent.split("\n")) {
            if (line.startsWith("event:")) currentEvent = line.slice(6).trim();
            if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          handleEvent(currentEvent, data);
          currentEvent = "message";
        }
        if (done) break;
      }
    } catch (runError) {
      const message =
        runError instanceof Error
          ? runError.message
          : "Unable to complete the audit";
      setError(
        message.includes("fetch")
          ? "Backend unavailable. Start the FastAPI server on port 8000 and try again."
          : message,
      );
      setSteps((current) =>
        current.map((step) =>
          step.status === "active"
            ? { ...step, status: "error", detail: "Could not complete" }
            : step,
        ),
      );
    } finally {
      setIsRunning(false);
    }
  }

  const completedCount = steps.filter(
    (step) => step.status === "complete",
  ).length;
  const violationCount = records.filter(
    (record) =>
      Number(record.discount_pct) >
      (String(record.region).toUpperCase() === "APAC" ? 15 : 12),
  ).length;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">
            <BarChart3 size={19} />
          </div>
          <div>
            <strong>northstar</strong>
            <span>enterprise intelligence</span>
          </div>
        </div>
        <div className="topbar-status">
          <span className="status-dot" /> Systems operational{" "}
          <span className="topbar-divider" />{" "}
          <span className="mono">AUDIT / 2026.09</span>
        </div>
        <button
          className="icon-button"
          aria-label="Open external status page"
          title="Open status page"
        >
          <ArrowUpRight size={17} />
        </button>
      </header>
      <section className="hero-band">
        <div className="hero-copy">
          <p className="eyebrow">
            <Sparkles size={14} /> Intelligence workspace
          </p>
          <h1>
            Compliance, with
            <br />
            <em>receipts.</em>
          </h1>
          <p className="hero-description">
            Cross-reference live commercial activity with the policies that
            govern it. Ask a question, get an audit trail.
          </p>
        </div>
        <div className="hero-stamp">
          <span>LIVE CONTROL ROOM</span>
          <strong>01</strong>
          <small>
            Structured + semantic
            <br />
            evidence in one view
          </small>
        </div>
      </section>
      <section className="workspace-grid">
        <aside className="control-column">
          <div className="section-kicker">
            <span>01</span> Run an audit
          </div>
          <form onSubmit={runAudit} className="query-form">
            <label htmlFor="audit-query">Your question</label>
            <textarea
              id="audit-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              rows={5}
              placeholder="Ask about orders, customers, discounts..."
            />
            <button
              className="run-button"
              type="submit"
              disabled={isRunning || !query.trim()}
            >
              {isRunning ? (
                <>
                  <LoaderCircle className="spin" size={17} /> Running audit
                </>
              ) : (
                <>
                  <Play size={16} fill="currentColor" /> Run audit
                </>
              )}
            </button>
          </form>
          <div className="suggestion-block">
            <span className="label">Try a question</span>
            <button onClick={() => setQuery(starterPrompt)}>
              {starterPrompt}
            </button>
            <button
              onClick={() =>
                setQuery("Which orders exceed the approved discount threshold?")
              }
            >
              Which orders exceed the approved discount threshold?
            </button>
          </div>
          <div className="connection-card">
            <div>
              <Database size={16} />
              <span>Supabase transaction layer</span>
            </div>
            <strong>
              <span className="status-dot" /> Connected
            </strong>
            <small>Live read-only connection</small>
          </div>
        </aside>
        <div className="main-column">
          <div className="section-kicker">
            <span>02</span> Agent activity{" "}
            <span className="activity-count">{completedCount}/4 complete</span>
          </div>
          <div className="stepper">
            {steps.map((step, index) => (
              <div className={`step ${step.status}`} key={step.id}>
                <div className="step-icon">
                  {step.status === "complete" ? (
                    <CheckCircle2 size={17} />
                  ) : step.status === "error" ? (
                    <XCircle size={17} />
                  ) : step.status === "active" ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <span>{String(index + 1).padStart(2, "0")}</span>
                  )}
                </div>
                <div>
                  <strong>{step.label}</strong>
                  <span>{step.detail}</span>
                </div>
                {index < steps.length - 1 && <div className="step-line" />}
              </div>
            ))}
          </div>
          <div className="section-kicker results-kicker">
            <span>03</span> Audit output{" "}
            <span className="live-label">
              <Radio size={12} /> STREAMING
            </span>
          </div>
          {error && (
            <div className="error-banner">
              <CircleAlert size={17} />
              <span>{error}</span>
            </div>
          )}
          <div className="metric-row">
            <div>
              <span>Records inspected</span>
              <strong>{records.length || "-"}</strong>
            </div>
            <div>
              <span>Policy matches</span>
              <strong>{ragResults.length || "-"}</strong>
            </div>
            <div className={violationCount ? "metric-alert" : ""}>
              <span>Potential violations</span>
              <strong>{records.length ? violationCount : "-"}</strong>
            </div>
            <div>
              <span>Source confidence</span>
              <strong>{report ? "High" : "-"}</strong>
            </div>
          </div>
          <div className="output-panel">
            <div className="panel-tabs">
              <button
                className={activeTab === "records" ? "selected" : ""}
                onClick={() => setActiveTab("records")}
              >
                <Database size={15} /> Raw records
              </button>
              <button
                className={activeTab === "query" ? "selected" : ""}
                onClick={() => setActiveTab("query")}
              >
                <TerminalSquare size={15} /> Generated SQL
              </button>
              <button
                className={activeTab === "evidence" ? "selected" : ""}
                onClick={() => setActiveTab("evidence")}
              >
                <FileSearch size={15} /> Policy evidence
              </button>
            </div>
            {activeTab === "records" && (
              <div className="table-wrap">
                {records.length ? (
                  <table>
                    <thead>
                      <tr>
                        {Object.keys(records[0]).map((key) => (
                          <th key={key}>{key.replaceAll("_", " ")}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((record, index) => (
                        <tr key={index}>
                          {Object.keys(records[0]).map((key) => (
                            <td
                              key={key}
                              className={
                                key === "discount_pct" &&
                                Number(record[key]) > 15
                                  ? "cell-alert"
                                  : ""
                              }
                            >
                              {formatValue(record[key])}
                              {key === "discount_pct" ? "%" : ""}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty-state">
                    <Database size={25} />
                    <strong>
                      {isRunning
                        ? "Waiting for transaction records"
                        : "Your audit results will appear here"}
                    </strong>
                    <span>
                      Run an audit to inspect the live order register.
                    </span>
                  </div>
                )}
              </div>
            )}
            {activeTab === "query" && (
              <pre className="code-panel">
                {sqlQuery ||
                  "-- SQL generated by the audit agent will appear here"}
              </pre>
            )}
            {activeTab === "evidence" && (
              <div className="evidence-list">
                {ragResults.length ? (
                  ragResults.map((item, index) => (
                    <article key={index}>
                      <div>
                        <FileSearch size={16} />
                        <span>
                          {item.source} match · {item.score.toFixed(2)}
                        </span>
                      </div>
                      <p>{item.text}</p>
                    </article>
                  ))
                ) : (
                  <div className="empty-state">
                    <FileSearch size={25} />
                    <strong>No policy evidence yet</strong>
                    <span>Run an audit to retrieve governing clauses.</span>
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="report-panel">
            <div className="report-heading">
              <div>
                <span className="report-kicker">
                  <ShieldCheck size={14} /> Executive report
                </span>
                <h2>Audit findings</h2>
              </div>
              {report && (
                <span className="report-ready">
                  <CheckCircle2 size={14} /> Ready for review
                </span>
              )}
            </div>
            {report ? (
              <div className="markdown-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {report}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="report-placeholder">
                <Sparkles size={19} />
                <span>
                  The synthesis agent will turn database findings and contract
                  evidence into an executive-ready report.
                </span>
              </div>
            )}
          </div>
        </div>
      </section>
      <footer>
        <span>Northstar BI Copilot</span>
        <span>Read-only analysis environment</span>
        <span className="mono">POL-2026-MSA-V3</span>
      </footer>
    </main>
  );
}

function LegacyHome() {
  return (
    <div className="flex flex-col flex-1 items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex flex-1 w-full max-w-3xl flex-col items-center justify-between py-32 px-16 bg-white dark:bg-black sm:items-start">
        <Image
          className="dark:invert h-5 w-[100px]"
          src="/next.svg"
          alt="Next.js logo"
          width={100}
          height={20}
          priority
        />
        <div className="flex flex-col items-center gap-6 text-center sm:items-start sm:text-left">
          <h1 className="max-w-xs text-3xl font-semibold leading-10 tracking-tight text-black dark:text-zinc-50">
            To get started, edit the{" "}
            <code className="rounded bg-black/[.06] px-1.5 py-0.5 font-mono text-[0.9em] dark:bg-white/[.08]">
              page.tsx
            </code>{" "}
            file.
          </h1>
          <p className="max-w-md text-lg leading-8 text-zinc-600 dark:text-zinc-400">
            Looking for a starting point or more instructions? Head over to{" "}
            <a
              href="https://vercel.com/templates?framework=next.js&utm_source=create-next-app&utm_medium=appdir-template-tw&utm_campaign=create-next-app"
              className="font-medium text-zinc-950 dark:text-zinc-50"
            >
              Templates
            </a>{" "}
            or the{" "}
            <a
              href="https://nextjs.org/learn?utm_source=create-next-app&utm_medium=appdir-template-tw&utm_campaign=create-next-app"
              className="font-medium text-zinc-950 dark:text-zinc-50"
            >
              Learning
            </a>{" "}
            center.
          </p>
        </div>
        <div className="flex flex-col gap-4 text-base font-medium sm:flex-row">
          <a
            className="flex h-12 w-full items-center justify-center gap-2 rounded-full bg-foreground px-5 text-background transition-colors hover:bg-[#383838] dark:hover:bg-[#ccc] md:w-[158px]"
            href="https://vercel.com/new?utm_source=create-next-app&utm_medium=appdir-template-tw&utm_campaign=create-next-app"
            target="_blank"
            rel="noopener noreferrer"
          >
            <Image
              className="dark:invert h-[14px] w-4"
              src="/vercel.svg"
              alt="Vercel logomark"
              width={16}
              height={14}
            />
            Deploy Now
          </a>
          <a
            className="flex h-12 w-full items-center justify-center rounded-full border border-solid border-black/[.08] px-5 transition-colors hover:border-transparent hover:bg-black/[.04] dark:border-white/[.145] dark:hover:bg-[#1a1a1a] md:w-[158px]"
            href="https://nextjs.org/docs?utm_source=create-next-app&utm_medium=appdir-template-tw&utm_campaign=create-next-app"
            target="_blank"
            rel="noopener noreferrer"
          >
            Documentation
          </a>
        </div>
      </main>
    </div>
  );
}
