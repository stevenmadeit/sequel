"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Database, MessageSquareText, Sparkles } from "lucide-react";

const navigation = [
  { href: "/", label: "Ask Sequel", icon: MessageSquareText },
  { href: "/evals", label: "Evaluations", icon: BarChart3 },
  { href: "/schema", label: "Data schema", icon: Database },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark"><Sparkles size={17} /></span>
          <span>sequel<span className="brand-period">.</span></span>
        </Link>
        <div className="side-label">WORKSPACE</div>
        <nav className="side-nav">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link key={href} href={href} className={`nav-link ${active ? "active" : ""}`}>
                <Icon size={17} strokeWidth={1.8} />
                <span>{label}</span>
                {active && <span className="nav-indicator" />}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="status-dot" />
          <div>
            <div className="status-title">Local environment</div>
            <div className="status-subtitle">Ollama connected</div>
          </div>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb">SEQUEL <span>/</span> ANALYST WORKSPACE</div>
          <div className="topbar-right"><span className="model-pip" /> LOCAL MODEL</div>
        </header>
        <div className="page-content">{children}</div>
      </main>
    </div>
  );
}
