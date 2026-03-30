/**
 * types/index.ts — Tipos compartilhados do Motor SaaS IA.
 *
 * Source of truth para todas as entidades usadas nas páginas do dashboard.
 * Espelha os Pydantic models do backend (management.py / dashboard.py).
 */

// ─── Entidades base ───────────────────────────────────────────────────────────

export interface Empresa {
  id: number;
  nome: string;
  slug?: string;
}

export interface Unidade {
  id: number;
  empresa_id: number;
  nome: string;
  nome_abreviado?: string;
  slug?: string;
  ativa: boolean;
  descricao?: string;
  endereco?: string;
  cidade?: string;
  estado?: string;
  telefone_principal?: string;
  horarios?: string;
  modalidades?: string;
  planos?: Record<string, unknown>;
  formas_pagamento?: Record<string, unknown>;
  convenios?: Record<string, unknown>;
  infraestrutura?: Record<string, unknown>;
  servicos?: Record<string, unknown>;
  palavras_chave?: string[];
  link_matricula?: string;
  link_tour_virtual?: string;
  foto_grade?: string;
  site?: string;
  instagram?: string;
  created_at?: string;
  updated_at?: string;
}

export interface FAQItem {
  id?: number;
  empresa_id?: number;
  pergunta: string;
  resposta: string;
  unidade_id: number | null;
  todas_unidades: boolean;
  prioridade: number;
  ativo: boolean;
  visualizacoes?: number;
  unidades_ids?: number[];
  created_at?: string;
  updated_at?: string;
}

export interface Plano {
  id?: number;
  empresa_id?: number;
  nome: string;
  valor: number | null;
  valor_promocional: number | null;
  meses_promocionais: number | null;
  descricao: string;
  diferenciais: string;
  link_venda: string;
  unidade_id: number | null;
  unidade_nome?: string;
  ativo: boolean;
  ordem: number;
  id_externo?: string;
  created_at?: string;
  updated_at?: string;
}

export interface Integracao {
  id?: number;
  empresa_id?: number;
  tipo: string;
  config: Record<string, unknown>;
  ativo: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface PersonalidadeIA {
  id?: number;
  empresa_id?: number;
  nome: string;
  nome_agente?: string;
  instrucoes_base?: string;
  tom_voz?: string;
  estilo_comunicacao?: string;
  saudacao_personalizada?: string;
  regras_atendimento?: string;
  modelo?: string;
  temperatura?: number;
  max_tokens?: number;
  ativo: boolean;
  usar_emoji?: boolean;
  horario_atendimento_ia?: HorarioAtendimento | null;
  horario_comercial?: Record<string, unknown> | null;
  menu_triagem?: Record<string, unknown> | null;
  esta_no_horario?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface HorarioAtendimento {
  tipo: "dia_todo" | "horario_especifico";
  dias: Record<
    "segunda" | "terca" | "quarta" | "quinta" | "sexta" | "sabado" | "domingo",
    Array<{ inicio: string; fim: string }>
  >;
}

export interface FAQTemplate {
  id?: number;
  empresa_id?: number;
  titulo: string;
  perguntas: FAQItem[];
}

export interface FollowupTemplate {
  id?: number;
  empresa_id?: number;
  nome: string;
  mensagem: string;
  delay_horas: number;
  ativo: boolean;
}

export interface Conversa {
  id: number;
  conversation_id: number;
  account_id?: number;
  contato_id?: number;
  contato_nome?: string;
  contato_fone?: string;
  empresa_id: number;
  unidade_id?: number;
  unidade_nome?: string;
  canal?: string;
  status?: string;
  primeira_mensagem?: string;
  primeira_resposta_em?: string;
  ultima_mensagem?: string;
  total_mensagens_cliente?: number;
  total_mensagens_ia?: number;
  lead_qualificado?: boolean;
  score_lead?: number;
  score_interesse?: number;
  intencao_de_compra?: boolean;
  resumo_ia?: string;
  created_at?: string;
  updated_at?: string;
}

// ─── Respostas paginadas ──────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  page_size: number;
}

// ─── Resposta padrão de mutação ───────────────────────────────────────────────

export interface MutationResponse {
  status: "success" | "error";
  message?: string;
}

// ─── Métricas ─────────────────────────────────────────────────────────────────

export interface MetricasDiarias {
  data: string;
  total_conversas: number;
  conversas_encerradas: number;
  novos_contatos: number;
  total_mensagens: number;
  total_mensagens_ia: number;
  leads_qualificados: number;
  taxa_conversao: number;
  tempo_medio_resposta: number;
}
