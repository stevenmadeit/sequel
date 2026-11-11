"use client";

import { FormEvent, useRef, useState } from "react";
import { ArrowUp, Check, CircleAlert, LoaderCircle, Sparkles, Terminal } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const examples = [
  "How many job postings are in the database?",
  "Which 5 skills are mentioned most often?",
  "Which skills appear together most frequently?",
];

type TraceItem = { id: number; type: "action" | "result" | "error"; data: Record<string, unknown> };
type ResultTable = { columns: string[]; rows: unknown[][]; truncated: boolean };
type FinalAnswer = { answer: string; sql: string; steps?: number };

function isResultTable(value: unknown): value is ResultTable {
  return Boolean(value && typeof value === "object" && "columns" in value && "rows" in value);
}

export default function HomePage() {
  const [question, setQuestion] = useState("");
  const [trace, setTrace] = useState<TraceItem[]>([]);
  const [final, setFinal] = useState<FinalAnswer | null>(null);
  const [table, setTable] = useState<ResultTable | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nextId = useRef(0);

  function addTrace(type: TraceItem["type"], data: Record<string, unknown>) {
    setTrace((current) => [...current, { id: nextId.current++, type, data }]);
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const prompt = question.trim();
    if (!prompt || busy) return;
    setTrace([]);
    setFinal(null);
    setTable(null);
    setError("");
    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ question: prompt }),
      });
      if (!response.ok || !response.body) {
        const detail = await response.text();
        throw new Error(detail || `Request failed (${response.status}).`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const processEvent = (block: string) => {
        let eventType = "message";
        const dataLines: string[] = [];
        for (const line of block.split(/\r?\n/)) {
          if (line.startsWith("event:")) eventType = line.slice(6).trim();
          if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) return;
        const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
        if (eventType === "action") addTrace("action", data);
        else if (eventType === "result") {
          addTrace("result", data);
          if (isResultTable(data)) {
            setTable({
              columns: data.columns,
              rows: data.rows,
              truncated: Boolean(data.truncated),
            });
          }
        } else if (eventType === "final") setFinal(data as FinalAnswer);
        else if (eventType === "error") {
          setError(String(data.message ?? "The agent encountered an error."));
          addTrace("error", data);
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() ?? "";
        blocks.forEach(processEvent);
        if (done) break;
      }
      if (buffer.trim()) processEvent(buffer);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Request failed.";
      setError(message);
      addTrace("error", { message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR DATA, IN PLAIN ENGLISH</div>
          <h1>Ask your data<br />a better question.</h1>
          <p className="lead">Explore your job market data with a local AI analyst. Ask naturally — Sequel writes and runs the SQL.</p>
        </div>
        <div className="hero-tag"><span>●</span> PRIVATE BY DESIGN</div>
      </div>

      <form className="surface question-card" onSubmit={submit}>
        <label htmlFor="question">What would you like to know?</label>
        <textarea
          id="question"
          className="question-input"
          placeholder="Ask a question about your data..."
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
          disabled={busy}
        />
        <div className="composer-footer">
          <span className="hint">Your data stays on this machine · Enter to run</span>
          <button className="primary-button" disabled={busy || !question.trim()} type="submit">
            {busy ? <LoaderCircle size={15} className="loading-pulse" /> : <ArrowUp size={15} />}
            {busy ? "Thinking..." : "Ask Sequel"}
          </button>
        </div>
      </form>

      <div className="examples">
        <span className="examples-label">TRY ASKING</span>
        {examples.map((example) => (
          <button key={example} type="button" className="example-chip" onClick={() => setQuestion(example)}>{example}</button>
        ))}
      </div>

      <div className="section-heading">
        <h2>Agent trace</h2>
        <div className="live-badge">{busy && <span className="status-dot" />} {busy ? "LIVE · FOLLOWING" : trace.length ? "RUN COMPLETE" : "READY WHEN YOU ARE"}</div>
      </div>
      <div className="surface trace">
        {!trace.length && !busy ? (
          <div className="trace-empty"><div><Terminal size={20} /><div>Your agent’s reasoning steps will appear here.</div></div></div>
        ) : (
          trace.map((item, index) => {
            const data = item.data;
            if (item.type === "action") {
              return (
                <div className="trace-row" key={item.id}>
                  <div className="trace-meta"><span className="trace-index">{String(index + 1).padStart(2, "0")}</span><span className="trace-kind">Action</span></div>
                  <div className="tool-line">Calling {String(data.tool ?? "tool")}</div>
                  {typeof data.sql === "string" && <pre className="code-block" style={{ marginTop: 9 }}>{data.sql}</pre>}
                </div>
              );
            }
            if (item.type === "error") {
              return <div className="trace-row" key={item.id}><div className="trace-meta"><CircleAlert size={14} color="#ff9a86" /><span className="trace-kind error">Error</span></div><div className="trace-result">{String(data.message ?? "Unknown error")}</div></div>;
            }
            const isError = Boolean(data.error);
            return (
              <div className="trace-row" key={item.id}>
                <div className="trace-meta">{isError ? <CircleAlert size={13} color="#ff9a86" /> : <Check size={13} color="#a7e65f" />}<span className={`trace-kind ${isError ? "error" : ""}`}>{isError ? "Recovered error" : "Result"}</span><span className="trace-index">STEP {String(data.step ?? "")}</span></div>
                <div className="trace-result">{String(data.summary ?? "")}</div>
              </div>
            );
          })
        )}
      </div>

      {error && <div className="error-banner" style={{ marginTop: 14 }}><CircleAlert size={14} style={{ verticalAlign: "middle", marginRight: 7 }} />{error}</div>}

      {final && (
        <section className="surface final-card">
          <div className="final-top"><Sparkles size={14} /> Final answer</div>
          <p className="final-answer">{final.answer}</p>
          {final.sql && <><div className="sql-panel-label">SQL USED</div><pre className="code-block">{final.sql}</pre></>}
          {table && table.columns.length > 0 && (
            <div className="result-table-wrap">
              <table className="result-table">
                <thead><tr>{table.columns.map((column, i) => <th key={`${column}-${i}`}>{column}</th>)}</tr></thead>
                <tbody>{table.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell === null ? "—" : String(cell)}</td>)}</tr>)}</tbody>
              </table>
              {table.truncated && <div className="result-count">Showing first 50 rows.</div>}
            </div>
          )}
        </section>
      )}
    </>
  );
}
