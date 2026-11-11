"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, ChevronRight, FlaskConical, LoaderCircle } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
type DifficultyMetric = { correct: number; total: number; accuracy: number };
type Run = {
  run_id: string; model: string; split: string; started_at: string;
  total: number; correct: number; accuracy: number;
  accuracy_by_difficulty: Record<string, DifficultyMetric>;
  failure_types: Record<string, number>; average_steps: number; average_latency: number;
};
type QuestionResult = {
  question_id: string; question: string; difficulty: string; correct: number;
  failure_type: string; agent_sql: string; gold_sql: string | null;
  answer: string; error: string | null; steps: number;
};

export default function EvalsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [results, setResults] = useState<QuestionResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const selectRun = useCallback(async (runId: string) => {
    setSelected(runId);
    setDetailLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/evals?run_id=${encodeURIComponent(runId)}`);
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json() as { results: QuestionResult[] };
      setResults(data.results);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load run details.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/evals`)
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json() as Promise<{ runs: Run[] }>;
      })
      .then((data) => {
        setRuns(data.runs);
        const testRuns = data.runs.filter((run) => run.split === "test");
        if (testRuns[0]) void selectRun(testRuns[0].run_id);
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Could not load evaluations."))
      .finally(() => setLoading(false));
  }, [selectRun]);

  const testRuns = runs.filter((run) => run.split === "test").sort((a, b) => b.accuracy - a.accuracy);

  return (
    <>
      <div className="page-heading">
        <div><div className="eyebrow">MEASURE WHAT MATTERS</div><h1>Model evaluations</h1><p className="lead">Execution accuracy against the held-out benchmark, broken down by difficulty.</p></div>
        <div className="hero-tag"><span><FlaskConical size={12} style={{ verticalAlign: "middle" }} /></span> TEST SPLIT</div>
      </div>
      <div className="note"><AlertCircle size={15} />Development results are for prompt tuning only and are not reported as test accuracy. 20 questions, one question = 5 points.</div>
      {error && <div className="error-banner">{error}</div>}
      {loading ? <div className="page-loading"><LoaderCircle size={15} className="loading-pulse" /> Loading evaluation runs...</div> : testRuns.length === 0 ? (
        <div className="surface trace-empty">No test runs yet. Run <code>python evals/run_evals.py --split test</code> to populate results.</div>
      ) : (
        <>
          <div className="surface data-table-wrap">
            <table className="data-table">
              <thead><tr><th>Model</th><th>Overall</th><th>Easy</th><th>Medium</th><th>Hard</th><th>Questions</th><th>Failures</th><th /></tr></thead>
              <tbody>{testRuns.map((run) => (
                <tr key={run.run_id} className={selected === run.run_id ? "selected-row" : ""} onClick={() => void selectRun(run.run_id)}>
                  <td className="model-name">{run.model}<div className="muted" style={{ fontSize: 10, marginTop: 4 }}>{new Date(run.started_at).toLocaleString()}</div></td>
                  <td className="accuracy-number">{(run.accuracy * 100).toFixed(1)}%</td>
                  {(["easy", "medium", "hard"] as const).map((difficulty) => {
                    const item = run.accuracy_by_difficulty[difficulty];
                    return <td key={difficulty}>{item.total ? `${(item.accuracy * 100).toFixed(1)}%` : "—"}</td>;
                  })}
                  <td>{run.total}</td>
                  <td className="muted">{Object.entries(run.failure_types).filter(([type]) => type !== "none").map(([type, count]) => `${type} ${count}`).join(", ") || "None"}</td>
                  <td><ChevronRight size={15} color="#768178" /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {selected && (
            <section className="surface results-detail">
              <div className="run-heading"><div><h2>Question results</h2><div className="muted" style={{ fontSize: 10, marginTop: 5 }}>Run {selected}</div></div>{detailLoading && <LoaderCircle size={15} className="loading-pulse" />}</div>
              {results.map((result) => (
                <article className="question-detail" key={result.question_id}>
                  <div className="question-detail-top">
                    <div className="question-copy"><span className="question-id">{result.question_id}</span>{result.question}<div className="muted" style={{ fontSize: 10, marginTop: 5 }}>{result.difficulty} · {result.failure_type} · {result.steps} steps</div></div>
                    <span className={`badge ${result.correct ? "good" : "bad"}`}>{result.correct ? "CORRECT" : "INCORRECT"}</span>
                  </div>
                  {result.error && <div className="trace-result" style={{ color: "#e9a18f", marginBottom: 10 }}>{result.error}</div>}
                  <div className="sql-grid">
                    <div><div className="sql-panel-label">AGENT SQL</div><pre className="code-block">{result.agent_sql || "(no SQL executed)"}</pre></div>
                    <div><div className="sql-panel-label">GOLD SQL</div><pre className="code-block">{result.gold_sql ?? "(unanswerable — no gold SQL)"}</pre></div>
                  </div>
                </article>
              ))}
            </section>
          )}
        </>
      )}
    </>
  );
}
