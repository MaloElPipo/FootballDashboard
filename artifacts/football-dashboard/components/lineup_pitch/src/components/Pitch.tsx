import React from "react";
import { FORMATIONS } from "../formations";
import type { FormationKey, Player } from "../types";
import { PlayerDot } from "./PlayerDot";

export function Pitch({
  formation,
  onPitch,
  selectedPid,
  onSelect,
}: {
  formation: FormationKey;
  onPitch: Map<number, Player>;
  selectedPid: number | null;
  onSelect: (pid: number) => void;
}) {
  const slots = FORMATIONS[formation];
  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        aspectRatio: "3 / 4",
        borderRadius: 12,
        overflow: "hidden",
        boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
        background:
          "repeating-linear-gradient(180deg, #2f9e44 0px, #2f9e44 36px, #37b04a 36px, #37b04a 72px)",
      }}
    >
      <svg
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        viewBox="0 0 300 400"
        preserveAspectRatio="none"
      >
        <rect
          x="10"
          y="10"
          width="280"
          height="380"
          stroke="white"
          strokeWidth="2"
          fill="none"
          opacity="0.7"
        />
        <line
          x1="10"
          y1="200"
          x2="290"
          y2="200"
          stroke="white"
          strokeWidth="2"
          opacity="0.7"
        />
        <circle
          cx="150"
          cy="200"
          r="40"
          stroke="white"
          strokeWidth="2"
          fill="none"
          opacity="0.7"
        />
        <rect
          x="80"
          y="10"
          width="140"
          height="50"
          stroke="white"
          strokeWidth="2"
          fill="none"
          opacity="0.7"
        />
        <rect
          x="80"
          y="340"
          width="140"
          height="50"
          stroke="white"
          strokeWidth="2"
          fill="none"
          opacity="0.7"
        />
        <rect
          x="115"
          y="10"
          width="70"
          height="20"
          stroke="white"
          strokeWidth="2"
          fill="none"
          opacity="0.7"
        />
        <rect
          x="115"
          y="370"
          width="70"
          height="20"
          stroke="white"
          strokeWidth="2"
          fill="none"
          opacity="0.7"
        />
      </svg>
      {slots.map((slot, idx) => {
        const player = onPitch.get(idx) ?? null;
        return (
          <PlayerDot
            key={idx}
            player={player}
            x={slot.x}
            y={slot.y}
            selected={!!player && player.pid === selectedPid}
            onClick={() => {
              if (player?.pid != null) onSelect(player.pid);
            }}
          />
        );
      })}
    </div>
  );
}
