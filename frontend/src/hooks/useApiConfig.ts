"use client";

/**
 * Hook que centraliza a leitura de token e empresaId do localStorage
 * e retorna a config de Authorization para axios/fetch.
 *
 * Uso:
 *   const { token, empresaId, config } = useApiConfig();
 *   await axios.get("/api-backend/endpoint", config);
 */
export function useApiConfig() {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const empresaId =
    typeof window !== "undefined" ? localStorage.getItem("empresaId") : null;
  const config = { headers: { Authorization: `Bearer ${token}` } };
  return { token, empresaId, config };
}

/**
 * Função standalone (não-hook) para uso fora de componentes React.
 * Ex.: em funções de callback que não podem usar hooks.
 */
export function getApiConfig() {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const empresaId =
    typeof window !== "undefined" ? localStorage.getItem("empresaId") : null;
  const config = { headers: { Authorization: `Bearer ${token}` } };
  return { token, empresaId, config };
}
