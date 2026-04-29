import type { FormationKey, Player, RoleBucket, Slot } from "./types";

export const FORMATIONS: Record<FormationKey, Slot[]> = {
  "4-3-3": [
    { role: "GK", x: 50, y: 92 },
    { role: "DEF", x: 15, y: 72 },
    { role: "DEF", x: 38, y: 75 },
    { role: "DEF", x: 62, y: 75 },
    { role: "DEF", x: 85, y: 72 },
    { role: "MID", x: 25, y: 50 },
    { role: "MID", x: 50, y: 53 },
    { role: "MID", x: 75, y: 50 },
    { role: "FWD", x: 20, y: 18 },
    { role: "FWD", x: 50, y: 12 },
    { role: "FWD", x: 80, y: 18 },
  ],
  "4-2-3-1": [
    { role: "GK", x: 50, y: 92 },
    { role: "DEF", x: 15, y: 72 },
    { role: "DEF", x: 38, y: 75 },
    { role: "DEF", x: 62, y: 75 },
    { role: "DEF", x: 85, y: 72 },
    { role: "MID", x: 35, y: 58 },
    { role: "MID", x: 65, y: 58 },
    { role: "MID", x: 20, y: 32 },
    { role: "MID", x: 50, y: 30 },
    { role: "MID", x: 80, y: 32 },
    { role: "FWD", x: 50, y: 12 },
  ],
  "4-4-2": [
    { role: "GK", x: 50, y: 92 },
    { role: "DEF", x: 15, y: 72 },
    { role: "DEF", x: 38, y: 75 },
    { role: "DEF", x: 62, y: 75 },
    { role: "DEF", x: 85, y: 72 },
    { role: "MID", x: 15, y: 47 },
    { role: "MID", x: 38, y: 50 },
    { role: "MID", x: 62, y: 50 },
    { role: "MID", x: 85, y: 47 },
    { role: "FWD", x: 35, y: 15 },
    { role: "FWD", x: 65, y: 15 },
  ],
  "3-5-2": [
    { role: "GK", x: 50, y: 92 },
    { role: "DEF", x: 25, y: 75 },
    { role: "DEF", x: 50, y: 78 },
    { role: "DEF", x: 75, y: 75 },
    { role: "MID", x: 10, y: 55 },
    { role: "MID", x: 30, y: 50 },
    { role: "MID", x: 50, y: 53 },
    { role: "MID", x: 70, y: 50 },
    { role: "MID", x: 90, y: 55 },
    { role: "FWD", x: 35, y: 15 },
    { role: "FWD", x: 65, y: 15 },
  ],
  "3-4-3": [
    { role: "GK", x: 50, y: 92 },
    { role: "DEF", x: 25, y: 75 },
    { role: "DEF", x: 50, y: 78 },
    { role: "DEF", x: 75, y: 75 },
    { role: "MID", x: 15, y: 50 },
    { role: "MID", x: 38, y: 53 },
    { role: "MID", x: 62, y: 53 },
    { role: "MID", x: 85, y: 50 },
    { role: "FWD", x: 20, y: 18 },
    { role: "FWD", x: 50, y: 12 },
    { role: "FWD", x: 80, y: 18 },
  ],
  "5-3-2": [
    { role: "GK", x: 50, y: 92 },
    { role: "DEF", x: 10, y: 70 },
    { role: "DEF", x: 30, y: 75 },
    { role: "DEF", x: 50, y: 78 },
    { role: "DEF", x: 70, y: 75 },
    { role: "DEF", x: 90, y: 70 },
    { role: "MID", x: 25, y: 47 },
    { role: "MID", x: 50, y: 50 },
    { role: "MID", x: 75, y: 47 },
    { role: "FWD", x: 35, y: 15 },
    { role: "FWD", x: 65, y: 15 },
  ],
};

const ROLE_OF: Record<string, RoleBucket> = {
  GK: "GK",
  G: "GK",
  GOALKEEPER: "GK",
  DEF: "DEF",
  D: "DEF",
  CB: "DEF",
  LB: "DEF",
  RB: "DEF",
  LWB: "DEF",
  RWB: "DEF",
  DEFENDER: "DEF",
  MID: "MID",
  M: "MID",
  CM: "MID",
  DM: "MID",
  AM: "MID",
  LM: "MID",
  RM: "MID",
  MIDFIELDER: "MID",
  FWD: "FWD",
  F: "FWD",
  ST: "FWD",
  SS: "FWD",
  LW: "FWD",
  RW: "FWD",
  CF: "FWD",
  FORWARD: "FWD",
};

export function bucketOf(pos: string): RoleBucket {
  const k = (pos || "").toUpperCase();
  return ROLE_OF[k] ?? "MID";
}

/** Auto-assignement : remplit chaque slot du schéma par le premier
 *  joueur compatible (par bucket de rôle) parmi les starters, puis
 *  retombe sur les non-starters si manque. Renvoie l'assignement +
 *  la liste des joueurs non placés. */
export function autoAssign(
  roster: Player[],
  formation: FormationKey,
): { onPitch: Map<number, Player>; bench: Player[] } {
  const slots = FORMATIONS[formation];
  const used = new Set<number>();
  const onPitch = new Map<number, Player>();
  const candidates = (role: RoleBucket) =>
    roster
      .filter((p) => p.pid != null && bucketOf(p.pos) === role && !used.has(p.pid as number))
      .sort((a, b) => {
        const sa = a.is_starter ? 0 : 1;
        const sb = b.is_starter ? 0 : 1;
        if (sa !== sb) return sa - sb;
        const aa = a.availability === "available" ? 0 : 1;
        const ab = b.availability === "available" ? 0 : 1;
        if (aa !== ab) return aa - ab;
        return (b.start_rate ?? 0) - (a.start_rate ?? 0);
      });
  slots.forEach((slot, idx) => {
    const pool = candidates(slot.role);
    if (pool.length > 0) {
      const pick = pool[0];
      used.add(pick.pid as number);
      onPitch.set(idx, pick);
    }
  });
  // Si certains slots vides (rare), prendre n'importe quel joueur encore dispo
  slots.forEach((_, idx) => {
    if (!onPitch.has(idx)) {
      const fallback = roster.find(
        (p) => p.pid != null && !used.has(p.pid as number),
      );
      if (fallback) {
        used.add(fallback.pid as number);
        onPitch.set(idx, fallback);
      }
    }
  });
  const bench = roster.filter((p) => p.pid != null && !used.has(p.pid as number));
  return { onPitch, bench };
}

/** Détecte le schéma "naturel" du roster : compte les starters par rôle
 *  et matche au schéma le plus proche. */
export function detectFormation(roster: Player[]): FormationKey {
  const starters = roster.filter((p) => p.is_starter);
  let nDef = 0,
    nMid = 0,
    nFwd = 0;
  starters.forEach((p) => {
    const b = bucketOf(p.pos);
    if (b === "DEF") nDef++;
    else if (b === "MID") nMid++;
    else if (b === "FWD") nFwd++;
  });
  const sig = `${nDef}-${nMid}-${nFwd}`;
  if (sig in FORMATIONS) return sig as FormationKey;
  // Fallback : 4-3-3 si on a 4+ DEF et 3+ FWD, sinon 4-2-3-1
  if (nDef >= 4 && nFwd >= 3) return "4-3-3";
  if (nDef >= 4) return "4-2-3-1";
  if (nDef === 3 && nFwd >= 3) return "3-4-3";
  if (nDef === 3) return "3-5-2";
  return "4-3-3";
}
