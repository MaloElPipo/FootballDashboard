import React from "react";
import { FORMATIONS } from "../formations";
import type { FormationKey, Player } from "../types";
import { PlayerDot } from "./PlayerDot";

/**
 * Terrain en mode "tableau tactique" : fond bleu nuit avec halo cyan
 * lumineux en haut, lignes blanches lumineuses, légère perspective via
 * un dégradé radial (sans transform 3D pour ne pas casser le positionnement).
 *
 * Largeur max : limitée à 380px pour rester compact (style maquette).
 */
export function Pitch({
  formation,
  onPitch,
  selectedPid,
  swapSourcePid,
  teamName,
  onSelect,
}: {
  formation: FormationKey;
  onPitch: Map<number, Player>;
  selectedPid: number | null;
  swapSourcePid: number | null;
  teamName?: string;
  onSelect: (pid: number) => void;
}) {
  const slots = FORMATIONS[formation];
  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        maxWidth: 380,
        margin: "0 auto",
        aspectRatio: "3 / 4",
        borderRadius: 14,
        overflow: "hidden",
        boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
        background:
          "radial-gradient(ellipse at 50% 0%, rgba(34,211,238,0.35) 0%, rgba(34,211,238,0.08) 30%, rgba(15,23,42,0) 60%), linear-gradient(180deg, #0c1b3d 0%, #0a1734 50%, #07122a 100%)",
      }}
    >
      {/* Halo lumineux supérieur (effet "scène") */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 16,
          background:
            "linear-gradient(180deg, rgba(34,211,238,0.6) 0%, rgba(34,211,238,0) 100%)",
          pointerEvents: "none",
        }}
      />
      <svg
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        viewBox="0 0 300 400"
        preserveAspectRatio="none"
      >
        {/* Lignes blanches lumineuses, opacité plus faible pour le feel sombre */}
        <defs>
          <filter id="lineGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="1.2" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g
          stroke="#cbd5e1"
          strokeWidth="1.5"
          fill="none"
          opacity="0.55"
          filter="url(#lineGlow)"
        >
          <rect x="10" y="10" width="280" height="380" />
          <line x1="10" y1="200" x2="290" y2="200" />
          <circle cx="150" cy="200" r="38" />
          <circle cx="150" cy="200" r="2.5" fill="#cbd5e1" stroke="none" opacity="1" />
          <rect x="80" y="10" width="140" height="50" />
          <rect x="80" y="340" width="140" height="50" />
          <rect x="115" y="10" width="70" height="20" />
          <rect x="115" y="370" width="70" height="20" />
        </g>
      </svg>
      {slots.map((slot, idx) => {
        const player = onPitch.get(idx) ?? null;
        const isSelected = !!player && player.pid === selectedPid;
        const isSwapSource = !!player && player.pid === swapSourcePid;
        // En mode swap : tous les joueurs SAUF la source sont des cibles
        // potentielles (highlight orange) ; la source elle-même garde le halo cyan.
        const isSwapTarget =
          swapSourcePid != null && player?.pid != null && !isSwapSource;
        return (
          <PlayerDot
            key={idx}
            player={player}
            x={slot.x}
            y={slot.y}
            selected={isSelected || isSwapSource}
            swapHighlight={isSwapTarget}
            teamName={teamName}
            onClick={() => {
              if (player?.pid != null) onSelect(player.pid);
            }}
          />
        );
      })}
    </div>
  );
}
