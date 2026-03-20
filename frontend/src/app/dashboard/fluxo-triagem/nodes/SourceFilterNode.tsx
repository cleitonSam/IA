"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode from "./BaseNode";

export default function SourceFilterNode(props: NodeProps) {
  return (
    <BaseNode
      nodeType="sourceFilter"
      {...props}
      customOutputHandles={[
        { id: "private", label: "Privado" },
        { id: "group", label: "Grupo" },
      ]}
    >
      <p className="text-[10px] text-lime-800 leading-tight">
        Filtra se a mensagem veio de um chat privado ou de um grupo de WhatsApp.
      </p>
    </BaseNode>
  );
}
