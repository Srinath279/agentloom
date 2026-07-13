import { ExternalLink } from "lucide-react";
import { ChatPanel } from "./components/ChatPanel";

const OBS_LINKS = [
  { label: "Temporal", href: "http://localhost:8233" },
  { label: "Grafana", href: "http://localhost:3000" },
  { label: "Langfuse", href: "http://localhost:3001" },
];

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur">
        <div className="max-w-4xl mx-auto px-6 py-3 flex flex-wrap items-center gap-x-6 gap-y-2">
          <div>
            <h1 className="text-lg font-semibold tracking-tight leading-none">
              🧵 <span className="text-accent">Agent</span>Loom
            </h1>
            <p className="text-[10px] text-foreground/50 mt-1">
              durable agents on <span className="text-accent">Temporal</span> ·{" "}
              <span className="text-accent-violet">OpenAI Agents SDK</span>
            </p>
          </div>

          <span className="ml-auto hidden sm:flex items-center gap-3 text-xs text-foreground/40">
            {OBS_LINKS.map((l) => (
              <a
                key={l.label}
                href={l.href}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 hover:text-accent"
              >
                {l.label}
                <ExternalLink size={11} />
              </a>
            ))}
          </span>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-6">
        <div className="h-[calc(100vh-6.5rem)] min-h-[28rem]">
          <ChatPanel />
        </div>
      </main>
    </div>
  );
}
