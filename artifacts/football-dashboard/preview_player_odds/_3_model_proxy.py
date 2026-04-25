"""Re-export propre des fonctions du modèle (le fichier 3_model.py commence par
un chiffre, ce qui empêche l'import direct depuis le scope live/)."""
import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("preview_player_odds._3_model", _HERE / "3_model.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

aggregate_player_pool = _mod.aggregate_player_pool
distribute_xg_to_players = _mod.distribute_xg_to_players
get_lineup_players = _mod.get_lineup_players
shrunk_per90 = _mod.shrunk_per90
is_goalkeeper = _mod.is_goalkeeper
parse_event_date = _mod.parse_event_date
apply_anti_poisson_calibration = _mod.apply_anti_poisson_calibration
position_prior = _mod.position_prior
career_blended_xg_per_90 = _mod.career_blended_xg_per_90
career_confidence_ratio = _mod.career_confidence_ratio
career_g90 = _mod.career_g90

# Constantes utiles
LEAGUE_PRIOR_XG90_OUTFIELD = _mod.LEAGUE_PRIOR_XG90_OUTFIELD
LEAGUE_PRIOR_XA90_OUTFIELD = _mod.LEAGUE_PRIOR_XA90_OUTFIELD
SHRINKAGE_K = _mod.SHRINKAGE_K
MINUTES_STARTER_DEFAULT = _mod.MINUTES_STARTER_DEFAULT
MINUTES_SUB_DEFAULT = _mod.MINUTES_SUB_DEFAULT
CAREER_FULL_TRUST_MINUTES = _mod.CAREER_FULL_TRUST_MINUTES
CAREER_MIN_USABLE_MINUTES = _mod.CAREER_MIN_USABLE_MINUTES
