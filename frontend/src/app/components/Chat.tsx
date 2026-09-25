"use client";

import { FormEvent, useState } from "react";
import { ArrowUpRight, LoaderCircle, Sparkles } from "lucide-react";

export type ChatMessage = { role: "user" | "assistant"; content: string };

type ChatProps = {
  messages: ChatMessage[];
  disabled: boolean;
  onSubmit: (message: string) => void;
};

export default function Chat({ messages, disabled, onSubmit }: ChatProps) {
  const [input, setInput] = useState("");

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
              <p>{message.content}</p>
            </div>
          ))
        ) : (
          <div className="chat-empty">
            Ask a question after your audit report is ready.
          </div>
        )}
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
          {disabled ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <ArrowUpRight size={16} />
          )}
          Ask
        </button>
      </form>
    </section>
  );
}
