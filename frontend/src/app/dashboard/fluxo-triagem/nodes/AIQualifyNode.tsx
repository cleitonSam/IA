"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

export default function AIQualifyNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const perguntas: string[] = Array.isArray(data.perguntas) ? (data.perguntas as string[]) : [""];
  const variaveis: string[] = Array.isArray(data.variaveis) ? (data.variaveis as string[]) : [""];

  const setItem = (type: "perguntas" | "variaveis", idx: number, val: string) => {
    const next = type === "perguntas" ? [...perguntas] : [...variaveis];
    next[idx] = val;
    onChange?.({ [type]: next });
  };

  const addRow = () => {
    onChange?.({ perguntas: [...perguntas, ""], variaveis: [...variaveis, ""] });
  };

  const removeRow = (idx: number) => {
    onChange?.({
      perguntas: perguntas.filter((_, i) => i !== idx),
      variaveis: variaveis.filter((_, i) => i !== idx),
    });
  };

  return (
    <BaseNode nodeType="aiQualify" {...props}>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Perguntas</p>
          <button type="button" onClick={addRow}
            className="nodrag text-[9px] text-teal-400 hover:text-teal-300 font-bold border border-teal-500/20 px-2 py-0.5 rounded-md">
            + Adicionar
          </button>
        </div>

        {perguntas.map((perg, idx) => (
          <div key={idx} className="space-y-1 bg-black/30 rounded-lg p-2 border border-white/5">
            <div className="flex items-center gap-1">
              <span className="text-[9px] text-teal-400 font-black w-4">{idx + 1}</span>
              <input
                className="nodrag flex-1 bg-transparent text-[11px] text-white placeholder-slate-700 focus:outline-none"
                value={perg}
                onChange={(e) => setItem("perguntas", idx, e.target.value)}
                placeholder={`Pergunta ${idx + 1}`}
              />
              <button type="button" onClick={() => removeRow(idx)}
                className="nodrag text-slate-700 hover:text-red-400 text-[10px]">✕</button>
            </div>
            <input
              className="nodrag w-full bg-black/40 border border-white/5 rounded px-2 py-1 text-[10px] text-slate-400 placeholder-slate-700 focus:outline-none"
              value={variaveis[idx] || ""}
              onChange={(e) => setItem("variaveis", idx, e.target.value)}
              placeholder={`Variável: ex. nome_lead`}
            />
          </div>
        ))}
      </div>
      <p className="text-[9px] text-teal-900">
        A IA envia cada pergunta em sequência. Respostas salvas em {"{{variavel}}"}.
      </p>
    </BaseNode>
  );
}
