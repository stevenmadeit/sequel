"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Database } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function SchemaPage() {
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetch(`${API_BASE}/schema`)
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json() as Promise<{ content: string }>;
      })
      .then((data) => { if (active) setContent(data.content); })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "Could not load schema.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  return (
    <>
      <div className="page-heading">
        <div><div className="eyebrow">KNOW YOUR DATA</div><h1>Schema reference</h1><p className="lead">Tables, columns, and example values available to the Sequel analyst.</p></div>
        <div className="hero-tag"><span><Database size={12} style={{ verticalAlign: "middle" }} /></span> DUCKDB</div>
      </div>
      {loading && <div className="page-loading">Loading schema documentation...</div>}
      {error && <div className="error-banner">{error}</div>}
      {!loading && !error && <article className="surface schema-md" style={{ padding: "24px 28px" }}><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></article>}
    </>
  );
}
