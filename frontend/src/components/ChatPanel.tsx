import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, MessageSquarePlus, Send, Sparkles, Square, User } from "lucide-react";

type ChatMessage = { role: "user" | "assistant"; content: string };
type ChatHistory = { messages: ChatMessage[]; responding: boolean; ended: boolean };

const SUGGESTIONS = [
  "Explain what a Temporal workflow is in simple terms",
  "What are signals and queries in Temporal?",
  "Summarize the pros and cons of event sourcing",
  "Write a haiku about durable execution",
];

/**
 * Interactive chat with a durable agent. Each session is a ChatWorkflow on
 * Temporal: messages are signals, the transcript is workflow state — so it
 * survives page reloads (session id kept in localStorage) and worker crashes.
 *
 * A session is created lazily on the first message, so the user can just
 * type any question and hit Enter — no "start a chat" step required.
 *
 * The panel fills its parent's height, so the layout decides how big it is.
 */
export function ChatPanel() {
  const [chatId, setChatId] = useState<string | null>(
    () => localStorage.getItem("agentloom-chat-id"),
  );
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [responding, setResponding] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Poll the workflow's transcript while a session is active.
  useEffect(() => {
    if (!chatId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch(`/api/chat/${chatId}/history`);
        if (r.status === 404) {
          // Workflow gone (e.g. Temporal dev server restarted) — reset.
          if (!cancelled) reset();
          return;
        }
        const h: ChatHistory = await r.json();
        if (cancelled) return;
        if (h.ended) return reset();
        setMessages(h.messages);
        setResponding(h.responding);
      } catch {
        /* transient — keep polling */
      }
    };
    tick();
    const t = setInterval(tick, 1500);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [chatId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, responding]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [chatId]);

  const reset = () => {
    localStorage.removeItem("agentloom-chat-id");
    setChatId(null);
    setMessages([]);
    setResponding(false);
  };

  // Create a session if none exists — called lazily from send().
  const ensureSession = useCallback(async (): Promise<string> => {
    if (chatId) return chatId;
    const r = await fetch("/api/chat/", { method: "POST" });
    if (!r.ok) throw new Error(`failed to start chat (${r.status})`);
    const { workflow_id } = await r.json();
    localStorage.setItem("agentloom-chat-id", workflow_id);
    setMessages([]);
    setChatId(workflow_id);
    return workflow_id;
  }, [chatId]);

  const endChat = async () => {
    if (chatId) await fetch(`/api/chat/${chatId}/end`, { method: "POST" }).catch(() => {});
    reset();
    inputRef.current?.focus();
  };

  const send = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || responding || sending) return;
    setSending(true);
    setError(null);
    setInput("");
    try {
      const id = await ensureSession();
      setMessages((m) => [...m, { role: "user", content: text }]);
      setResponding(true);
      const r = await fetch(`/api/chat/${id}/message`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!r.ok) throw new Error(`send failed (${r.status})`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "something went wrong — is the API up?");
      setResponding(false);
      setInput(text); // give the user their message back to retry
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const empty = messages.length === 0 && !responding;

  return (
    <section className="flex h-full flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="panel-title whitespace-nowrap">
          Agent Chat
          <span className="panel-caption ml-2 hidden sm:inline">
            · ask anything — each conversation is a durable Temporal workflow
          </span>
        </h2>
        <div className="flex items-center gap-3 text-xs">
          {chatId && (
            <span className="hidden sm:inline font-mono text-foreground/40" title="Temporal workflow id">
              {chatId}
            </span>
          )}
          {chatId ? (
            <button
              onClick={endChat}
              className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1 text-foreground/70 hover:text-foreground hover:border-foreground/40"
            >
              <Square size={11} /> End chat
            </button>
          ) : (
            <span
              className="flex items-center gap-1.5 whitespace-nowrap text-foreground/40"
              title="a durable session starts with your first message"
            >
              <MessageSquarePlus size={13} /> new session on first message
            </span>
          )}
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-auto panel p-4 space-y-4">
        {empty && (
          <div className="h-full flex flex-col items-center justify-center gap-6 px-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-accent/40 bg-accent/10 text-accent">
              <Sparkles size={22} />
            </div>
            <div>
              <p className="text-base font-medium text-foreground/90">Ask me anything</p>
              <p className="mt-1 max-w-md text-xs text-foreground/45">
                Your question starts a durable agent session — the transcript is Temporal
                workflow state, so it survives page reloads and worker crashes.
              </p>
            </div>
            <div className="grid w-full max-w-xl grid-cols-1 gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-xl border border-border bg-white/[0.03] px-3 py-2.5 text-left text-xs text-foreground/70 transition-colors hover:border-accent/50 hover:text-foreground hover:bg-accent/5"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={"flex items-start gap-2.5 " + (m.role === "user" ? "flex-row-reverse" : "")}>
            <div
              className={
                "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border " +
                (m.role === "user"
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-border bg-white/5 text-foreground/60")
              }
            >
              {m.role === "user" ? <User size={13} /> : <Bot size={13} />}
            </div>
            <div
              className={
                "max-w-[78%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed " +
                (m.role === "user"
                  ? "bg-accent/15 text-foreground rounded-tr-sm"
                  : "bg-white/5 text-foreground/90 border border-border rounded-tl-sm")
              }
            >
              {m.content}
            </div>
          </div>
        ))}

        {responding && (
          <div className="flex items-start gap-2.5">
            <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-white/5 text-foreground/60">
              <Bot size={13} />
            </div>
            <div className="rounded-2xl rounded-tl-sm border border-border bg-white/5 px-3.5 py-2.5 text-sm text-foreground/50">
              <span className="inline-flex gap-1">
                <span className="animate-bounce [animation-delay:0ms]">·</span>
                <span className="animate-bounce [animation-delay:150ms]">·</span>
                <span className="animate-bounce [animation-delay:300ms]">·</span>
              </span>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      <div className="flex items-end gap-2">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask anything… (Enter to send, Shift+Enter for a new line)"
          rows={Math.min(5, Math.max(1, input.split("\n").length))}
          disabled={responding || sending}
          className="flex-1 resize-none rounded-xl border border-border bg-card px-3.5 py-2.5 text-sm outline-none focus:border-accent/60 disabled:opacity-50"
        />
        <button
          onClick={() => send()}
          disabled={responding || sending || !input.trim()}
          className="flex h-10 items-center gap-2 rounded-xl bg-accent/20 border border-accent/60 px-4 text-sm text-accent hover:bg-accent/30 disabled:opacity-40"
        >
          <Send size={13} /> {sending ? "…" : "Send"}
        </button>
      </div>
    </section>
  );
}
