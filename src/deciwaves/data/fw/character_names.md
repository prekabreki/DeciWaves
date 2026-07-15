# Forbidden West character names (ASR priming roster)

Auto-derived from `docs/forbidden_west_gamescript.md` speaker labels (`^Name:`, count >= 3). Feeds the WhisperX `initial_prompt`/`hotwords` for the FW ASR-binding stage to cut name mistranscriptions at the source (e.g. ALOY heard as "Eli", GAIA/HADES/HEPHAESTUS garbled).

Regenerate: re-parse `docs/forbidden_west_gamescript.md` for `^Name:` speaker labels and
re-tally by count (this file was generated ad hoc 2026-06-27; no maintained script does
this). Review before use — a few generic role labels (Tenakth Soldier, Quen Guard, …) are
kept for order/context but excluded from the hotword prompt below.

## WhisperX initial_prompt (proper nouns)

```initial_prompt
Aloy, Varl, Zo, Erend, Alva, GAIA, Kotallo, Tilda van der Meer, Beta, Sylens, Talanah, Dekka, Morlund, Hekarro, Ceo, Lawan, Synthetic Voice, Bohai, Amadis, Petra, Ulvund, Javad the Willing, Abadund, Silga, Kue, Natikka, Marshal Fashav, HADES, Lokasha, Arokkeh, Penttoh, Stemmur, Avad, Ivvira, Regalla, Kavvoh, Studious Vuadis, HEPHAESTUS, Ritakka, Delah, Larend, Erik, Porguf, Vanasha, Wekatta, Karhn, Milduf, Thurlis, Nozar, Untalla, Ragurt, Kivva, Joruf, Belna, Tolland Cleanbroker, Keruf, Gerard, Uthid, Hakund, Kitakka, Hataktto, Tekotteh, Travis Tate, Blameless Marad, Ivinna, Jekkah, Littay, Telga, Boomer, Savohar, Rokko, Amuf, Odurg, Salma, Vetteh, Zokkah, Kentokk, Kenalla, Aldur, Mian, Luf, Corend, Erayyo, Lirokkeh, Nirik, Itamen, Volma, Fendur, Elisabet Sobeck, Milu, Lel, Fane, Gerrah, Verbena, Isabel, Nasadi, Minda, Lunda, Ziverra, Nakko, Eileen Sasaki, Nakalla, Osvald Dalgaard, MINERVA, Rukka, Jorund, Terakka, Litakka, Tekatteh, Vetten, Aquino, Quen Soldier 2, Yivekka
```

## Full roster (129 labels, by line count)

| count | speaker |
|------:|---------|
| 3034 | Aloy |
| 390 | Varl |
| 300 | Zo |
| 247 | Erend |
| 244 | Alva |
| 228 | GAIA |
| 222 | Kotallo |
| 163 | Tilda van der Meer |
| 131 | Beta |
| 119 | Sylens |
| 82 | Talanah |
| 66 | Dekka |
| 64 | Morlund |
| 51 | Hekarro |
| 46 | Ceo |
| 40 | Lawan |
| 39 | Synthetic Voice |
| 37 | Bohai |
| 36 | Amadis |
| 35 | Petra |
| 35 | Ulvund |
| 34 | Javad the Willing |
| 33 | Abadund |
| 32 | Silga |
| 32 | Kue |
| 29 | Natikka |
| 27 | Marshal Fashav |
| 26 | HADES |
| 26 | Lokasha |
| 25 | Tenakth Survivor |
| 23 | Arokkeh |
| 22 | Penttoh |
| 22 | Stemmur |
| 21 | Avad |
| 20 | Ivvira |
| 19 | Regalla |
| 19 | Kavvoh |
| 18 | Studious Vuadis |
| 17 | Tenakth Soldier |
| 17 | HEPHAESTUS |
| 17 | Ritakka |
| 16 | Delah |
| 16 | Larend |
| 16 | Erik |
| 16 | Porguf |
| 15 | Oseram Worker |
| 15 | Vanasha |
| 15 | Wekatta |
| 13 | Karhn |
| 13 | Milduf |
| 13 | Thurlis |
| 13 | Nozar |
| 13 | Untalla |
| 13 | Ragurt |
| 13 | Quen Marine |
| 12 | Kivva |
| 11 | Joruf |
| 11 | Belna |
| 11 | Tolland Cleanbroker |
| 11 | Keruf |
| 11 | Tenakth High Marshal |
| 11 | Gerard |
| 10 | Uthid |
| 10 | Hakund |
| 10 | Kitakka |
| 10 | Hataktto |
| 10 | Tekotteh |
| 9 | Travis Tate |
| 9 | Blameless Marad |
| 9 | Carja Guard |
| 9 | Ivinna |
| 9 | Jekkah |
| 9 | Littay |
| 8 | Telga |
| 8 | Boomer |
| 8 | Male Stranger |
| 8 | Savohar |
| 8 | Narrator |
| 8 | Rokko |
| 7 | Amuf |
| 7 | Odurg |
| 7 | Salma |
| 7 | Vetteh |
| 7 | Zokkah |
| 7 | Kentokk |
| 7 | Kenalla |
| 6 | Aldur |
| 6 | Mian |
| 6 | Luf |
| 6 | Corend |
| 6 | Erayyo |
| 6 | Tenakth Climber |
| 6 | Utaru Archer |
| 6 | Lirokkeh |
| 6 | Nirik |
| 5 | Itamen |
| 5 | Volma |
| 5 | Fendur |
| 5 | Tenakth Marshal |
| 5 | Elisabet Sobeck |
| 5 | Milu |
| 5 | Lel |
| 5 | Fane |
| 5 | Rebel Soldier |
| 5 | Gerrah |
| 5 | Verbena |
| 5 | Isabel |
| 4 | Nasadi |
| 4 | Minda |
| 4 | Lunda |
| 4 | Tenakth Guard |
| 4 | Ziverra |
| 4 | Quen Guard |
| 4 | Nakko |
| 4 | Eileen Sasaki |
| 4 | Nakalla |
| 3 | Osvald Dalgaard |
| 3 | Carja Citizen |
| 3 | Female Stranger |
| 3 | MINERVA |
| 3 | Rukka |
| 3 | Jorund |
| 3 | Terakka |
| 3 | Litakka |
| 3 | Tekatteh |
| 3 | Vetten |
| 3 | Aquino |
| 3 | Quen Soldier 2 |
| 3 | Yivekka |
