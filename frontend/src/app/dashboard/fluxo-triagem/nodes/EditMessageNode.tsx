"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function EditMessageNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  return (
    <BaseNode nodeType="editMessage" {...props}>
      <div className="space-y-1.5">
        <input
          type="text"
          placeholder="{{_last_bot_msg_id}}"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.message_id || ""}
          onChange={(e) => onChange?.({ message_id: e.target.value })}
        />
        <NodeTextarea
          label="Novo texto"
          value={data.new_text || ""}
          onChange={(v) => onChange?.({ new_text: v })}
          placeholder="Texto corrigido (aceita {{variaveis}})"
          rows={3}
        />
      </div>
    </BaseNode>
  );
}
