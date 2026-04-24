"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

type Variant = { handle: string; weight: number; label: string };

export default function AbTestSplitNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  const variants: Variant[] = Array.isArray(data.variants) ? data.variants : [
    { handle: "a", weight: 50, label: "A" },
    { handle: "b", weight: 50, label: "B" },
  ];
  const total = variants.reduce((s, v) => s + (v.weight || 0), 0) || 1;

  const update = (i: number, patch: Partial<Variant>) => {
    const next = variants.map((v, idx) => (idx === i ? { ...v, ...patch } : v));
    onChange?.({ variants: next });
  };
  const add = () => {
    const ch = String.fromCharCode(97 + variants.length); // c, d, e...
    onChange?.({ variants: [...variants, { handle: ch, weight: 0, label: ch.toUpperCase() }] });
  };
  const remove = (i: number) => onChange?.({ variants: variants.filter((_, idx) => idx !== i) });

  const outputHandles = variants.map((v) => ({ id: v.handle, label: v.label || v.handle }));

  return (
    <BaseNode nodeType="abTestSplit" {...props} customOutputHandles={outputHandles}>
      <div className="space-y-1.5">
        <input
          type="text"
          placeholder="Variável onde salvar (ex: _ab_variant)"
          className="w-full text-[10px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.variavel || "_ab_variant"}
          onChange={(e) => onChange?.({ variavel: e.target.value })}
        />
        <div className="space-y-1">
          {variants.map((v, i) => {
            const pct = Math.round(((v.weight || 0) / total) * 100);
            return (
              <div key={i} className="flex gap-1 items-center">
                <input
                  type="text"
                  placeholder="Label"
                  className="flex-1 text-[10px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
                  value={v.label}
                  onChange={(e) => update(i, { label: e.target.value, handle: e.target.value.toLowerCase().replace(/[^a-z0-9]/g, "") || v.handle })}
                />
                <input
                  type="number" min={0} max={100}
                  className="w-14 text-[10px] bg-slate-800 border border-slate-700 rounded px-1 py-1 text-slate-100"
                  value={v.weight}
                  onChange={(e) => update(i, { weight: parseInt(e.target.value) || 0 })}
                />
                <span className="text-[10px] text-slate-500 w-10">{pct}%</span>
                <button onClick={() => remove(i)} className="text-red-400 text-[10px] px-1">✕</button>
              </div>
            );
          })}
          <button onClick={add} className="text-[10px] text-sky-400">+ variante</button>
        </div>
        <p className="text-[9px] text-slate-600">Hash do telefone mantém mesmo usuário sempre na mesma variante.</p>
      </div>
    </BaseNode>
  );
}
