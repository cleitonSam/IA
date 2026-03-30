"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationBarProps {
  page: number;
  totalPages: number;
  onPageChange: (newPage: number) => void;
  /** Opcional: texto extra antes das páginas, ex: "12 resultados" */
  label?: string;
  className?: string;
}

/**
 * Barra de paginação reutilizável — compatível com o padrão de resposta
 * `{data: [...], meta: {total, page, per_page, total_pages}}` da API.
 *
 * Uso:
 *   <PaginationBar
 *     page={currentPage}
 *     totalPages={meta.total_pages}
 *     onPageChange={(p) => setCurrentPage(p)}
 *     label={`${meta.total} unidades`}
 *   />
 */
export default function PaginationBar({
  page,
  totalPages,
  onPageChange,
  label,
  className = "",
}: PaginationBarProps) {
  if (totalPages <= 1) return null;

  const canPrev = page > 1;
  const canNext = page < totalPages;

  return (
    <div className={`flex items-center justify-between gap-3 mt-4 pt-4 border-t border-white/5 ${className}`}>
      {/* Label opcional */}
      <span className="text-xs text-gray-500 flex-1">{label ?? ""}</span>

      {/* Controles */}
      <div className="flex items-center gap-2">
        <button
          disabled={!canPrev}
          onClick={() => onPageChange(page - 1)}
          className={`p-1.5 rounded-lg transition-all ${
            canPrev
              ? "text-gray-300 hover:text-white hover:bg-white/10"
              : "text-gray-700 cursor-not-allowed opacity-40"
          }`}
          aria-label="Página anterior">
          <ChevronLeft className="w-4 h-4" />
        </button>

        <span className="text-xs font-medium text-gray-400 select-none min-w-[80px] text-center">
          Página {page} de {totalPages}
        </span>

        <button
          disabled={!canNext}
          onClick={() => onPageChange(page + 1)}
          className={`p-1.5 rounded-lg transition-all ${
            canNext
              ? "text-gray-300 hover:text-white hover:bg-white/10"
              : "text-gray-700 cursor-not-allowed opacity-40"
          }`}
          aria-label="Próxima página">
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
