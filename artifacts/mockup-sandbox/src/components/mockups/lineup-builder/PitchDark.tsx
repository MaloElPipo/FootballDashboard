import { Sparkles, RotateCcw, Users } from "lucide-react";

type Player = { name: string; jersey: number; status?: "doubtful" | "injured" | "suspended" };

const formation = {
  GK: [{ name: "Chevalier", jersey: 30 }],
  DEF: [
    { name: "Hakimi", jersey: 2 },
    { name: "Marquinhos", jersey: 5 },
    { name: "Pacho", jersey: 51 },
    { name: "Beraldo", jersey: 35 },
  ],
  MID: [
    { name: "Vitinha", jersey: 17, status: "doubtful" as const },
    { name: "Zaïre-Emery", jersey: 33 },
    { name: "Neves", jersey: 87 },
  ],
  FWD: [
    { name: "Doué", jersey: 14, status: "doubtful" as const },
    { name: "Dembélé", jersey: 10 },
    { name: "Kvaratskhelia", jersey: 7 },
  ],
};

function StatusDot({ s }: { s?: Player["status"] }) {
  if (!s) return null;
  const colorMap = {
    doubtful: "bg-amber-400 shadow-amber-400/50",
    injured: "bg-red-500 shadow-red-500/50",
    suspended: "bg-orange-500 shadow-orange-500/50",
  };
  return <span className={`absolute top-0.5 right-0.5 w-2.5 h-2.5 rounded-full ring-2 ring-slate-900 shadow-lg ${colorMap[s]}`} />;
}

function PlayerChip({ p }: { p: Player }) {
  return (
    <div className="flex flex-col items-center gap-1 cursor-pointer hover:scale-105 transition">
      <div className="relative">
        <div className="w-12 h-12 rounded-md bg-gradient-to-br from-red-500 to-red-700 ring-1 ring-white/40 shadow-[0_4px_20px_rgba(239,68,68,0.4)] flex items-center justify-center">
          <span className="text-white font-black text-base font-mono">{p.jersey}</span>
        </div>
        <StatusDot s={p.status} />
      </div>
      <div className="text-[10px] text-white font-bold uppercase tracking-wide drop-shadow-lg">{p.name}</div>
    </div>
  );
}

export function PitchDark() {
  return (
    <div className="min-h-screen bg-slate-950 p-6 font-sans">
      <div className="max-w-md mx-auto space-y-3">
        {/* Header */}
        <div className="border border-slate-800 bg-slate-900/80 backdrop-blur rounded-lg p-3">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Domicile</div>
              <div className="font-black text-white text-lg leading-tight">PARIS SG</div>
            </div>
            <div className="flex flex-col items-end gap-1">
              <div className="text-[10px] text-slate-500 uppercase tracking-widest">Schéma</div>
              <select className="bg-slate-950 text-white text-xs border border-slate-700 rounded px-2 py-1 font-mono font-bold">
                <option>4-3-3</option>
                <option>4-2-3-1</option>
                <option>4-4-2</option>
                <option>3-5-2</option>
                <option>3-4-3</option>
                <option>5-3-2</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button className="flex items-center justify-center gap-1.5 bg-gradient-to-r from-red-600 to-red-500 hover:from-red-500 hover:to-red-400 text-white text-[11px] font-bold uppercase tracking-wide py-2 rounded transition shadow-[0_2px_10px_rgba(239,68,68,0.3)]">
              <Sparkles className="w-3.5 h-3.5" /> Auto-fill
            </button>
            <button className="flex items-center justify-center gap-1.5 border border-slate-700 hover:bg-slate-800 text-slate-300 text-[11px] font-bold uppercase tracking-wide py-2 rounded transition">
              <RotateCcw className="w-3.5 h-3.5" /> Reset
            </button>
          </div>
        </div>

        {/* Tactical board */}
        <div className="relative rounded-lg overflow-hidden border-2 border-slate-800" style={{ aspectRatio: "3/4" }}>
          {/* Dark turf */}
          <div className="absolute inset-0 bg-gradient-to-b from-emerald-950 via-emerald-900 to-emerald-950" />
          <div className="absolute inset-0" style={{
            background: "repeating-linear-gradient(0deg, transparent 0px, transparent 50px, rgba(255,255,255,0.025) 50px, rgba(255,255,255,0.025) 100px)"
          }} />
          {/* Pitch markings */}
          <svg className="absolute inset-0 w-full h-full" viewBox="0 0 300 400" preserveAspectRatio="none">
            <rect x="10" y="10" width="280" height="380" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" fill="none" />
            <line x1="10" y1="200" x2="290" y2="200" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" />
            <circle cx="150" cy="200" r="40" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" fill="none" />
            <circle cx="150" cy="200" r="2" fill="rgba(255,255,255,0.5)" />
            <rect x="80" y="10" width="140" height="50" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" fill="none" />
            <rect x="80" y="340" width="140" height="50" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" fill="none" />
            <rect x="115" y="10" width="70" height="20" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" fill="none" />
            <rect x="115" y="370" width="70" height="20" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" fill="none" />
          </svg>
          {/* Players */}
          <div className="absolute inset-0 flex flex-col justify-around py-5">
            <div className="flex justify-around px-6">
              {formation.FWD.map(p => <PlayerChip key={p.name} p={p} />)}
            </div>
            <div className="flex justify-around px-10">
              {formation.MID.map(p => <PlayerChip key={p.name} p={p} />)}
            </div>
            <div className="flex justify-around px-3">
              {formation.DEF.map(p => <PlayerChip key={p.name} p={p} />)}
            </div>
            <div className="flex justify-center">
              {formation.GK.map(p => <PlayerChip key={p.name} p={p} />)}
            </div>
          </div>
        </div>

        {/* Status legend */}
        <div className="flex items-center justify-between text-[10px] uppercase tracking-wider">
          <div className="flex items-center gap-1.5 text-slate-500">
            <Users className="w-3 h-3" /> 11 / 11
          </div>
          <div className="flex gap-3">
            <span className="flex items-center gap-1 text-amber-400"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> Doute</span>
            <span className="flex items-center gap-1 text-red-400"><span className="w-1.5 h-1.5 rounded-full bg-red-500" /> Blessé</span>
            <span className="flex items-center gap-1 text-orange-400"><span className="w-1.5 h-1.5 rounded-full bg-orange-500" /> Susp.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
