"use client";

import { ChangeEvent, useState } from "react";
import { BarChart3, FileSpreadsheet, FileText, Upload } from "lucide-react";
import Chat, { type ChatMessage } from "./Chat";

type SqlRecord = Record<string, string | number | null>;
type PolicyMatch = { text: string; source: string; score: number };
type AuditPayload = {
  final_response?: string;
  follow_up?: boolean;
  sql_query?: string;
  sql_results?: { data?: SqlRecord[] };
  rag_results?: { results?: PolicyMatch[] };
};

type UploadKind = "csv" | "pdf";

export default function ChatWorkspace() {
  const tenantId = "user_123";
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pinnedReport, setPinnedReport] = useState("");
  const [records, setRecords] = useState<SqlRecord[]>([]);
  const [ragResults, setRagResults] = useState<PolicyMatch[]>([]);
  const [sqlQuery, setSqlQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [uploadStatus, setUploadStatus] = useState<Record<string, string>>({});

  async function sendMessage(message: string) {
    if (isLoading) return;
    setIsLoading(true);
    setError("");
    const nextMessages: ChatMessage[] = [
      ...messages,
      { role: "user", content: message },
    ];
    setMessages(nextMessages);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const response = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({
          message,
          messages: nextMessages,
          audit_context: pinnedReport
            ? {
                report: pinnedReport,
                sql_query: sqlQuery,
                sql_results: records.length ? { data: records } : null,
                rag_results: ragResults.length ? { results: ragResults } : null,
              }
            : null,
        }),
      });
      if (!response.ok || !response.body)
        throw new Error(`Backend returned ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let eventName = "message";
      let finalPayload: AuditPayload | null = null;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const rawLine of lines) {
          const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          if (line.startsWith("data:")) {
            const payload = JSON.parse(line.slice(5).trim()) as AuditPayload & {
              error?: string;
            };
            if (eventName === "error")
              throw new Error(payload.error || "The request failed");
            if (eventName === "final") finalPayload = payload;
            eventName = "message";
          }
        }
        if (done) break;
      }
      if (!finalPayload?.final_response)
        throw new Error("The assistant did not return a response");

      setMessages((current) => [
        ...current,
        { role: "assistant", content: finalPayload.final_response || "" },
      ]);
      if (!finalPayload.follow_up) {
        setPinnedReport(finalPayload.final_response);
        setRecords(finalPayload.sql_results?.data || []);
        setRagResults(finalPayload.rag_results?.results || []);
        setSqlQuery(finalPayload.sql_query || "");
      }
    } catch (requestError) {
      setMessages((current) => current.slice(0, -1));
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to reach the assistant",
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function uploadFile(
    kind: UploadKind,
    event: ChangeEvent<HTMLInputElement>,
  ) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const extension = kind === "csv" ? ".csv" : ".pdf";
    if (!file.name.toLowerCase().endsWith(extension)) {
      setUploadStatus((current) => ({
        ...current,
        [kind]: `Choose a ${kind.toUpperCase()} file`,
      }));
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    setUploadStatus((current) => ({ ...current, [kind]: "Uploading..." }));
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const response = await fetch(`${apiUrl}/api/upload/${kind}`, {
        method: "POST",
        headers: { "X-Tenant-ID": tenantId },
        body: formData,
      });
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok) throw new Error(payload.detail || "Upload failed");
      setUploadStatus((current) => ({
        ...current,
        [kind]: `${file.name} ready`,
      }));
    } catch (uploadError) {
      setUploadStatus((current) => ({
        ...current,
        [kind]:
          uploadError instanceof Error ? uploadError.message : "Upload failed",
      }));
    }
  }

  return (
    <main className="chat-app-shell">
      <header className="chat-app-header">
        <div className="brand-lockup">
          <div className="brand-mark">
            <BarChart3 size={18} />
          </div>
          <div>
            <strong>northstar</strong>
            <span>enterprise intelligence</span>
          </div>
        </div>
        <span className="chat-tenant">TENANT / {tenantId}</span>
        <span className="chat-live">
          <span className="status-dot" /> LIVE
        </span>
      </header>
      <section className="chat-app-body">
        <div className="chat-intro">
          <div>
            <span className="eyebrow">Northstar Copilot</span>
            <h1>
              Ask your data
              <br />
              <em>anything.</em>
            </h1>
            <p>One conversation for your business data and corporate policy.</p>
          </div>
          <div className="chat-upload-bar" aria-label="Upload data sources">
            <label className="chat-upload-control">
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => void uploadFile("csv", event)}
              />
              <FileSpreadsheet size={15} />
              <span>Business data</span>
              <small>{uploadStatus.csv || "CSV"}</small>
            </label>
            <label className="chat-upload-control">
              <input
                type="file"
                accept=".pdf,application/pdf"
                onChange={(event) => void uploadFile("pdf", event)}
              />
              <FileText size={15} />
              <span>Corporate policy</span>
              <small>{uploadStatus.pdf || "PDF"}</small>
            </label>
            <span className="chat-upload-note">
              <Upload size={13} /> Sources stay tenant-scoped
            </span>
          </div>
        </div>
        {error && <div className="chat-error">{error}</div>}
        <Chat
          messages={messages}
          disabled={isLoading}
          isLoading={isLoading}
          onSubmit={sendMessage}
        />
        {sqlQuery && (
          <span className="chat-source-note">
            Methodology is included inline from the executed SQL and retrieved
            policy context.
          </span>
        )}
      </section>
    </main>
  );
}
