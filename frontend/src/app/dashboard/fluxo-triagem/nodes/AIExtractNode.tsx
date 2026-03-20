"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

interface Campo { label: string; variavel: string }

export default function AIExtractNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const campos: Campo[] = Array.isArray(data.campos) ? (data.campos as Campo[]) : [];

  const addCampo = () => {
    onChange?.({ campos: [...campos, { label: "", variavel: "" }] });
  };

  const removeCampo = (idx: number) => {
    onChange?.({ campos: campos.filter((_, i) => i !== idx) });
  };

  const setCampo = (idx: number, field: keyof Campo, val: string) => {
    const next = [...campos];
    next[idx] = { ...next[idx], [field]: val };
    onChange?.({ campos: next });
  };

  return (
    <BaseNode nodeType="aiExtract" {...props}>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Campos a extrair</p>
          <button type="button" onClick={addCampo}
            className="nodrag text-[9px] text-yellow-400 hover:text-yellow-300 font-bold border border-yellow-500/20 px-2 py-0.5 rounded-md">
            + Campo
          </button>
        </div>

        {campos.map((campo, idx) => (
          <div key={idx} className="flex gap-1.5 items-center bg-black/30 rounded-lg p-1.5 border border-white/5">
            <div className="flex-1 space-y-1">
              <input
                className="nodrag w-full bg-transparent text-[11px] text-white placeholder-slate-700 focus:outline-none border-b border-white/5 pb-0.5"
                value={campo.label}
                onChange={(e) => setCampo(idx, "label", e.target.value)}
                placeholder="Nome do campo (ex: CPF)"
              />
              <input
                className="nodrag w-full bg-transparent text-[10px] text-slate-500 placeholder-slate-700 focus:outline-none"
                value={campo.variavel}
                onChange={(e) => setCampo(idx, "variavel", e.target.value)}
                placeholder="Variável: ex. cpf_cliente"
              />
            </div>
            <button type="button" onClick={() => removeCampo(idx)}
              className="nodrag text-slate-700 hover:text-red-400 text-[10px]">✕</button>
          </div>
        ))}
      </div>
      <p className="text-[9px] text-yellow-900 mt-1">
        A IA extrai os dados da mensagem e salva como {"{{variavel}}"}.
      </p>
    </BaseNode>
  );
}
