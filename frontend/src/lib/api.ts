/**
 * api.ts — Cliente axios centralizado para o Motor SaaS IA.
 *
 * Uso:
 *   import { api } from "@/lib/api";
 *   const faqs = await api.get("/management/faq");
 *   await api.post("/management/faq", body);
 *
 * Todos os endpoints são relativos ao prefixo /api-backend.
 * O token Bearer é injetado automaticamente via interceptor.
 */
import axios, { AxiosError, AxiosInstance, AxiosResponse } from "axios";

// ─── Tipos de erro padronizado ────────────────────────────────────────────────
export interface ApiError {
  status: number;
  message: string;
  detail?: string;
}

export class ApiException extends Error {
  status: number;
  detail?: string;

  constructor(err: ApiError) {
    super(err.message);
    this.status = err.status;
    this.detail = err.detail;
  }
}

// ─── Mensagens de erro amigáveis por código HTTP ──────────────────────────────
function friendlyMessage(status: number, fallback?: string): string {
  const map: Record<number, string> = {
    400: "Dados inválidos. Verifique os campos e tente novamente.",
    401: "Sessão expirada. Faça login novamente.",
    403: "Você não tem permissão para esta ação.",
    404: "Registro não encontrado.",
    409: "Conflito: este registro já existe.",
    422: "Os dados enviados não são válidos.",
    429: "Muitas requisições. Aguarde um momento.",
    500: "Erro interno do servidor. Tente novamente em instantes.",
    502: "Serviço temporariamente indisponível.",
    503: "Serviço em manutenção. Tente novamente em breve.",
  };
  return map[status] ?? fallback ?? "Erro inesperado. Tente novamente.";
}

// ─── Factory do cliente ───────────────────────────────────────────────────────
function createApiClient(): AxiosInstance {
  const client = axios.create({
    baseURL: "/api-backend",
    timeout: 30_000,
    headers: { "Content-Type": "application/json" },
  });

  // Request: injeta Bearer token
  client.interceptors.request.use((config) => {
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  // Response: normaliza erros em ApiException
  client.interceptors.response.use(
    (res: AxiosResponse) => res,
    (err: AxiosError<{ detail?: string; message?: string }>) => {
      const status = err.response?.status ?? 0;
      const serverDetail =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message;

      if (status === 401) {
        // Token inválido — limpa sessão e redireciona
        if (typeof window !== "undefined") {
          localStorage.removeItem("token");
          window.location.href = "/login";
        }
      }

      throw new ApiException({
        status,
        message: friendlyMessage(status, serverDetail),
        detail: serverDetail,
      });
    }
  );

  return client;
}

export const api = createApiClient();

// ─── Helpers de conveniência (retornam .data diretamente) ────────────────────
export const apiGet = <T = unknown>(url: string, params?: object): Promise<T> =>
  api.get<T>(url, { params }).then((r) => r.data);

export const apiPost = <T = unknown>(url: string, body?: unknown): Promise<T> =>
  api.post<T>(url, body).then((r) => r.data);

export const apiPut = <T = unknown>(url: string, body?: unknown): Promise<T> =>
  api.put<T>(url, body).then((r) => r.data);

export const apiDelete = <T = unknown>(url: string): Promise<T> =>
  api.delete<T>(url).then((r) => r.data);
