import React from "react";
import type { Player } from "../types";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function shortLast(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return parts[parts.length - 1] ?? name;
}

const STATUS_DOT: Record<string, string> = {
  doubtful: "#f59e0b",
  injured: "#dc2626",
  suspended: "#ea580c",
};

export function Bench({
  players,
  selectedPid,
  onSelect,
}: {
  players: Player[];
  selectedPid: number | null;
  onSelect: (pid: number) => void;
}) {
  if (players.length === 0) return null;
  return (
    <div
      style={{
        marginTop: 12,
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        padding: "10px 12px",
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: "#475569",
          textTransform: "uppercase",
          letterSpacing: 0.5,
          marginBottom: 8,
        }}
      >
        Banc · {players.length} joueurs
      </div>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        {players.map((p) => {
          const isSelected = p.pid != null && p.pid === selectedPid;
          const statusColor = STATUS_DOT[p.availability];
          return (
            <button
              key={p.pid ?? p.name}
              onClick={() => p.pid != null && onSelect(p.pid)}
              aria-pressed={isSelected}
              className="lineup-pitch-btn"
              title={`${p.name} (${p.pos}) — Cote Buteur ${
                p.fair_scorer != null ? p.fair_scorer.toFixed(2) : "—"
              }`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 8px 4px 4px",
                background: isSelected ? "#0891b2" : "white",
                border: isSelected ? "1px solid #0891b2" : "1px solid #cbd5e1",
                color: isSelected ? "white" : "#1e293b",
                borderRadius: 999,
                cursor: "pointer",
                fontSize: 11,
                fontWeight: 600,
                transition: "all 100ms ease",
              }}
            >
              <span
                style={{
                  position: "relative",
                  width: 24,
                  height: 24,
                  borderRadius: "50%",
                  background: isSelected
                    ? "rgba(255,255,255,0.25)"
                    : "linear-gradient(160deg, #94a3b8, #64748b)",
                  color: "white",
                  fontWeight: 700,
                  fontSize: 9,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                {initials(p.name)}
                {statusColor && (
                  <span
                    style={{
                      position: "absolute",
                      top: -1,
                      right: -1,
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: statusColor,
                      border: "1px solid white",
                    }}
                  />
                )}
              </span>
              <span>{shortLast(p.name)}</span>
              <span
                style={{
                  marginLeft: 2,
                  padding: "0 4px",
                  background: isSelected ? "rgba(255,255,255,0.25)" : "#fef3c7",
                  color: isSelected ? "white" : "#78350f",
                  borderRadius: 3,
                  fontFamily: "ui-monospace, monospace",
                  fontSize: 10,
                }}
              >
                {p.fair_scorer != null && isFinite(p.fair_scorer)
                  ? p.fair_scorer >= 100
                    ? p.fair_scorer.toFixed(0)
                    : p.fair_scorer.toFixed(2)
                  : "—"}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
