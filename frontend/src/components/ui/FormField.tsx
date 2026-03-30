"use client";

/**
 * FormField — Input, Textarea e Select com estilo padrão do dashboard.
 * Elimina os inputClass/labelClass copy-pastados em cada página.
 */

import React from "react";

// ─── Estilos base (único source of truth) ────────────────────────────────────
export const inputBase =
  "w-full bg-slate-900/60 border border-white/8 rounded-2xl px-5 py-3.5 text-white placeholder-slate-600 focus:outline-none focus:border-[#00d2ff]/40 transition-all font-medium text-sm disabled:opacity-50";

export const labelBase =
  "block text-xs font-semibold text-slate-400 mb-1.5 uppercase tracking-wider";

// ─── Props compartilhadas ─────────────────────────────────────────────────────
interface BaseFieldProps {
  label?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  className?: string;
}

// ─── Input ────────────────────────────────────────────────────────────────────
interface InputFieldProps
  extends BaseFieldProps,
    Omit<React.InputHTMLAttributes<HTMLInputElement>, "className"> {}

export function InputField({
  label,
  hint,
  error,
  required,
  className,
  ...props
}: InputFieldProps) {
  return (
    <div className={className}>
      {label && (
        <label className={labelBase}>
          {label}
          {required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
      )}
      <input
        className={`${inputBase} ${error ? "border-red-500/50" : ""}`}
        required={required}
        {...props}
      />
      {hint && !error && <p className="mt-1.5 text-xs text-slate-500">{hint}</p>}
      {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
    </div>
  );
}

// ─── Textarea ─────────────────────────────────────────────────────────────────
interface TextareaFieldProps
  extends BaseFieldProps,
    Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "className"> {}

export function TextareaField({
  label,
  hint,
  error,
  required,
  className,
  rows = 3,
  ...props
}: TextareaFieldProps) {
  return (
    <div className={className}>
      {label && (
        <label className={labelBase}>
          {label}
          {required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
      )}
      <textarea
        rows={rows}
        className={`${inputBase} resize-none ${error ? "border-red-500/50" : ""}`}
        required={required}
        {...props}
      />
      {hint && !error && <p className="mt-1.5 text-xs text-slate-500">{hint}</p>}
      {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
    </div>
  );
}

// ─── Select ───────────────────────────────────────────────────────────────────
interface SelectFieldProps
  extends BaseFieldProps,
    Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "className"> {
  options: Array<{ value: string | number; label: string }>;
  placeholder?: string;
}

export function SelectField({
  label,
  hint,
  error,
  required,
  className,
  options,
  placeholder,
  ...props
}: SelectFieldProps) {
  return (
    <div className={className}>
      {label && (
        <label className={labelBase}>
          {label}
          {required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
      )}
      <select
        className={`${inputBase} appearance-none ${error ? "border-red-500/50" : ""}`}
        required={required}
        {...props}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {hint && !error && <p className="mt-1.5 text-xs text-slate-500">{hint}</p>}
      {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
    </div>
  );
}

// ─── Toggle ───────────────────────────────────────────────────────────────────
interface ToggleFieldProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  className?: string;
}

export function ToggleField({
  label,
  description,
  checked,
  onChange,
  className,
}: ToggleFieldProps) {
  return (
    <div
      className={`flex items-center justify-between px-4 py-3 bg-slate-900/40 rounded-2xl border border-white/6 ${className ?? ""}`}
    >
      <div>
        <span className="text-sm font-medium text-white">{label}</span>
        {description && (
          <p className="text-xs text-slate-500 mt-0.5">{description}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`w-11 h-6 rounded-full transition-colors relative ${
          checked ? "bg-[#00d2ff]/80" : "bg-slate-700"
        }`}
        aria-checked={checked}
        role="switch"
      >
        <span
          className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
            checked ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}
