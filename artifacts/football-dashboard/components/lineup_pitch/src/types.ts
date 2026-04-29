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
};

export type FormationKey =
  | "4-3-3"
  | "4-2-3-1"
  | "4-4-2"
  | "3-5-2"
  | "3-4-3"
  | "5-3-2";

export type Slot = {
  role: RoleBucket;
  x: number;
  y: number;
};

export type Assignment = {
  slot: Slot;
  player: Player | null;
};
