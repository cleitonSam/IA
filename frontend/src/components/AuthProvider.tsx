"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import axios from "axios";

/**
 * AuthProvider — interceptor global de autenticação.
 *
 * Qualquer chamada axios que retorne 401 (token expirado/inválido)
 * limpa o token do localStorage e redireciona para /login.
 * Páginas públicas (login, register) são ignoradas.
 */
export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const PUBLIC_PATHS = ["/login", "/register", "/"];

    const interceptorId = axios.interceptors.response.use(
      (response) => response,
      (error) => {
        if (
          error?.response?.status === 401 &&
          !PUBLIC_PATHS.some((p) => pathname?.startsWith(p))
        ) {
          localStorage.removeItem("token");
          router.replace("/login");
        }
        return Promise.reject(error);
      }
    );

    return () => {
      axios.interceptors.response.eject(interceptorId);
    };
  }, [router, pathname]);

  return <>{children}</>;
}
