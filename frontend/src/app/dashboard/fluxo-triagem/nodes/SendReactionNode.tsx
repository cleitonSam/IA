"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

const EMOJI_SUGESTOES = ["👍", "❤️", "😂", "😮", "😢", "🙏", "🎉", "✅", "❌"];

export default function SendReactionNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  return (
    <BaseNode nodeType="sendReaction" {...props}>
      <div className="space-y-1.5">
        <label className="block text-[10px] text-slate-400">ID da mensagem</label>
        <input
          type="text"
          placeholder="{{_last_msg_id}} ou ID especifico"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.message_id || ""}
          onChange={(e) => onChange?.({ message_id: e.target.value })}
        />
        <label className="block text-[10px] text-slate-400 mt-1">Emoji</label>
        <input
          type="text"
          placeholder="👍"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.emoji || ""}
          onChange={(e) => onChange?.({ emoji: e.target.value })}
          maxLength={8}
        />
        <div className="flex flex-wrap gap-1 mt-1">
          {EMOJI_SUGESTOES.map((e) => (
            <button
              key={e}
              onClick={() => onChange?.({ emoji: e })}
              className="text-sm hover:scale-125 transition-transform"
            >{e}</button>
          ))}
        </div>
        <p className="text-[9px] text-slate-600">Reage com emoji numa mensagem especifica.</p>
      </div>
    </BaseNode>
  );
}
