export type Side = "home" | "away";

export type Availability = "available" | "doubtful" | "injured" | "suspended";

export type RoleBucket = "GK" | "DEF" | "MID" | "FWD";

export type Player = {
  pid: number | null;
  name: string;
  pos: string;
  team_side: Side;
  is_starter: boolean;
  availability: Availability;
  injury_type: string | null;
  fair_scorer: number | null;
  betclic_scorer: number | null;
  edge_scorer: number | null;
  fair_assist: number | null;
  betclic_assist: number | null;
  edge_assist: number | null;
  xg_player: number | null;
  xa_player: number | null;
  xg_p90: number | null;
  xa_p90: number | null;
  expected_shots: number | null;
  expected_shots_on_target: number | null;
  shots_p90: number | null;
  shots_on_p90: number | null;
  minutes_expected: number | null;
  start_rate: number | null;
  jersey_number: number | null;
};

export type SavedLineup = {
  side: Side;
  formation: FormationKey;
  // Liste alignée sur l'ordre des slots du `formation` (len == 11). Un
  // élément null signifie qu'aucun joueur n'a été assigné à ce slot
  // (cas rare : roster < 11 ou slot vidé manuellement).
  starters_pids: (number | null)[];
  // Map pid (string car JSON) → minutes attendues (override utilisateur).
  minutes_overrides: Record<string, number>;
  saved_at_ms?: number;
};

export type SavedOverrides = {
  home: SavedLineup | null;
  away: SavedLineup | null;
};

export type MatchData = {
  event_id: number;
  home_team: string;
  away_team: string;
  kickoff: string | null;
  league: string;
  xg_team_home: number | null;
  xg_team_away: number | null;
  home: Player[];
  away: Player[];
  // Compositions manuelles déjà sauvegardées par l'utilisateur (chargées
  // depuis live/data/lineup_overrides/{event_id}.json par Python). Si
  // présent, le composant React rehydrate l'état au mount + au changement
  // de side, plutôt que de partir de la compo auto-détectée.
  saved_overrides?: SavedOverrides | null;
};

export type FormationKey =
  | "4-3-3"
  | "4-2-3-1"
  | "4-4-2"
  | "3-5-2"
  | "3-4-3"
  | "5-3-2"
  | "4-5-1"
  | "4-1-4-1"
  | "5-4-1";

export type Slot = {
  role: RoleBucket;
  x: number;
  y: number;
};

export type Assignment = {
  slot: Slot;
  player: Player | null;
};
