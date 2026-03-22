"use client";
import React from "react";
import {
  EdgeProps,
  getBezierPath,
  EdgeLabelRenderer,
  BaseEdge,
} from "@xyflow/react";

interface DeletableEdgeProps extends EdgeProps {
  data?: { onDelete?: () => void };
}

export default function DeletableEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  markerEnd,
  style,
  data,
}: DeletableEdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} style={style} />
      {/* Botão × aparece ao selecionar ou ao hover (via CSS no path) */}
      {selected && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
            }}
            className="nodrag nopan"
          >
            <button
              type="button"
              onClick={() => data?.onDelete?.()}
              className="w-5 h-5 rounded-full bg-red-500 border-2 border-[#0a1628] flex items-center justify-center text-white text-[10px] font-black hover:bg-red-400 shadow-lg transition-all hover:scale-110"
              title="Excluir conexão"
            >
              ×
            </button>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
