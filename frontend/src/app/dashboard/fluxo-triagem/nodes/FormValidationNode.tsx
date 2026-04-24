"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

export default function FormValidationNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, any>;
  const onChange = props.data?.onChange as ((patch: Record<string, any>) => void) | undefined;
  return (
    <BaseNode nodeType="formValidation" {...props} customOutputHandles={[{ id: "valid", label: "✓ valido" }, { id: "invalid", label: "✗ invalido" }]}>
      <div className="space-y-1.5">
        <label className="block text-[10px] text-slate-400">Tipo</label>
        <select
          value={data.tipo || "email"}
          onChange={(e) => onChange?.({ tipo: e.target.value })}
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
        >
          <option value="email">Email</option>
          <option value="cpf">CPF</option>
          <option value="cnpj">CNPJ</option>
          <option value="telefone">Telefone BR</option>
        </select>
        <label className="block text-[10px] text-slate-400 mt-1">Valor a validar</label>
        <input
          type="text"
          placeholder="{{mensagem}} ou {{email_cliente}}"
          className="w-full text-[11px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.valor || "{{mensagem}}"}
          onChange={(e) => onChange?.({ valor: e.target.value })}
        />
        <label className="block text-[10px] text-slate-400 mt-1">Salvar resultado em</label>
        <input
          type="text"
          placeholder="_validation_ok"
          className="w-full text-[10px] bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100"
          value={data.variavel_resultado || "_validation_ok"}
          onChange={(e) => onChange?.({ variavel_resultado: e.target.value })}
        />
      </div>
    </BaseNode>
  );
}
