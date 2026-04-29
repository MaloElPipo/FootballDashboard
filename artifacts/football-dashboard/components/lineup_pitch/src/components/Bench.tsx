import React, { useState } from "react";
import type { Player } from "../types";
import { getTheme } from "./PlayerDot";

function shortLast(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return parts[parts.length - 1] ?? name;
}

const STATUS_DOT: Record<string, string> = {
  doubtful: "#f59e0b",
  injured: "#dc2626",
  suspended: "#ea580c",
};

function formatOdd(o: number | null | undefined): string {
  if (o == null || !isFinite(o)) return "—";
  if (o >= 100) return o.toFixed(0);
  if (o >= 10) return o.toFixed(1);
  return o.toFixed(2);
}

/**
 * Banc dépliable : par défaut replié, montre juste un bouton-bandeau qui
 * affiche le nombre de remplaçants et un chevron. Quand déplié, affiche
 * une grille de mini-cartes (maillot + nom + cote fair).
 *
 * En mode swap (`swapSourcePid` non null) le banc se déplie automatiquement
 * et chaque carte affiche un halo orange "cible cliquable".
 */
export function Bench({
  players,
  selectedPid,
  swapSourcePid,
  teamName,
  defaultExpanded = false,
  onSelect,
}: {
  players: Player[];
  selectedPid: number | null;
  swapSourcePid: number | null;
  teamName?: string;
  defaultExpanded?: boolean;
  onSelect: (pid: number) => void;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  // En mode swap on force l'ouverture pour que les cibles soient visibles.
  const reallyExpanded = expanded || swapSourcePid != null;

  if (players.length === 0) return null;

  return (
    <div
      style={{
        marginTop: 10,
        background: "linear-gradient(180deg, #1e293b 0%, #0f172a 100%)",
        border: "1px solid #1e293b",
        borderRadius: 10,
        padding: 8,
        boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
      }}
    >
      <button
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={reallyExpanded}
        className="lineup-pitch-btn"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
          background: "transparent",
          border: "none",
          color: "white",
          padding: "4px 6px",
          cursor: "pointer",
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: 0.3,
        }}
      >
        <span>
          <span style={{ color: "#22d3ee", marginRight: 6 }}>▸</span>
          Remplaçants · {players.length}
          {swapSourcePid != null && (
            <span
              style={{
                marginLeft: 8,
                fontSize: 10,
                color: "#fb923c",
                fontWeight: 800,
                letterSpacing: 0.5,
              }}
            >
              MODE SWAP — choisir cible
            </span>
          )}
        </span>
        <span
          style={{
            display: "inline-block",
            transform: reallyExpanded ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 150ms ease",
            color: "#94a3b8",
            fontSize: 10,
          }}
        >
          ▼
        </span>
      </button>
      {reallyExpanded && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(64px, 1fr))",
            gap: 6,
            marginTop: 8,
          }}
        >
          {players.map((p) => {
            const isSelected = p.pid != null && p.pid === selectedPid;
            const isSwapSource = p.pid != null && p.pid === swapSourcePid;
            const isSwapTarget =
              swapSourcePid != null && p.pid != null && !isSwapSource;
            const statusColor = STATUS_DOT[p.availability];
            const isGK = p.pos === "GK" || p.pos === "G";
            const theme = getTheme(teamName, isGK);
            let jerseyBg: React.CSSProperties["background"] = theme.primary;
            if (theme.pattern === "stripes") {
              jerseyBg = `repeating-linear-gradient(90deg, ${theme.primary} 0 4px, ${theme.secondary} 4px 8px)`;
            } else if (theme.pattern === "sleeves") {
              jerseyBg = `linear-gradient(90deg, ${theme.secondary} 0 4px, ${theme.primary} 4px calc(100% - 4px), ${theme.secondary} calc(100% - 4px) 100%)`;
            }
            return (
              <button
                key={p.pid ?? p.name}
                onClick={() => p.pid != null && onSelect(p.pid)}
                aria-pressed={isSelected || isSwapSource}
                className="lineup-pitch-btn"
                title={`${p.name} (${p.pos}) — Cote juste ${formatOdd(p.fair_scorer)}`}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 2,
                  padding: "4px 2px",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  position: "relative",
                }}
              >
                {(isSelected || isSwapSource || isSwapTarget) && (
                  <span
                    style={{
                      position: "absolute",
                      inset: 2,
                      borderRadius: 6,
                      background: isSwapTarget
                        ? "rgba(251,146,60,0.25)"
                        : "rgba(34,211,238,0.25)",
                      border: `1px solid ${isSwapTarget ? "#fb923c" : "#22d3ee"}`,
                      pointerEvents: "none",
                    }}
                  />
                )}
                <div style={{ position: "relative", zIndex: 1 }}>
                  <div
                    style={{
                      width: 28,
                      height: 28,
                      background: jerseyBg,
                      border: `1.5px solid ${theme.secondary}`,
                      borderRadius: "5px 5px 3px 3px",
                      color: theme.text,
                      fontWeight: 800,
                      fontSize: 11,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      textShadow: "0 1px 2px rgba(0,0,0,0.6)",
                    }}
                  >
                    {p.jersey_number != null
                      ? p.jersey_number
                      : p.pid != null
                        ? String(p.pid % 100).padStart(2, "0")
                        : "—"}
                  </div>
                  {statusColor && (
                    <span
                      style={{
                        position: "absolute",
                        top: -2,
                        right: -2,
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: statusColor,
                        border: "1px solid #0f172a",
                      }}
                    />
                  )}
                </div>
                <span
                  style={{
                    fontSize: 9,
                    color: "white",
                    fontWeight: 700,
                    maxWidth: 60,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    zIndex: 1,
                  }}
                >
                  {shortLast(p.name)}
                </span>
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 800,
                    color: "white",
                    background: p.fair_scorer != null ? "#dc2626" : "rgba(148,163,184,0.5)",
                    padding: "0 4px",
                    borderRadius: 2,
                    fontFamily: "ui-monospace, monospace",
                    minWidth: 24,
                    textAlign: "center",
                    zIndex: 1,
                  }}
                >
                  {formatOdd(p.fair_scorer)}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
