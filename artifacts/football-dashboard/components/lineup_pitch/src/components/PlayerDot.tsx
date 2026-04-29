import React from "react";
import type { Player } from "../types";

const STATUS_COLORS: Record<string, { bg: string; fg: string; label: string }> = {
  doubtful: { bg: "#f59e0b", fg: "#451a03", label: "?" },
  injured: { bg: "#dc2626", fg: "#ffffff", label: "+" },
  suspended: { bg: "#ea580c", fg: "#ffffff", label: "■" },
};

export type JerseyTheme = {
  primary: string;
  secondary: string;
  text: string;
  pattern: "stripes" | "solid" | "sleeves";
};

export const TEAM_THEMES: Record<string, JerseyTheme> = {
  "Atlético Madrid": {
    primary: "#d3122c",
    secondary: "#ffffff",
    text: "#ffffff",
    pattern: "stripes",
  },
  Arsenal: {
    primary: "#ef0107",
    secondary: "#ffffff",
    text: "#ffffff",
    pattern: "sleeves",
  },
};

const GK_THEME: JerseyTheme = {
  primary: "#15803d",
  secondary: "#052e16",
  text: "#ffffff",
  pattern: "solid",
};

const DEFAULT_THEME: JerseyTheme = {
  primary: "#1e3a8a",
  secondary: "#0f172a",
  text: "#ffffff",
  pattern: "solid",
};

export function getTheme(teamName: string | undefined, isGK: boolean): JerseyTheme {
  if (isGK) return GK_THEME;
  if (!teamName) return DEFAULT_THEME;
  return TEAM_THEMES[teamName] ?? DEFAULT_THEME;
}

function shortLast(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return name;
  const last = parts[parts.length - 1];
  return last.length > 10 ? last.slice(0, 9) + "…" : last;
}

function formatOdd(o: number | null | undefined): string {
  if (o == null || !isFinite(o)) return "—";
  if (o >= 100) return o.toFixed(0);
  if (o >= 10) return o.toFixed(1);
  return o.toFixed(2);
}

function jerseyDisplay(player: Player): string {
  if (player.jersey_number != null) return String(player.jersey_number);
  // fallback : 2 derniers chiffres du pid si dispo
  if (player.pid != null) return String(player.pid % 100).padStart(2, "0");
  return "—";
}

/**
 * Carte maillot compacte (~60px de large) façon trading card.
 * Composée de 3 zones empilées :
 *   - haut : maillot stylisé avec numéro
 *   - milieu : nom de famille
 *   - bas : cote Buteur fair (chip rouge)
 *
 * Le mode `swapHighlight` ajoute un halo orange pulsant pour signaler
 * les cibles cliquables pendant un swap en cours.
 */
export function PlayerDot({
  player,
  x,
  y,
  selected,
  swapHighlight,
  teamName,
  onClick,
}: {
  player: Player | null;
  x: number;
  y: number;
  selected: boolean;
  swapHighlight: boolean;
  teamName?: string;
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
          width: 32,
          height: 38,
          borderRadius: 4,
          border: "2px dashed rgba(148,163,184,0.45)",
        }}
      />
    );
  }
  const status = player.availability !== "available" ? player.availability : null;
  const statusBadge = status ? STATUS_COLORS[status] : null;
  const odd = player.fair_scorer;
  const oddDisplay = formatOdd(odd);
  const isGK = player.pos === "GK" || player.pos === "G";
  const theme = getTheme(teamName, isGK);
  const jersey = jerseyDisplay(player);

  // Background du maillot : rayures, manches ou uni
  let jerseyBg: React.CSSProperties["background"] = theme.primary;
  if (theme.pattern === "stripes") {
    jerseyBg = `repeating-linear-gradient(90deg, ${theme.primary} 0 6px, ${theme.secondary} 6px 12px)`;
  } else if (theme.pattern === "sleeves") {
    jerseyBg = `linear-gradient(90deg, ${theme.secondary} 0 6px, ${theme.primary} 6px calc(100% - 6px), ${theme.secondary} calc(100% - 6px) 100%)`;
  }

  return (
    <button
      onClick={onClick}
      title={`${player.name} — Cote juste Buteur ${oddDisplay}`}
      aria-pressed={selected}
      aria-label={`${player.name} (${player.pos}), cote juste Buteur ${oddDisplay}${swapHighlight ? ", cible swap" : ""}`}
      className="lineup-pitch-btn"
      style={{
        position: "absolute",
        left: `${x}%`,
        top: `${y}%`,
        transform: "translate(-50%, -50%)",
        width: 56,
        background: "transparent",
        border: "none",
        padding: 0,
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 2,
        zIndex: selected || swapHighlight ? 5 : 2,
        borderRadius: 6,
      }}
    >
      <div style={{ position: "relative" }}>
        {(selected || swapHighlight) && (
          <span
            style={{
              position: "absolute",
              inset: -6,
              borderRadius: 8,
              background: swapHighlight
                ? "rgba(251,146,60,0.55)"
                : "rgba(34,211,238,0.55)",
              animation: "lineupPulse 1.4s ease-in-out infinite",
            }}
          />
        )}
        {/* Maillot stylisé : largeur 38px, hauteur 36px, avec encolure */}
        <div
          style={{
            position: "relative",
            width: 38,
            height: 36,
            background: jerseyBg,
            border: `2px solid ${selected ? "#22d3ee" : swapHighlight ? "#fb923c" : theme.secondary}`,
            borderRadius: "6px 6px 4px 4px",
            color: theme.text,
            fontWeight: 800,
            fontSize: 14,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: selected
              ? "0 4px 14px rgba(34,211,238,0.5)"
              : "0 2px 6px rgba(0,0,0,0.45)",
            textShadow: "0 1px 2px rgba(0,0,0,0.6)",
            transform: selected ? "scale(1.06)" : "scale(1)",
            transition: "transform 120ms ease, box-shadow 120ms ease",
          }}
        >
          {/* encolure en V */}
          <div
            style={{
              position: "absolute",
              top: -1,
              left: "50%",
              transform: "translateX(-50%) rotate(45deg)",
              width: 8,
              height: 8,
              background: "#0f172a",
              borderRadius: 1,
            }}
          />
          {jersey}
        </div>
        {statusBadge && (
          <span
            style={{
              position: "absolute",
              top: -4,
              right: -4,
              width: 14,
              height: 14,
              borderRadius: "50%",
              background: statusBadge.bg,
              color: statusBadge.fg,
              fontWeight: 700,
              fontSize: 9,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "2px solid #0f172a",
              lineHeight: 1,
            }}
          >
            {statusBadge.label}
          </span>
        )}
      </div>
      {/* Nom */}
      <div
        style={{
          background: "rgba(15,23,42,0.85)",
          color: "white",
          fontSize: 9,
          fontWeight: 700,
          padding: "1px 4px",
          borderRadius: 3,
          whiteSpace: "nowrap",
          maxWidth: 64,
          overflow: "hidden",
          textOverflow: "ellipsis",
          lineHeight: 1.2,
          letterSpacing: 0.2,
        }}
      >
        {shortLast(player.name)}
      </div>
      {/* Cote fair en chip rouge */}
      <div
        style={{
          background: odd != null ? "#dc2626" : "rgba(148,163,184,0.4)",
          color: "white",
          fontSize: 10,
          fontWeight: 800,
          padding: "1px 6px",
          borderRadius: 3,
          fontFamily: "ui-monospace, monospace",
          lineHeight: 1.3,
          minWidth: 28,
          textAlign: "center",
          boxShadow: "0 1px 2px rgba(0,0,0,0.35)",
        }}
      >
        {oddDisplay}
      </div>
    </button>
  );
}
