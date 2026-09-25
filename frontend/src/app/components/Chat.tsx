"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowUpRight, LoaderCircle, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export type ChatMessage = { role: "user" | "assistant"; content: string };

type ChatProps = {
  messages: ChatMessage[];
  disabled: boolean;
  isLoading: boolean;
  onSubmit: (message: string) => void;
};

export default function Chat({
  messages,
  disabled,
  isLoading,
  onSubmit,
}: ChatProps) {
  const [input, setInput] = useState("");

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || disabled) return;
    setInput("");
    onSubmit(message);
  }

  return (
    <section className="chat-panel" aria-label="Follow-up conversation">
      <div className="chat-heading">
        <div>
          <span className="report-kicker">
            <Sparkles size={14} /> Conversation
          </span>
          <h2>Ask about this audit</h2>
        </div>
        <span className="chat-context">Current audit context</span>
      </div>
      <div className="chat-history" aria-live="polite">
        {messages.length ? (
          messages.map((message, index) => (
            <div
              className={`chat-message ${message.role}`}
              key={`${message.role}-${index}`}
            >
              <span>{message.role === "user" ? "You" : "Northstar"}</span>
              <div className="chat-message-content whitespace-pre-wrap leading-relaxed">
                {message.role === "assistant" ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content}
                  </ReactMarkdown>
                ) : (
                  <p>{message.content}</p>
                )}
              </div>
            </div>
          ))
        ) : (
          <div className="chat-empty">
            Ask a question after your audit report is ready.
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <form className="chat-form" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask a follow-up question..."
          aria-label="Ask a follow-up question"
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || !input.trim()}>
          {isLoading ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <ArrowUpRight size={16} />
          )}
          {isLoading ? "AI is typing..." : "Ask"}
        </button>
      </form>
    </section>
  );
}
