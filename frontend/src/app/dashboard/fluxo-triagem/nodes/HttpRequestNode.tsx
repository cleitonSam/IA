"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

export default function HttpRequestNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  const responseMap = data.response_map || {};
  const headers = data.headers || {};
  const authType = data.auth_type || "none";

  const updateMap = (key: string, val: string) => onChange?.({ response_map: { ...responseMap, [key]: val } });
  const removeMap = (key: string) => {
    const next = { ...responseMap };
    delete next[key];
    onChange?.({ response_map: next });
  };

  return (
    <BaseNode nodeType="httpRequest" {...props} customOutputHandles={["success", "error"]}>
      <div className="space-y-1.5">
        <div className="flex gap-1">
          <select
            value={data.method || "GET"}
            onChange={(e) => onChange?.({ method: e.target.value })}
            className="text-[11px] bg-slate-800 border border-slate-700 rounded px-1.5 py-1 text-slate-100"
          >
            <option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option>
          </select>
          <input
            type="text"
            placeholder="https://api.exemplo.com/v1/endpoint"
            className="flex-1 text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
            value={data.url || ""}
            onChange={(e) => onChange?.({ url: e.target.value })}
          />
        </div>

        <label className="block text-[10px] text-slate-400 mt-1">Autenticacao</label>
        <select
          value={authType}
          onChange={(e) => onChange?.({ auth_type: e.target.value })}
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
        >
          <option value="none">Nenhuma</option>
          <option value="bearer">Bearer token</option>
          <option value="basic">Basic (user/pass)</option>
        </select>
        {authType === "bearer" && (
          <input
            type="text"
            placeholder="Token (ex: {{api_token}})"
            className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
            value={data.auth_token || ""}
            onChange={(e) => onChange?.({ auth_token: e.target.value })}
          />
        )}
        {authType === "basic" && (
          <>
            <input type="text" placeholder="usuario" className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
              value={data.auth_user || ""} onChange={(e) => onChange?.({ auth_user: e.target.value })} />
            <input type="password" placeholder="senha" className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100 mt-1"
              value={data.auth_password || ""} onChange={(e) => onChange?.({ auth_password: e.target.value })} />
          </>
        )}

        <NodeTextarea
          label="Headers (JSON)"
          value={typeof headers === "string" ? headers : JSON.stringify(headers, null, 2)}
          onChange={(v) => {
            try {
              onChange?.({ headers: JSON.parse(v || "{}") });
            } catch {
              onChange?.({ headers: v });
            }
          }}
          placeholder='{"X-API-Key": "{{api_key}}"}'
          rows={2}
        />

        <NodeTextarea
          label="Body (JSON, aceita {{vars}})"
          value={typeof data.body === "string" ? data.body : JSON.stringify(data.body || {}, null, 2)}
          onChange={(v) => {
            try {
              onChange?.({ body: JSON.parse(v || "{}") });
            } catch {
              onChange?.({ body: v });
            }
          }}
          placeholder='{"phone": "{{phone}}", "name": "{{nome}}"}'
          rows={3}
        />

        <label className="block text-[10px] text-slate-400 mt-1">
          Mapear resposta (variavel = caminho.no.json)
        </label>
        <div className="space-y-1">
          {Object.entries(responseMap).map(([k, v]: [string, any]) => (
            <div key={k} className="flex gap-1 items-center">
              <span className="text-[10px] text-sky-300 min-w-[60px]">{k}</span>
              <input
                type="text"
                value={String(v)}
                onChange={(e) => updateMap(k, e.target.value)}
                className="flex-1 text-[10px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
              />
              <button onClick={() => removeMap(k)} className="text-[10px] text-red-400">✕</button>
            </div>
          ))}
          <button
            onClick={() => {
              const name = prompt("Nome da variavel:");
              if (name) updateMap(name, "");
            }}
            className="text-[10px] text-sky-400 hover:text-sky-300"
          >+ adicionar campo</button>
        </div>

        <label className="block text-[10px] text-slate-400 mt-1">Timeout (s)</label>
        <input
          type="number"
          min={1}
          max={60}
          value={data.timeout || 15}
          onChange={(e) => onChange?.({ timeout: parseInt(e.target.value) || 15 })}
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
        />

        <p className="text-[9px] text-slate-600 mt-1">
          Handles: "success" (2xx) e "error". Status no {"{{_http_last_status}}"}
        </p>
      </div>
    </BaseNode>
  );
}
