import React, { useEffect, useMemo, useRef, useState } from "react";
import { Streamlit, RenderData } from "streamlit-component-lib";
import fixture from "./fixtures/atletico_arsenal.json";
import { Pitch } from "./components/Pitch";
import { Bench } from "./components/Bench";
import { StatsPanel } from "./components/StatsPanel";
import { autoAssign, detectFormation, FORMATIONS } from "./formations";
import type { FormationKey, MatchData, Player, Side } from "./types";

const FORMATION_KEYS = Object.keys(FORMATIONS) as FormationKey[];

const FIXTURE = fixture as unknown as MatchData;

type ComponentArgs = {
  // Au chantier 3 : event_id réel + match data BSD live. Pour l'instant,
  // ces args ne servent qu'à l'affichage du header (titre, kickoff…).
  home_team?: string;
  away_team?: string;
  kickoff?: string;
  league?: string;
};

type SaveDelta = {
  side: Side;
  formation: FormationKey;
  starters_pids: (number | null)[]; // 11 pids dans l'ordre des slots
  minutes_overrides: Record<string, number>; // pid -> minutes
};

function teamHeader(args: ComponentArgs): {
  league: string;
  match: string;
  kickoff: string;
} {
  return {
    league: args.league ?? FIXTURE.league,
    match: `${args.home_team ?? FIXTURE.home_team} vs ${args.away_team ?? FIXTURE.away_team}`,
    kickoff: args.kickoff ?? "Kick-off à venir",
  };
}

// Breakpoint en dessous duquel le panneau passe en stack vertical sous le
// terrain (sinon le terrain est compressé et les pastilles se chevauchent).
const NARROW_BREAKPOINT = 720;

export function App() {
  const [args, setArgs] = useState<ComponentArgs | null>(null);
  const [side, setSide] = useState<Side>("home");
  const [formation, setFormation] = useState<FormationKey>(() =>
    detectFormation(FIXTURE.home),
  );
  const [selectedPid, setSelectedPid] = useState<number | null>(null);
  const [minutesOverrides, setMinutesOverrides] = useState<
    Record<number, number>
  >({});
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [isNarrow, setIsNarrow] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const readySent = useRef(false);

  // Surveille la largeur réelle du conteneur (l'iframe Streamlit varie selon
  // que la sidebar est ouverte/fermée et selon la résolution écran).
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        setIsNarrow(w > 0 && w < NARROW_BREAKPOINT);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Bridge Streamlit ↔ React
  useEffect(() => {
    const onRender = (event: Event) => {
      const data = (event as CustomEvent<RenderData>).detail;
      setArgs(data?.args as ComponentArgs);
      Streamlit.setFrameHeight();
    };
    Streamlit.events.addEventListener(
      Streamlit.RENDER_EVENT,
      onRender as EventListener,
    );
    if (!readySent.current) {
      Streamlit.setComponentReady();
      readySent.current = true;
    }
    Streamlit.setFrameHeight(720);
    return () => {
      Streamlit.events.removeEventListener(
        Streamlit.RENDER_EVENT,
        onRender as EventListener,
      );
    };
  }, []);

  const roster = side === "home" ? FIXTURE.home : FIXTURE.away;
  const referenceFormation = useMemo(() => detectFormation(roster), [roster]);

  // Auto-assign à chaque changement de side / formation
  const { onPitch, bench } = useMemo(
    () => autoAssign(roster, formation),
    [roster, formation],
  );

  useEffect(() => {
    Streamlit.setFrameHeight();
  });

  // Quand on change de side, re-detect le schéma + reset selection / overrides
  const handleSideChange = (newSide: Side) => {
    if (newSide === side) return;
    setSide(newSide);
    const newRoster = newSide === "home" ? FIXTURE.home : FIXTURE.away;
    setFormation(detectFormation(newRoster));
    setSelectedPid(null);
    setMinutesOverrides({});
  };

  const handleReset = () => {
    setFormation(referenceFormation);
    setSelectedPid(null);
    setMinutesOverrides({});
    setSavedAt(null);
  };

  const handleSave = () => {
    const slots = FORMATIONS[formation];
    const starters: (number | null)[] = slots.map(
      (_, idx) => onPitch.get(idx)?.pid ?? null,
    );
    const payload: SaveDelta = {
      side,
      formation,
      starters_pids: starters,
      minutes_overrides: Object.fromEntries(
        Object.entries(minutesOverrides).map(([k, v]) => [String(k), v]),
      ),
    };
    Streamlit.setComponentValue({
      action: "save",
      ts: Date.now(),
      payload,
    });
    setSavedAt(Date.now());
  };

  const selectedPlayer: Player | null = useMemo(() => {
    if (selectedPid == null) return null;
    return roster.find((p) => p.pid === selectedPid) ?? null;
  }, [selectedPid, roster]);

  const headerInfo = teamHeader(args ?? {});
  const isModified = formation !== referenceFormation || Object.keys(minutesOverrides).length > 0;

  return (
    <div
      ref={containerRef}
      style={{
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        color: "#0f172a",
        background: "transparent",
      }}
    >
      <style>{`@keyframes lineupPulse {
        0%, 100% { transform: scale(1); opacity: 0.55; }
        50% { transform: scale(1.18); opacity: 0.25; }
      }
      .lineup-pitch-btn:focus-visible {
        outline: 2px solid #0891b2;
        outline-offset: 2px;
      }`}</style>

      {/* Header match */}
      <div
        style={{
          background: "white",
          borderRadius: 12,
          padding: "10px 14px",
          marginBottom: 12,
          boxShadow: "0 2px 6px rgba(0,0,0,0.06)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 11,
              color: "#64748b",
              textTransform: "uppercase",
              letterSpacing: 0.5,
              fontWeight: 700,
            }}
          >
            {headerInfo.league}
          </div>
          <div style={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
            {headerInfo.match}
          </div>
          <div style={{ fontSize: 11, color: "#64748b" }}>
            {headerInfo.kickoff}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button
            onClick={handleReset}
            title="Restaurer la composition de référence (BSD/forward log)"
            style={{
              padding: "6px 10px",
              background: "#f1f5f9",
              border: "1px solid #cbd5e1",
              borderRadius: 6,
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 600,
              color: "#334155",
            }}
          >
            ↺ Reset
          </button>
          <button
            onClick={handleSave}
            disabled={!isModified}
            title={
              isModified
                ? "Sauvegarder la composition modifiée vers Python"
                : "Pas de modification à sauvegarder"
            }
            style={{
              padding: "6px 12px",
              background: isModified ? "#16a34a" : "#94a3b8",
              border: "none",
              borderRadius: 6,
              cursor: isModified ? "pointer" : "not-allowed",
              fontSize: 12,
              fontWeight: 700,
              color: "white",
            }}
          >
            {savedAt != null && Date.now() - savedAt < 3000
              ? "✓ Sauvegardé"
              : "💾 Save"}
          </button>
        </div>
      </div>

      {/* Toggle home/away + dropdown schéma */}
      <div
        style={{
          background: "white",
          borderRadius: 12,
          padding: 10,
          marginBottom: 12,
          boxShadow: "0 2px 6px rgba(0,0,0,0.06)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            background: "#f1f5f9",
            borderRadius: 8,
            padding: 2,
          }}
        >
          {(["home", "away"] as Side[]).map((s) => (
            <button
              key={s}
              onClick={() => handleSideChange(s)}
              style={{
                padding: "5px 14px",
                background: side === s ? "white" : "transparent",
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
                fontSize: 12,
                fontWeight: 700,
                color: side === s ? "#0f172a" : "#64748b",
                boxShadow:
                  side === s ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
              }}
            >
              {s === "home" ? FIXTURE.home_team : FIXTURE.away_team}
            </button>
          ))}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginLeft: "auto",
          }}
        >
          <label
            style={{
              fontSize: 11,
              color: "#64748b",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            Schéma
          </label>
          <select
            value={formation}
            onChange={(e) => {
              setFormation(e.target.value as FormationKey);
              setSelectedPid(null);
            }}
            style={{
              padding: "5px 8px",
              border: "1px solid #cbd5e1",
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 600,
              background: "white",
              cursor: "pointer",
            }}
          >
            {FORMATION_KEYS.map((k) => (
              <option key={k} value={k}>
                {k}
                {k === referenceFormation ? "  (référence BSD)" : ""}
              </option>
            ))}
          </select>
          {formation !== referenceFormation && (
            <span
              style={{
                fontSize: 10,
                padding: "2px 6px",
                background: "#fef3c7",
                color: "#78350f",
                borderRadius: 4,
                fontWeight: 700,
              }}
              title={`Référence détectée : ${referenceFormation}`}
            >
              OVERRIDE
            </span>
          )}
        </div>
      </div>

      {/* Layout 2 colonnes (terrain + panneau) ou 1 colonne empilée si étroit */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isNarrow
            ? "minmax(0, 1fr)"
            : "minmax(0, 1fr) " +
              (selectedPlayer ? "minmax(280px, 360px)" : "0px"),
          gridAutoFlow: "row",
          gap: selectedPlayer ? 12 : 0,
          alignItems: "start",
          transition: "grid-template-columns 200ms ease, gap 200ms ease",
        }}
      >
        <div>
          <Pitch
            formation={formation}
            onPitch={onPitch}
            selectedPid={selectedPid}
            onSelect={(pid) =>
              setSelectedPid((cur) => (cur === pid ? null : pid))
            }
          />
          <Bench
            players={bench}
            selectedPid={selectedPid}
            onSelect={(pid) =>
              setSelectedPid((cur) => (cur === pid ? null : pid))
            }
          />
        </div>

        {selectedPlayer && (
          <div style={{ overflow: "hidden" }}>
            <StatsPanel
              player={selectedPlayer}
              minutesOverride={
                selectedPid != null
                  ? (minutesOverrides[selectedPid] ?? null)
                  : null
              }
              onMinutesChange={(m) => {
                if (selectedPid == null) return;
                setMinutesOverrides((cur) => {
                  const next = { ...cur };
                  if (m == null) delete next[selectedPid];
                  else next[selectedPid] = m;
                  return next;
                });
              }}
              onClose={() => setSelectedPid(null)}
            />
          </div>
        )}
      </div>

      {/* Footer indicateur état */}
      {isModified && (
        <div
          style={{
            marginTop: 10,
            padding: "6px 10px",
            background: "#fef3c7",
            color: "#78350f",
            borderRadius: 6,
            fontSize: 11,
            fontWeight: 600,
            display: "inline-block",
          }}
        >
          Modifications non sauvegardées : schéma {formation} (réf{" "}
          {referenceFormation}) ·{" "}
          {Object.keys(minutesOverrides).length} override(s) minutes
        </div>
      )}
    </div>
  );
}
