"use client";
import React from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { NODE_CONFIG, NODE_BASE_CLASS } from "./nodeStyles";

const DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];

interface DiaHorario { ativo: boolean; inicio: string; fim: string }
type Horarios = Record<string, DiaHorario>;

const DEFAULT_HORARIOS: Horarios = {
  "0": { ativo: true,  inicio: "08:00", fim: "18:00" },
  "1": { ativo: true,  inicio: "08:00", fim: "18:00" },
  "2": { ativo: true,  inicio: "08:00", fim: "18:00" },
  "3": { ativo: true,  inicio: "08:00", fim: "18:00" },
  "4": { ativo: true,  inicio: "08:00", fim: "18:00" },
  "5": { ativo: true,  inicio: "08:00", fim: "13:00" },
  "6": { ativo: false, inicio: "00:00", fim: "00:00" },
};

export default function BusinessHoursNode(props: NodeProps) {
  const { selected } = props;
  const cfg = NODE_CONFIG["businessHours"];
  const data = (props.data || {}) as Record<string, unknown>;
  const onChange = props.data?.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const horarios: Horarios = (data.horarios as Horarios) || DEFAULT_HORARIOS;

  const updateDia = (dia: string, field: keyof DiaHorario, value: string | boolean) => {
    const next = { ...horarios, [dia]: { ...horarios[dia], [field]: value } };
    onChange?.({ horarios: next });
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
      }}
    >
      <Handle type="target" position={Position.Left}
        style={{ background: cfg.border, width: 10, height: 10, border: `2px solid ${cfg.border}`, boxShadow: `0 0 6px ${cfg.border}` }} />

      <div className="flex items-center gap-2 px-3 py-2" style={{ background: cfg.headerBg }}>
        <span className="text-base">🕐</span>
        <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: cfg.headerText }}>
          Horário Comercial
        </span>
      </div>

      <div className="p-3 space-y-2">
        {/* Dias da semana */}
        {DIAS.map((nome, i) => {
          const key = String(i);
          const dia = horarios[key] || { ativo: false, inicio: "08:00", fim: "18:00" };
          return (
            <div key={key} className={`flex items-center gap-1.5 rounded-lg px-2 py-1 border ${dia.ativo ? "border-sky-500/20 bg-sky-500/5" : "border-white/5 bg-black/20"}`}>
              <button type="button"
                onClick={() => updateDia(key, "ativo", !dia.ativo)}
                className={`nodrag w-4 h-4 rounded border transition-all flex-shrink-0 ${
                  dia.ativo ? "bg-sky-500 border-sky-400" : "bg-transparent border-slate-600"
                }`}
              />
              <span className={`text-[10px] font-bold w-12 ${dia.ativo ? "text-sky-300" : "text-slate-600"}`}>
                {nome.substring(0, 3)}
              </span>
              {dia.ativo ? (
                <div className="flex items-center gap-1 flex-1">
                  <input type="time" className="nodrag bg-black/40 border border-white/8 rounded px-1.5 py-0.5 text-white text-[10px] focus:outline-none w-[70px]"
                    value={dia.inicio} onChange={(e) => updateDia(key, "inicio", e.target.value)} />
                  <span className="text-slate-600 text-[9px]">–</span>
                  <input type="time" className="nodrag bg-black/40 border border-white/8 rounded px-1.5 py-0.5 text-white text-[10px] focus:outline-none w-[70px]"
                    value={dia.fim} onChange={(e) => updateDia(key, "fim", e.target.value)} />
                </div>
              ) : (
                <span className="text-[9px] text-slate-700 flex-1">Fechado</span>
              )}
            </div>
          );
        })}

        {/* Timezone */}
        <div className="space-y-1">
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Fuso Horário</p>
          <input className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] placeholder-slate-700 focus:outline-none focus:border-white/20"
            value={(data.fusoHorario as string) || "America/Sao_Paulo"}
            onChange={(e) => onChange?.({ fusoHorario: e.target.value })}
            placeholder="America/Sao_Paulo" />
        </div>

        {/* Handles aberto/fechado */}
        <div className="space-y-1.5 mt-1">
          <div className="relative flex items-center bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-2 py-1.5">
            <span className="text-[10px] text-emerald-400 font-bold flex-1">✅ Aberto</span>
            <Handle type="source" position={Position.Right} id="aberto"
              style={{ background: "#22c55e", width: 10, height: 10, border: "2px solid #22c55e", boxShadow: "0 0 6px #22c55e", right: -12, top: "50%" }} />
          </div>
          <div className="relative flex items-center bg-red-500/10 border border-red-500/20 rounded-lg px-2 py-1.5">
            <span className="text-[10px] text-red-400 font-bold flex-1">🔴 Fechado</span>
            <Handle type="source" position={Position.Right} id="fechado"
              style={{ background: "#ef4444", width: 10, height: 10, border: "2px solid #ef4444", boxShadow: "0 0 6px #ef4444", right: -12, top: "50%" }} />
          </div>
        </div>

        <p className="text-[9px] text-sky-900">
          Roteia baseado no horário atual. Configure os dias e horários de funcionamento.
        </p>
      </div>
    </div>
  );
}
