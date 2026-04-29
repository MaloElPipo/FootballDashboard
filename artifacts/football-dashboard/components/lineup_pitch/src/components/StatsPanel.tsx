import React from "react";
import type { Player } from "../types";

function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toFixed(digits);
}

function fmtOdd(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  if (v >= 100) return v.toFixed(0);
  if (v >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

const AVAIL_LABEL: Record<string, { label: string; color: string }> = {
  doubtful: { label: "DOUBTFUL", color: "#f59e0b" },
  injured: { label: "INJURED", color: "#dc2626" },
  suspended: { label: "SUSPENDED", color: "#ea580c" },
  available: { label: "AVAILABLE", color: "#16a34a" },
};

function StatRow({
  label,
  value,
  hint,
  edge,
  sub,
}: {
  label: string;
  value: string;
  hint?: string;
  edge?: number | null;
  sub?: string;
}) {
  let edgeBg = "transparent";
  let edgeFg = "#64748b";
  if (edge != null) {
    if (edge > 3) {
      edgeBg = "#dcfce7";
      edgeFg = "#15803d";
    } else if (edge < -3) {
      edgeBg = "#fee2e2";
      edgeFg = "#b91c1c";
    } else {
      edgeBg = "#f1f5f9";
      edgeFg = "#64748b";
    }
  }
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 0",
        borderBottom: "1px solid #f1f5f9",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column" }}>
        <span
          style={{
            fontSize: 11,
            color: "#64748b",
            textTransform: "uppercase",
            letterSpacing: 0.5,
            fontWeight: 700,
          }}
        >
          {label}
        </span>
        {hint && (
          <span style={{ fontSize: 10, color: "#94a3b8" }}>{hint}</span>
        )}
      </div>
      <div
        style={{ display: "flex", alignItems: "center", gap: 8 }}
      >
        <div style={{ textAlign: "right" }}>
          <div
            style={{
              fontSize: 16,
              fontWeight: 700,
              fontFamily: "ui-monospace, monospace",
              color: "#0f172a",
            }}
          >
            {value}
          </div>
          {sub && (
            <div
              style={{
                fontSize: 10,
                color: "#94a3b8",
                fontFamily: "ui-monospace, monospace",
              }}
            >
              {sub}
            </div>
          )}
        </div>
        {edge != null && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 4,
              background: edgeBg,
              color: edgeFg,
              minWidth: 50,
              textAlign: "center",
            }}
          >
            {edge > 0 ? "+" : ""}
            {edge.toFixed(1)}%
          </span>
        )}
      </div>
    </div>
  );
}

export function StatsPanel({
  player,
  minutesOverride,
  onMinutesChange,
  onStartSwap,
  onClose,
}: {
  player: Player;
  minutesOverride: number | null;
  onMinutesChange: (m: number | null) => void;
  onStartSwap: () => void;
  onClose: () => void;
}) {
  const status = AVAIL_LABEL[player.availability] ?? AVAIL_LABEL.available;
  const baseMinutes = Math.round(player.minutes_expected ?? 78);
  const currentMinutes = minutesOverride ?? baseMinutes;
  const isOverridden = minutesOverride != null && minutesOverride !== baseMinutes;

  const edgeScorer =
    player.edge_scorer != null ? player.edge_scorer * 100 : null;
  const edgeAssist =
    player.edge_assist != null ? player.edge_assist * 100 : null;

  return (
    <div
      style={{
        background: "white",
        borderRadius: 12,
        boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          background: "linear-gradient(135deg, #06b6d4 0%, #0e7490 100%)",
          color: "white",
          padding: 14,
          position: "relative",
        }}
      >
        <button
          onClick={onClose}
          aria-label="Fermer"
          style={{
            position: "absolute",
            top: 8,
            right: 8,
            background: "rgba(255,255,255,0.18)",
            border: "none",
            color: "white",
            width: 24,
            height: 24,
            borderRadius: "50%",
            cursor: "pointer",
            fontSize: 14,
            lineHeight: 1,
          }}
        >
          ×
        </button>
        <div
          style={{
            fontSize: 10,
            textTransform: "uppercase",
            letterSpacing: 1,
            opacity: 0.85,
            marginBottom: 2,
          }}
        >
          {player.pos} · Joueur sélectionné
        </div>
        <div
          style={{ fontSize: 18, fontWeight: 800, lineHeight: 1.1 }}
        >
          {player.name}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginTop: 6,
          }}
        >
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 4,
              background: status.color,
              color: "white",
            }}
          >
            {status.label}
          </span>
          {player.injury_type && (
            <span style={{ fontSize: 10, opacity: 0.9 }}>
              {player.injury_type}
            </span>
          )}
          {player.is_starter && (
            <span style={{ fontSize: 10, opacity: 0.85 }}>
              · titulaire présumé ({fmt((player.start_rate ?? 0) * 100, 0)}
              %)
            </span>
          )}
        </div>
      </div>
      <div style={{ padding: 14 }}>
        <button
          onClick={onStartSwap}
          className="lineup-pitch-btn"
          style={{
            width: "100%",
            padding: "8px 12px",
            background: "linear-gradient(180deg, #fb923c 0%, #ea580c 100%)",
            color: "white",
            border: "none",
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 800,
            cursor: "pointer",
            marginBottom: 12,
            boxShadow: "0 2px 6px rgba(234,88,12,0.35)",
            letterSpacing: 0.3,
          }}
          title="Activer le mode permutation : cliquez ensuite sur un autre joueur (terrain ou banc) pour permuter"
        >
          ⇄ Permuter ce joueur
        </button>
        <div
          style={{
            fontSize: 10,
            color: "#94a3b8",
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: 0.5,
            marginBottom: 4,
          }}
        >
          Cotes (modèle Buteurs Maison 4.1)
        </div>
        <StatRow
          label="Cote juste Buteur"
          hint={`Modèle ${fmtOdd(player.fair_scorer)} · Betclic ${fmtOdd(player.betclic_scorer)}`}
          value={fmtOdd(player.fair_scorer)}
          edge={edgeScorer}
        />
        <StatRow
          label="Cote juste Passeur"
          hint={`Modèle ${fmtOdd(player.fair_assist)} · Betclic ${fmtOdd(player.betclic_assist)}`}
          value={fmtOdd(player.fair_assist)}
          edge={edgeAssist}
        />
        <div
          style={{
            fontSize: 10,
            color: "#94a3b8",
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: 0.5,
            marginTop: 16,
            marginBottom: 4,
          }}
        >
          Stats attendues match
        </div>
        <StatRow
          label="xG"
          hint="Buts attendus"
          value={fmt(player.xg_player, 2)}
          sub={`${fmt(player.xg_p90, 2)} / 90′`}
        />
        <StatRow
          label="xA"
          hint="Passes déc. attendues"
          value={fmt(player.xa_player, 2)}
          sub={`${fmt(player.xa_p90, 2)} / 90′`}
        />
        <StatRow
          label="xT"
          hint="Tirs attendus"
          value={fmt(player.expected_shots, 2)}
          sub={`${fmt(player.shots_p90, 2)} / 90′`}
        />
        <StatRow
          label="xTC"
          hint="Tirs cadrés attendus"
          value={fmt(player.expected_shots_on_target, 2)}
          sub={`${fmt(player.shots_on_p90, 2)} / 90′`}
        />
        <div style={{ marginTop: 16 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 6,
            }}
          >
            <span
              style={{
                fontSize: 11,
                color: "#64748b",
                textTransform: "uppercase",
                letterSpacing: 0.5,
                fontWeight: 700,
              }}
            >
              Minutes attendues
            </span>
            <span
              style={{
                fontSize: 14,
                fontWeight: 700,
                fontFamily: "ui-monospace, monospace",
                color: isOverridden ? "#0891b2" : "#0f172a",
              }}
            >
              {currentMinutes}′
              {isOverridden && (
                <span
                  style={{ fontSize: 10, color: "#0891b2", marginLeft: 6 }}
                >
                  (modifié, base {baseMinutes}′)
                </span>
              )}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={95}
            step={1}
            value={currentMinutes}
            onChange={(e) => onMinutesChange(Number(e.target.value))}
            style={{ width: "100%", accentColor: "#0891b2" }}
          />
          {isOverridden && (
            <button
              onClick={() => onMinutesChange(null)}
              style={{
                marginTop: 4,
                background: "transparent",
                border: "none",
                color: "#0891b2",
                fontSize: 11,
                cursor: "pointer",
                padding: 0,
                textDecoration: "underline",
              }}
            >
              ↺ Restaurer la valeur par défaut
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
