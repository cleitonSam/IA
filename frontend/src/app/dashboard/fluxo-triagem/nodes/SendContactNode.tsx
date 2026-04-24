"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

export default function SendContactNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  return (
    <BaseNode nodeType="sendContact" {...props}>
      <div className="space-y-1.5">
        <input
          type="text"
          placeholder="Nome do contato"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.contact_name || ""}
          onChange={(e) => onChange?.({ contact_name: e.target.value })}
        />
        <input
          type="text"
          placeholder="Telefone (ex: 5511999999999)"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.contact_phone || ""}
          onChange={(e) => onChange?.({ contact_phone: e.target.value })}
        />
        <p className="text-[9px] text-slate-600">
          Envia vCard. Use DDI+DDD+numero (so digitos).
        </p>
      </div>
    </BaseNode>
  );
}
