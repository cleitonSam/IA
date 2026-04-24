"use client";
import React, { useState } from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput, NodeTextarea } from "./BaseNode";

interface MenuOpcao { id: string; titulo: string; descricao?: string }

export default function SendMenuNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;
  const opcoes: MenuOpcao[] = Array.isArray(data.opcoes) ? (data.opcoes as MenuOpcao[]) : [];
  const tipo = (data.tipo as string) || "list";
  const [showIgPreview, setShowIgPreview] = useState(false);

  // Preview de como o menu aparece no Instagram (texto numerado)
  const igPreviewLines = [
    (data.titulo as string) ? `*${data.titulo}*` : "",
    (data.texto as string) || "",
    "",
    ...opcoes.map((o, i) => `${i + 1} - ${o.titulo || "(sem título)"}`),
    opcoes.length > 0 ? "" : "",
    opcoes.length > 0 ? "_Responda com o numero da opcao_" : "",
    (data.rodape as string) ? `_${data.rodape}_` : "",
  ].filter(Boolean).join("\n");

  const setOpcao = (idx: number, field: keyof MenuOpcao, val: string) => {
    const next = [...opcoes];
    next[idx] = { ...next[idx], [field]: val };
    onChange?.({ opcoes: next });
  };

  const addOpcao = () => {
    onChange?.({ opcoes: [...opcoes, { id: String(Date.now()), titulo: "", descricao: "" }] });
  };

  const removeOpcao = (idx: number) => {
    onChange?.({ opcoes: opcoes.filter((_, i) => i !== idx) });
  };

  return (
    <BaseNode nodeType="sendMenu" {...props}>
      {/* Badge multi-canal */}
      <div className="flex items-center gap-1.5 bg-gradient-to-r from-fuchsia-500/10 to-blue-500/10 border border-fuchsia-500/20 rounded-md px-2 py-1">
        <span className="text-[9px] font-bold text-fuchsia-300">📱 Multi-canal</span>
        <span className="text-[9px] text-slate-400">WhatsApp + Instagram</span>
      </div>

      {/* Tipo */}
      <div className="flex gap-1.5">
        {(["list", "button"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => onChange?.({ tipo: t })}
            className={`nodrag flex-1 py-1 rounded-lg text-[9px] font-black uppercase tracking-wider border transition-all ${
              tipo === t ? "bg-blue-500/20 text-blue-300 border-blue-500/60" : "bg-black/20 text-slate-600 border-white/5"
            }`}
          >
            {t === "list" ? "📋 Lista" : "🔘 Botões"}
          </button>
        ))}
      </div>

      <NodeInput
        label="Título"
        value={(data.titulo as string) || ""}
        onChange={(v) => onChange?.({ titulo: v })}
        placeholder="Ex: Atendimento"
      />
      <NodeTextarea
        label="Mensagem"
        value={(data.texto as string) || ""}
        onChange={(v) => onChange?.({ texto: v })}
        placeholder="Ex: Olá, {{nome}}! Como posso ajudar?"
        rows={2}
      />
      <NodeInput
        label="Rodapé"
        value={(data.rodape as string) || ""}
        onChange={(v) => onChange?.({ rodape: v })}
        placeholder="Ex: Escolha uma opção"
      />
      {tipo === "list" && (
        <NodeInput
          label="Texto do botão"
          value={(data.botao as string) || ""}
          onChange={(v) => onChange?.({ botao: v })}
          placeholder="Ex: Ver opções"
        />
      )}

      {/* Opções */}
      <div className="space-y-1.5 mt-1">
        <div className="flex items-center justify-between">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">
            Opções ({opcoes.length})
          </p>
          <button
            type="button"
            onClick={addOpcao}
            className="nodrag text-[9px] text-blue-400 hover:text-blue-300 font-bold border border-blue-500/20 hover:border-blue-500/40 px-2 py-0.5 rounded-md"
          >
            + Adicionar
          </button>
        </div>
        <div className="space-y-1.5 max-h-[200px] overflow-y-auto pr-1 nodrag">
          {opcoes.map((op, idx) => (
            <div key={op.id} className="flex gap-1.5 items-start bg-black/30 rounded-lg p-1.5 border border-white/5">
              <span className="text-[9px] text-blue-400 font-black w-4 mt-0.5">{idx + 1}</span>
              <div className="flex-1 flex flex-col gap-1">
                <input
                  className="nodrag w-full bg-transparent text-[11px] text-white placeholder-slate-700 focus:outline-none"
                  value={op.titulo}
                  onChange={(e) => setOpcao(idx, "titulo", e.target.value)}
                  placeholder="Título da opção"
                />
                {tipo === "list" && (
                  <input
                    className="nodrag w-full bg-transparent text-[10px] text-slate-400 placeholder-slate-700 focus:outline-none border-t border-white/5 pt-0.5"
                    value={op.descricao || ""}
                    onChange={(e) => setOpcao(idx, "descricao", e.target.value)}
                    placeholder="Descrição (opcional)"
                  />
                )}
              </div>
              <button type="button" onClick={() => removeOpcao(idx)} className="nodrag text-slate-700 hover:text-red-400 text-[10px] transition-colors mt-0.5">✕</button>
            </div>
          ))}
        </div>
      </div>

      {tipo === "button" && opcoes.length > 3 && (
        <p className="text-[9px] text-red-400 font-bold">⚠️ Máx. 3 botões no WhatsApp</p>
      )}

      {/* Preview Instagram — mostra como o menu vai aparecer no IG */}
      <button
        type="button"
        onClick={() => setShowIgPreview((v) => !v)}
        className="nodrag w-full text-[9px] text-fuchsia-300/80 hover:text-fuchsia-300 font-bold border border-fuchsia-500/20 hover:border-fuchsia-500/40 rounded-md px-2 py-1 mt-1 text-left transition-colors"
      >
        {showIgPreview ? "▼" : "▶"} 📸 Preview Instagram (texto numerado)
      </button>
      {showIgPreview && (
        <div className="nodrag bg-black/40 border border-fuchsia-500/10 rounded-md p-2 mt-1">
          <pre className="text-[10px] text-slate-300 whitespace-pre-wrap font-mono leading-relaxed">
{igPreviewLines || "(preencha título/texto/opções pra ver o preview)"}
          </pre>
          <p className="text-[8px] text-slate-500 mt-1.5 italic">
            No Instagram, botões viram lista numerada. Cliente responde com o número.
          </p>
        </div>
      )}
    </BaseNode>
  );
}
