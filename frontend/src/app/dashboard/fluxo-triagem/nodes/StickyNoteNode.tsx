"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";

const COLORS = [
  { bg: "#fef3c7", border: "#fbbf24", text: "#78350f", name: "Amarelo" },
  { bg: "#dbeafe", border: "#3b82f6", text: "#1e3a8a", name: "Azul" },
  { bg: "#dcfce7", border: "#22c55e", text: "#14532d", name: "Verde" },
  { bg: "#fce7f3", border: "#ec4899", text: "#831843", name: "Rosa" },
  { bg: "#f3e8ff", border: "#a855f7", text: "#581c87", name: "Roxo" },
];

export default function StickyNoteNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  const colorIdx = Math.max(0, Math.min(COLORS.length - 1, data.color_idx ?? 0));
  const color = COLORS[colorIdx];
  const selected = (props as any).selected;

  return (
    <div
      className={"rounded-lg p-2 shadow-lg transition-all " + (selected ? "ring-2 ring-offset-2 ring-offset-slate-900 ring-white/50" : "")}
      style={{
        background: color.bg,
        border: `2px solid ${color.border}`,
        minWidth: 200,
        minHeight: 120,
        maxWidth: 400,
      }}
    >
      <div className="flex gap-1 mb-1">
        {COLORS.map((c, i) => (
          <button
            key={i}
            onClick={() => onChange?.({ color_idx: i })}
            className={"w-3 h-3 rounded-full border " + (i === colorIdx ? "ring-1 ring-slate-700" : "")}
            style={{ background: c.bg, borderColor: c.border }}
            title={c.name}
          />
        ))}
      </div>
      <textarea
        placeholder="Anotação..."
        className="w-full bg-transparent outline-none resize-y"
        style={{ color: color.text, fontSize: 12, minHeight: 80, fontFamily: "Georgia, serif" }}
        value={data.texto || ""}
        onChange={(e) => onChange?.({ texto: e.target.value })}
      />
    </div>
  );
}
