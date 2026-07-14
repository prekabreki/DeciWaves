"""HZD side-quest / DLC unlock points for near-chronological ordering.

Maps each non-main-quest top-level scene prefix to the story rank (main-quest beat)
it unlocks after, so `games.hzd.render.build_spine(..., episode_map=HZD_EPISODE_MAP)`
interleaves side/DLC content among the main quests instead of dumping it at the end.

Ranks align with the main-quest spine (mq01=1.0 .. mq16=16.0); a side questline at
N.5 plays after main quest N. Within a questline, order is the embedded sequence number
+ line_index (handled by build_spine, not here). Prefixes absent from this map fall back
to UNMAPPED_RANK in render.py (sorted last, never dropped).

Authored from HZD quest progression + docs/zero_dawn_gamescript.md. Confidence is
"logical near-chronological", not frame-exact. Notable judgment calls:
  * Open-world systems (bandit camps, cauldrons, hunting grounds, collectibles, shops,
    Nora-valley errands) -> 6.5 (unlock when Aloy leaves the Embrace after mq06).
  * Meridian / Sundom side quests (tca*, tcb*, tcc*, tcd*, tnb*, tnc*) -> 8.5 (after mq08).
  * Vanasha palace intrigue (tsa*) -> 10.5 (before the Sun-Ring betrayal).
  * Frozen Wilds (dlc1_*) -> 12.5 (mid-to-late, one rank for the whole expansion).
  * Nora endgame (tna*) -> 14.5 (after retaking the Embrace, mq14).
"""
from __future__ import annotations

HZD_EPISODE_MAP = {
    # Embrace / Nora valley + general open-world (unlock on leaving the Embrace, mq06)
    "banditcamps": 6.5,
    "collectables": 6.5,
    "commgiraffe": 6.5,
    "quest_huntingground": 6.5,
    "robotfoundry": 6.5,
    "shops": 6.5,
    "worldencountersdialog": 6.5,
    "worldlocation": 6.5,
    "tnd01_thewildboars": 6.5,
    "tnd02_shortofsupplies": 6.5,
    "tnd09_rostsgrave": 6.5,
    "tnd10_gerashusband": 6.5,
    "tnd11_sanctuary": 6.5,
    "tnd15_pointer_hgnoravalley": 6.5,
    "tnd16_pointer_noramesapass": 6.5,

    # Meridian / Carja heartland (unlock on reaching Meridian, after mq08)
    "hg_hunterslodge": 8.5,
    "tca01_fieldofthefallen": 8.5,
    "tca02_thetestinggrounds": 8.5,
    "tca03_thesunshallfall": 8.5,
    "tcb01_underequipped": 8.5,
    "tcb02_honorthefallen": 8.5,
    "tcb03_thejunkyard": 8.5,
    "tcb04_socialclimbers": 8.5,
    "tcb05_peacefulgrove": 8.5,
    "tcb06_sunstonerock": 8.5,
    "tcb07_supplychain": 8.5,
    "tcb08_acquired_taste": 8.5,
    "tcb09_sunandshadow": 8.5,
    "tcb10_dragonsroost": 8.5,
    "tcb11_killzone": 8.5,
    "tcb12_blackmarket": 8.5,
    "tcb13_blacklash": 8.5,
    "tcc01_gearrewards": 8.5,
    "tcd01_thetradersstruggle": 8.5,
    "tcd02_rescueolinsfamily": 8.5,
    "tcd03_thelostcarasoldier": 8.5,
    "tcd04_thedoctorserrand": 8.5,
    "tcd07_lakevillage": 8.5,
    "tcd08_thelostconvoy": 8.5,
    "tcd09_thefoodthieves": 8.5,
    "tcd11_hgq_firsttrial": 8.5,
    "tcd12_hgq_secondtrial": 8.5,
    "tcd15_pointer_hunterslodge": 8.5,
    "tnb01_theonethatgotaway": 8.5,
    "tnb02_theforgotten": 8.5,
    "tnb03_oddgrata": 8.5,
    "tnb04_adaughtersvengeance": 8.5,
    "tnb05_notsohiddencache": 8.5,
    "tnb11_killingbanditsforfun": 8.5,
    "tnc01_themetalman": 8.5,

    # Meridian palace intrigue (Vanasha arc, before the Sun-Ring betrayal)
    "tsa01_traitorsbounty": 10.5,
    "tsa02_queens_gambit": 10.5,

    # Frozen Wilds DLC (mid-to-late game; one rank for the whole family)
    "dlc1_bc08": 12.5,
    "dlc1_collectables": 12.5,
    "dlc1_commgiraffe": 12.5,
    "dlc1_hg6": 12.5,
    "dlc1_livingworld": 12.5,
    "dlc1_tba01": 12.5,
    "dlc1_tba02": 12.5,
    "dlc1_tba03": 12.5,
    "dlc1_tbb01": 12.5,
    "dlc1_tbb02": 12.5,
    "dlc1_tbb04": 12.5,
    "dlc1_tbb05": 12.5,
    "dlc1_tbd01": 12.5,
    "dlc1_tbd02": 12.5,
    "dlc1_tbd03": 12.5,
    "dlc1_tbd04": 12.5,
    "dlc1_tbd05": 12.5,
    "dlc1_tbd06": 12.5,
    "dlc1_worlddatapoints": 12.5,

    # Endgame Nora (post-retaking the Embrace, mq14)
    "tna01_tracking_sona": 14.5,
    "tna02_revengeofthenora": 14.5,
}
