"use client";

/**
 * Modal — Overlay animado com header, body e footer padronizados.
 * Usado em FAQ, Planos, Unidades, etc.
 */

import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Loader2, Save, CheckCircle2 } from "lucide-react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Largura máxima (classe Tailwind). Padrão: max-w-xl */
  maxWidth?: string;
  children: React.ReactNode;
}

export function Modal({
  open,
  onClose,
  title,
  maxWidth = "max-w-xl",
  children,
}: ModalProps) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className={`w-full ${maxWidth} bg-[#0a0f1e] border border-white/8 rounded-3xl shadow-2xl max-h-[90vh] flex flex-col`}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-5 border-b border-white/6 shrink-0">
              <h2 className="text-base font-bold text-white">{title}</h2>
              <button
                onClick={onClose}
                className="p-1.5 rounded-xl hover:bg-white/8 text-slate-400 hover:text-white transition-all"
                aria-label="Fechar"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Scrollable body */}
            <div className="overflow-y-auto px-6 py-5 flex-1">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ─── Botão de salvar com estados ──────────────────────────────────────────────
interface SaveButtonProps {
  saving: boolean;
  success: boolean;
  label?: string;
  successLabel?: string;
}

export function SaveButton({
  saving,
  success,
  label = "Salvar",
  successLabel = "Salvo!",
}: SaveButtonProps) {
  return (
    <button
      type="submit"
      disabled={saving || success}
      className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-[#00d2ff]/80 to-[#7b2ff7]/80 hover:from-[#00d2ff] hover:to-[#7b2ff7] font-semibold text-white transition-all disabled:opacity-70 flex items-center justify-center gap-2 text-sm"
    >
      {success ? (
        <>
          <CheckCircle2 className="w-4 h-4" />
          {successLabel}
        </>
      ) : saving ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin" />
          Salvando...
        </>
      ) : (
        <>
          <Save className="w-4 h-4" />
          {label}
        </>
      )}
    </button>
  );
}

// ─── Toast de feedback ────────────────────────────────────────────────────────
interface ToastProps {
  message: string | null;
  type?: "success" | "error" | "info";
}

export function Toast({ message, type = "info" }: ToastProps) {
  const colors = {
    success: "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
    error: "bg-red-500/10 border-red-500/30 text-red-400",
    info: "bg-slate-800 border-white/8 text-slate-300",
  };

  return (
    <AnimatePresence>
      {message && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className={`px-5 py-3 rounded-2xl border text-sm ${colors[type]}`}
        >
          {message}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────
interface EmptyStateProps {
  icon: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="text-slate-600 mb-3 opacity-40">{icon}</div>
      <p className="text-lg text-slate-500 font-medium">{title}</p>
      {description && (
        <p className="text-sm text-slate-600 mt-1">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ─── Page header padrão ───────────────────────────────────────────────────────
interface PageHeaderProps {
  icon: React.ReactNode;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}

export function PageHeader({
  icon,
  title,
  description,
  actions,
}: PageHeaderProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-[#00d2ff]/20 to-[#7b2ff7]/20 flex items-center justify-center shrink-0">
          {icon}
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">{title}</h1>
          {description && (
            <p className="text-slate-500 text-sm mt-0.5">{description}</p>
          )}
        </div>
      </div>
      {actions && <div className="flex gap-2 flex-wrap">{actions}</div>}
    </div>
  );
}
