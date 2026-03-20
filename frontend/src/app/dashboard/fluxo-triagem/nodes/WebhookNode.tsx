"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput } from "./BaseNode";

export default function WebhookNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const method = (data.method as string) || "POST";
  const bodyObj: Record<string, string> = (data.body as Record<string, string>) || {};
  const bodyKeys = Object.keys(bodyObj);

  const addBodyField = () => {
    onChange?.({ body: { ...bodyObj, "": "" } });
  };

  const setBodyField = (oldKey: string, newKey: string, value: string) => {
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries(bodyObj)) {
      if (k === oldKey) next[newKey] = value;
      else next[k] = v as string;
    }
    onChange?.({ body: next });
  };

  const removeBodyField = (key: string) => {
    const next = { ...bodyObj };
    delete next[key];
    onChange?.({ body: next });
  };

  return (
    <BaseNode nodeType="webhook" {...props}>
      {/* Método */}
      <div className="flex gap-1.5">
        {(["POST", "GET"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => onChange?.({ method: m })}
            className={`nodrag flex-1 py-1 rounded-lg text-[9px] font-black uppercase tracking-wider border transition-all ${
              method === m ? "bg-lime-500/20 text-lime-300 border-lime-500/60" : "bg-black/20 text-slate-600 border-white/5"
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      <NodeInput
        label="URL"
        value={(data.url as string) || ""}
        onChange={(v) => onChange?.({ url: v })}
        placeholder="https://seu-crm.com/webhook"
        type="url"
      />

      {/* Body dinâmico */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Body / Params</p>
          <button type="button" onClick={addBodyField}
            className="nodrag text-[9px] text-lime-400 hover:text-lime-300 font-bold border border-lime-500/20 px-2 py-0.5 rounded-md">
            + Campo
          </button>
        </div>
        {bodyKeys.map((key) => (
          <div key={key} className="flex gap-1 items-center">
            <input
              className="nodrag flex-1 bg-black/40 border border-white/5 rounded px-1.5 py-1 text-[10px] text-slate-300 placeholder-slate-700 focus:outline-none"
              value={key}
              onChange={(e) => setBodyField(key, e.target.value, bodyObj[key])}
              placeholder="chave"
            />
            <input
              className="nodrag flex-1 bg-black/40 border border-white/5 rounded px-1.5 py-1 text-[10px] text-white placeholder-slate-700 focus:outline-none"
              value={bodyObj[key]}
              onChange={(e) => setBodyField(key, key, e.target.value)}
              placeholder="{{variavel}}"
            />
            <button type="button" onClick={() => removeBodyField(key)}
              className="nodrag text-slate-700 hover:text-red-400 text-[10px]">✕</button>
          </div>
        ))}
      </div>
      <p className="text-[9px] text-lime-900">Use {"{{phone}}"}, {"{{variavel}}"} no body.</p>
    </BaseNode>
  );
}
