import React from "react";
import type { Player } from "../types";

const STATUS_COLORS: Record<string, { bg: string; fg: string; label: string }> = {
  doubtful: { bg: "#f59e0b", fg: "#451a03", label: "?" },
  injured: { bg: "#dc2626", fg: "#ffffff", label: "+" },
  suspended: { bg: "#ea580c", fg: "#ffffff", label: "■" },
};

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function formatOdd(o: number | null | undefined): string {
  if (o == null || !isFinite(o)) return "—";
  if (o >= 100) return o.toFixed(0);
  if (o >= 10) return o.toFixed(1);
  return o.toFixed(2);
}

export function PlayerDot({
  player,
  x,
  y,
  selected,
  onClick,
}: {
  player: Player | null;
  x: number;
  y: number;
  selected: boolean;
  onClick: () => void;
}) {
  if (!player) {
    return (
      <div
        style={{
          position: "absolute",
          left: `${x}%`,
          top: `${y}%`,
          transform: "translate(-50%, -50%)",
          width: 38,
          height: 38,
          borderRadius: "50%",
          border: "2px dashed rgba(255,255,255,0.5)",
        }}
      />
    );
  }
  const status = player.availability !== "available" ? player.availability : null;
  const statusBadge = status ? STATUS_COLORS[status] : null;
  const odd = player.fair_scorer;
  const oddDisplay = formatOdd(odd);

  return (
    <button
      onClick={onClick}
      title={`${player.name} — Cote Buteur ${oddDisplay}`}
      aria-pressed={selected}
      aria-label={`${player.name} (${player.pos}), cote Buteur ${oddDisplay}`}
      className="lineup-pitch-btn"
      style={{
        position: "absolute",
        left: `${x}%`,
        top: `${y}%`,
        transform: "translate(-50%, -50%)",
        width: 64,
        background: "transparent",
        border: "none",
        padding: 0,
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 2,
        zIndex: selected ? 5 : 2,
        borderRadius: 8,
      }}
    >
      <div style={{ position: "relative" }}>
        {selected && (
          <span
            style={{
              position: "absolute",
              inset: -8,
              borderRadius: "50%",
              background: "rgba(34,211,238,0.55)",
              animation: "lineupPulse 1.4s ease-in-out infinite",
            }}
          />
        )}
        <div
          style={{
            position: "relative",
            width: 42,
            height: 42,
            borderRadius: "50%",
            background: selected
              ? "linear-gradient(160deg, #22d3ee 0%, #0891b2 100%)"
              : "linear-gradient(160deg, #2563eb 0%, #1e3a8a 100%)",
            boxShadow: selected
              ? "0 4px 14px rgba(34,211,238,0.5), 0 0 0 2px #a5f3fc"
              : "0 3px 8px rgba(0,0,0,0.4), 0 0 0 2px white",
            color: "white",
            fontWeight: 700,
            fontSize: 11,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: selected ? "scale(1.08)" : "scale(1)",
            transition: "transform 120ms ease, box-shadow 120ms ease",
          }}
        >
          {initials(player.name)}
        </div>
        {statusBadge && (
          <span
            style={{
              position: "absolute",
              top: -3,
              right: -3,
              width: 16,
              height: 16,
              borderRadius: "50%",
              background: statusBadge.bg,
              color: statusBadge.fg,
              fontWeight: 700,
              fontSize: 9,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "2px solid #2f9e44",
              lineHeight: 1,
            }}
          >
            {statusBadge.label}
          </span>
        )}
      </div>
      <div
        style={{
          background: selected ? "#0891b2" : "rgba(0,0,0,0.7)",
          color: "white",
          fontSize: 10,
          fontWeight: 600,
          padding: "1px 6px",
          borderRadius: 4,
          whiteSpace: "nowrap",
          maxWidth: 80,
          overflow: "hidden",
          textOverflow: "ellipsis",
          lineHeight: 1.2,
        }}
      >
        {player.name.split(" ").slice(-1)[0]}
      </div>
      <div
        style={{
          background: odd != null ? "#fbbf24" : "rgba(255,255,255,0.7)",
          color: odd != null ? "#1f2937" : "#6b7280",
          fontSize: 10,
          fontWeight: 700,
          padding: "0 5px",
          borderRadius: 3,
          fontFamily: "ui-monospace, monospace",
          lineHeight: 1.3,
        }}
      >
        {oddDisplay}
      </div>
    </button>
  );
}
