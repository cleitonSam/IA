"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

export default function DeleteMessageNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  return (
    <BaseNode nodeType="deleteMessage" {...props}>
      <div className="space-y-1.5">
        <label className="block text-[10px] text-slate-400">ID da mensagem a deletar</label>
        <input
          type="text"
          placeholder="{{_last_bot_msg_id}}"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.message_id || ""}
          onChange={(e) => onChange?.({ message_id: e.target.value })}
        />
        <p className="text-[9px] text-slate-600">Revoga a mensagem (apaga para ambos).</p>
      </div>
    </BaseNode>
  );
}
