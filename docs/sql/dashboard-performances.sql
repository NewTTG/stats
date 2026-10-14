-- Diagnostic du dashboard 24h, périmètre global (compte administrateur).
-- Lecture seule ; lancer chaque EXPLAIN séparément dans le bon schéma KPI.
-- EXPLAIN ANALYZE exécute réellement la lecture : comparer plusieurs passages.
-- Pour un périmètre restreint, ajouter le même filtre de cellules aux deux MAX.
-- Les index temporels existent dans le schéma documenté ; aucun CREATE INDEX requis.

-- LTE : ancienne découverte, celle des traces de 25 s / 20 s.
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT "DateHour" FROM "lte_cell_hour" WHERE "DateHour" IS NOT NULL ORDER BY "DateHour" DESC LIMIT 24;

-- LTE : nouvelle découverte par MAX indexés (au plus 24).
EXPLAIN (ANALYZE, BUFFERS)
WITH RECURSIVE heures(heure, rang) AS (
            SELECT MAX("DateHour"), 1 FROM "lte_cell_hour"
            WHERE "DateHour" IS NOT NULL
            UNION ALL
            SELECT (
                SELECT MAX("DateHour") FROM "lte_cell_hour"
                WHERE "DateHour" < h.heure
            ), h.rang + 1
            FROM heures h WHERE h.heure IS NOT NULL AND h.rang < 24
        )
        SELECT heure FROM heures WHERE heure IS NOT NULL;

-- LTE : compteurs lus pour les 24 heures trouvées.
-- Mêmes colonnes et filtres temporels que lire() ; ce diagnostic inclut aussi la découverte.
EXPLAIN (ANALYZE, BUFFERS)
WITH RECURSIVE heures(heure, rang) AS (
            SELECT MAX("DateHour"), 1 FROM "lte_cell_hour"
            WHERE "DateHour" IS NOT NULL
            UNION ALL
            SELECT (
                SELECT MAX("DateHour") FROM "lte_cell_hour"
                WHERE "DateHour" < h.heure
            ), h.rang + 1
            FROM heures h WHERE h.heure IS NOT NULL AND h.rang < 24
        )
        SELECT "EutranCell_Id" AS cellule, "DateHour" AS horodatage, "InitErabSuccRate_p", "PayloadDl_mB", "RrcConnMax_max_nb", "S1signalingSuccRate_p", "UserThpDl_kbps", "pmErabEstabAttInit", "pmRrcConnEstabAtt", "pmRrcConnEstabSucc", "pmS1SigConnEstabAtt" FROM "lte_cell_hour"
WHERE "DateHour" >= (SELECT MIN(heure)::date FROM heures)
  AND "DateHour" < (SELECT MAX(heure)::date + 1 FROM heures)
  AND "DateHour" IN (SELECT heure FROM heures WHERE heure IS NOT NULL);

-- WCDMA : ancienne découverte, celle des traces de 25 s / 20 s.
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT "DateHour" FROM "wcdma_cell_hour" WHERE "DateHour" IS NOT NULL ORDER BY "DateHour" DESC LIMIT 24;

-- WCDMA : nouvelle découverte par MAX indexés (au plus 24).
EXPLAIN (ANALYZE, BUFFERS)
WITH RECURSIVE heures(heure, rang) AS (
            SELECT MAX("DateHour"), 1 FROM "wcdma_cell_hour"
            WHERE "DateHour" IS NOT NULL
            UNION ALL
            SELECT (
                SELECT MAX("DateHour") FROM "wcdma_cell_hour"
                WHERE "DateHour" < h.heure
            ), h.rang + 1
            FROM heures h WHERE h.heure IS NOT NULL AND h.rang < 24
        )
        SELECT heure FROM heures WHERE heure IS NOT NULL;

-- WCDMA : compteurs lus pour les 24 heures trouvées.
-- Mêmes colonnes et filtres temporels que lire() ; ce diagnostic inclut aussi la découverte.
EXPLAIN (ANALYZE, BUFFERS)
WITH RECURSIVE heures(heure, rang) AS (
            SELECT MAX("DateHour"), 1 FROM "wcdma_cell_hour"
            WHERE "DateHour" IS NOT NULL
            UNION ALL
            SELECT (
                SELECT MAX("DateHour") FROM "wcdma_cell_hour"
                WHERE "DateHour" < h.heure
            ), h.rang + 1
            FROM heures h WHERE h.heure IS NOT NULL AND h.rang < 24
        )
        SELECT "CellWcdma" AS cellule, "DateHour" AS horodatage, "NbrSpeechCalls", "NbrSpeechCallsAtt", "PayloadPsHs_mb", "ReqCs", "ReqCsSucc", "SpeechTrafficDay_erlg", "UserThpHs_kbps" FROM "wcdma_cell_hour"
WHERE "DateHour" >= (SELECT MIN(heure)::date FROM heures)
  AND "DateHour" < (SELECT MAX(heure)::date + 1 FROM heures)
  AND "DateHour" IN (SELECT heure FROM heures WHERE heure IS NOT NULL);
