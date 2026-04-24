"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";

const COLORS = [
  { border: "#3b82f6", bg: "rgba(59,130,246,0.05)", text: "#bfdbfe" },
  { border: "#10b981", bg: "rgba(16,185,129,0.05)", text: "#a7f3d0" },
  { border: "#f59e0b", bg: "rgba(245,158,11,0.05)", text: "#fde68a" },
  { border: "#ec4899", bg: "rgba(236,72,153,0.05)", text: "#fbcfe8" },
  { border: "#a855f7", bg: "rgba(168,85,247,0.05)", text: "#e9d5ff" },
];

export default function GroupBoxNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  const colorIdx = Math.max(0, Math.min(COLORS.length - 1, data.color_idx ?? 0));
  const color = COLORS[colorIdx];
  const width = data.width || 400;
  const height = data.height || 300;
  const selected = (props as any).selected;

  return (
    <div
      className={"rounded-xl transition-all " + (selected ? "ring-2 ring-white/40" : "")}
      style={{
        background: color.bg,
        border: `2px dashed ${color.border}`,
        width,
        height,
        padding: 10,
        pointerEvents: "all",
      }}
    >
      <div className="flex items-center gap-2 mb-1">
        {COLORS.map((c, i) => (
          <button
            key={i}
            onClick={() => onChange?.({ color_idx: i })}
            className={"w-3 h-3 rounded-full border " + (i === colorIdx ? "ring-1 ring-white" : "")}
            style={{ background: c.border, borderColor: c.border }}
          />
        ))}
      </div>
      <input
        type="text"
        placeholder="Nome do grupo"
        className="w-full bg-transparent outline-none font-bold"
        style={{ color: color.text, fontSize: 13 }}
        value={data.titulo || ""}
        onChange={(e) => onChange?.({ titulo: e.target.value })}
      />
      <p className="text-[10px] opacity-60 mt-1" style={{ color: color.text }}>
        Solte nós dentro desta moldura pra agrupar visualmente.
      </p>
    </div>
  );
}
