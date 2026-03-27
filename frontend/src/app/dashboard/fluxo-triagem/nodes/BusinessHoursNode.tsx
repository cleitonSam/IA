"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";

const DIAS = [
  { key: "0", label: "Seg" },
  { key: "1", label: "Ter" },
  { key: "2", label: "Qua" },
  { key: "3", label: "Qui" },
  { key: "4", label: "Sex" },
  { key: "5", label: "Sab" },
  { key: "6", label: "Dom" },
];

const FUSOS = [
  { id: "America/Sao_Paulo", label: "Brasilia" },
  { id: "America/Manaus", label: "Manaus (-1h)" },
  { id: "America/Bahia", label: "Bahia" },
  { id: "America/Fortaleza", label: "Fortaleza" },
  { id: "America/Recife", label: "Recife" },
];

interface HorarioDia {
  ativo: boolean;
  inicio: string;
  fim: string;
}

export default function BusinessHoursNode(props: NodeProps) {
  const { data, selected } = props;
  const cfg = NODE_CONFIG["businessHours"];
  const onChange = data.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const modo: string = (data.modo as string) || "global";
  const fusoHorario: string = (data.fusoHorario as string) || "America/Sao_Paulo";
  const horarios = (data.horarios as Record<string, HorarioDia>) || {};

  const setModo = (m: string) => onChange?.({ modo: m });
  const setFuso = (f: string) => onChange?.({ fusoHorario: f });
  const setDia = (key: string, patch: Partial<HorarioDia>) => {
    const current = horarios[key] || { ativo: false, inicio: "08:00", fim: "18:00" };
    onChange?.({
      horarios: { ...horarios, [key]: { ...current, ...patch } },
    });
  };

  return (
    <div
      className={NODE_BASE_CLASS}
      style={{
        border: selected ? `2px solid ${cfg.border}` : `1px solid ${cfg.border}55`,
        background: "#0f172a",
        boxShadow: selected ? `0 0 20px ${cfg.border}55` : `0 4px 20px rgba(0,0,0,0.5)`,
        position: "relative",
        minWidth: 260,
        maxWidth: 300,
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: cfg.border, width: 10, height: 10, border: `2px solid ${cfg.border}`, boxShadow: `0 0 6px ${cfg.border}` }}
      />

      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2" style={{ background: cfg.headerBg }}>
        <span className="text-base">🕐</span>
        <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
          Horario Comercial
        </span>
      </div>

      {/* Body */}
      <div className="p-3 space-y-2.5">
        {/* Modo: global vs custom */}
        <div className="flex gap-1.5">
          {(["global", "custom"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setModo(m)}
              className={`nodrag flex-1 py-1.5 rounded-lg text-[9px] font-black uppercase tracking-wider border transition-all ${
                modo === m
                  ? "bg-sky-500/15 text-sky-300 border-sky-500/30"
                  : "bg-black/20 text-slate-600 border-white/5 hover:text-slate-400"
              }`}
            >
              {m === "global" ? "Global" : "Customizado"}
            </button>
          ))}
        </div>

        {modo === "global" ? (
          <p className="text-[9px] text-slate-500 leading-relaxed">
            Usa o horario configurado em{" "}
            <span className="text-sky-400 font-bold">Personalidade → Horarios</span>.
          </p>
        ) : (
          <>
            {/* Fuso horario */}
            <div className="space-y-1">
              <p className="text-[8px] font-black text-slate-600 uppercase tracking-widest">Fuso</p>
              <select
                value={fusoHorario}
                onChange={(e) => setFuso(e.target.value)}
                className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1 text-[10px] text-white focus:outline-none focus:border-white/20"
              >
                {FUSOS.map((f) => (
                  <option key={f.id} value={f.id}>{f.label}</option>
                ))}
              </select>
            </div>

            {/* Dias da semana */}
            <div className="space-y-1">
              {DIAS.map(({ key, label }) => {
                const dia = horarios[key] || { ativo: false, inicio: "08:00", fim: "18:00" };
                return (
                  <div key={key} className="flex items-center gap-1.5">
                    {/* Toggle */}
                    <button
                      type="button"
                      onClick={() => setDia(key, { ativo: !dia.ativo })}
                      className={`nodrag relative inline-flex h-4 w-7 items-center rounded-full transition-all flex-shrink-0 ${
                        dia.ativo ? "bg-sky-500" : "bg-slate-700"
                      }`}
                    >
                      <span className={`inline-block h-3 w-3 rounded-full bg-white transition-all shadow ${
                        dia.ativo ? "translate-x-3.5" : "translate-x-0.5"
                      }`} />
                    </button>

                    {/* Label */}
                    <span className={`text-[10px] font-bold w-7 ${dia.ativo ? "text-white" : "text-slate-600"}`}>
                      {label}
                    </span>

                    {dia.ativo ? (
                      <div className="flex items-center gap-1 flex-1">
                        <input
                          type="time"
                          value={dia.inicio}
                          onChange={(e) => setDia(key, { inicio: e.target.value })}
                          className="nodrag bg-black/40 border border-white/8 rounded px-1 py-0.5 text-[9px] text-white focus:outline-none focus:border-sky-500/40 w-[62px]"
                        />
                        <span className="text-slate-600 text-[9px]">-</span>
                        <input
                          type="time"
                          value={dia.fim}
                          onChange={(e) => setDia(key, { fim: e.target.value })}
                          className="nodrag bg-black/40 border border-white/8 rounded px-1 py-0.5 text-[9px] text-white focus:outline-none focus:border-sky-500/40 w-[62px]"
                        />
                      </div>
                    ) : (
                      <span className="text-[9px] text-slate-700 uppercase tracking-widest">Fechado</span>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* Handles aberto / fechado */}
        <div className="space-y-1.5 mt-1 pt-2 border-t border-white/5">
          <div className="relative flex items-center bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-2 py-1.5">
            <span className="text-[10px] text-emerald-400 font-bold flex-1">Aberto</span>
            <Handle
              type="source"
              position={Position.Right}
              id="aberto"
              style={{ background: "#22c55e", width: 10, height: 10, border: "2px solid #22c55e", boxShadow: "0 0 6px #22c55e", right: -12, top: "50%" }}
            />
          </div>
          <div className="relative flex items-center bg-red-500/10 border border-red-500/20 rounded-lg px-2 py-1.5">
            <span className="text-[10px] text-red-400 font-bold flex-1">Fechado</span>
            <Handle
              type="source"
              position={Position.Right}
              id="fechado"
              style={{ background: "#ef4444", width: 10, height: 10, border: "2px solid #ef4444", boxShadow: "0 0 6px #ef4444", right: -12, top: "50%" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
