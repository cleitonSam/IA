"use client";
import React, { useEffect, useState, useCallback } from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeTextarea } from "./BaseNode";

interface Team {
  id: number;
  name: string;
}

interface TransferTeamData {
  team_id?: number | string;
  team_name?: string;
  mensagem?: string;
  onChange?: (patch: Record<string, unknown>) => void;
}

const getToken = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
});

export default function TransferTeamNode(props: NodeProps) {
  const data = (props.data || {}) as TransferTeamData;
  const onChange = data.onChange as ((patch: Record<string, unknown>) => void) | undefined;

  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadTeams = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api-backend/management/chatwoot/teams", getToken());
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setTeams(Array.isArray(data) ? data : []);
    } catch (e: unknown) {
      setError("Não foi possível carregar os times.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTeams();
  }, [loadTeams]);

  const selectedTeamId = data.team_id ? String(data.team_id) : "";

  function handleTeamChange(val: string) {
    const team = teams.find((t) => String(t.id) === val);
    onChange?.({
      team_id: team ? team.id : undefined,
      team_name: team ? team.name : "",
    });
  }

  return (
    <BaseNode nodeType="transferTeam" {...props}>
      {/* Seletor de time */}
      <div className="space-y-1">
        <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest flex items-center justify-between">
          Time Chatwoot
          <button
            className="nodrag text-slate-600 hover:text-slate-400 transition-colors"
            title="Recarregar times"
            onClick={(e) => { e.stopPropagation(); loadTeams(); }}
          >
            ↻
          </button>
        </p>

        {loading ? (
          <p className="text-[10px] text-slate-500 italic px-2 py-1.5">Carregando times...</p>
        ) : error ? (
          <p className="text-[10px] text-red-400 px-2 py-1.5">{error}</p>
        ) : teams.length === 0 ? (
          <p className="text-[10px] text-slate-600 px-2 py-1.5">Nenhum time encontrado</p>
        ) : (
          <select
            className="nodrag w-full bg-black/40 border border-white/8 rounded-lg px-2 py-1.5 text-white text-[11px] focus:outline-none focus:border-white/20"
            value={selectedTeamId}
            onChange={(e) => handleTeamChange(e.target.value)}
          >
            <option value="">— Selecione o time —</option>
            {teams.map((t) => (
              <option key={t.id} value={String(t.id)}>
                {t.name}
              </option>
            ))}
          </select>
        )}

        {/* Preview do time selecionado */}
        {data.team_name && (
          <p className="text-[10px] text-emerald-400 px-1">
            ✓ Atribuirá ao time: <strong>{data.team_name}</strong>
          </p>
        )}
      </div>

      {/* Mensagem opcional de aviso */}
      <NodeTextarea
        label="Mensagem (opcional)"
        value={data.mensagem || ""}
        onChange={(v) => onChange?.({ mensagem: v })}
        placeholder="Ex: Encaminhando para o time Comercial! 🏢"
        rows={2}
      />

      <p className="text-[9px] text-blue-700 font-bold">
        ℹ️ A IA continua ativa. Use &ldquo;Transferir para Humano&rdquo; para pausar a IA.
      </p>
    </BaseNode>
  );
}
