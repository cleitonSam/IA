"use client";
import React from "react";
import { NodeProps } from "@xyflow/react";
import BaseNode, { NodeInput } from "./BaseNode";

export default function SendAudioNode(props: NodeProps) {
  const data = (props.data || {}) as Record<string, string>;
  const onChange = props.data?.onChange as ((patch: Record<string, string>) => void) | undefined;

  return (
    <BaseNode nodeType="sendAudio" {...props}>
      <NodeInput
        label="URL do áudio (PTT)"
        value={data.url || ""}
        onChange={(v) => onChange?.({ url: v })}
        placeholder="https://exemplo.com/audio.mp3"
        type="url"
      />
      <p className="text-[9px] text-purple-700">
        Será enviado como mensagem de voz (PTT) no WhatsApp.
      </p>
    </BaseNode>
  );
}
