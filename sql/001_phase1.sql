CREATE TABLE IF NOT EXISTS venue_master (
    venue_code SMALLINT PRIMARY KEY CHECK (venue_code BETWEEN 1 AND 24),
    venue_name TEXT NOT NULL,
    code_source TEXT NOT NULL DEFAULT 'boatraceopenapi v1 codes.md'
);

INSERT INTO venue_master (venue_code, venue_name) VALUES
    (1, '桐生'), (2, '戸田'), (3, '江戸川'), (4, '平和島'),
    (5, '多摩川'), (6, '浜名湖'), (7, '蒲郡'), (8, '常滑'),
    (9, '津'), (10, '三国'), (11, 'びわこ'), (12, '住之江'),
    (13, '尼崎'), (14, '鳴門'), (15, '丸亀'), (16, '児島'),
    (17, '宮島'), (18, '徳山'), (19, '下関'), (20, '若松'),
    (21, '芦屋'), (22, '福岡'), (23, '唐津'), (24, '大村')
ON CONFLICT (venue_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id UUID PRIMARY KEY,
    target_date DATE NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    source_url TEXT NOT NULL,
    fetch_status TEXT NOT NULL CHECK (fetch_status IN ('success', 'failed')),
    validation_status TEXT NOT NULL CHECK (validation_status IN ('valid', 'invalid', 'unconfirmed')),
    http_status INTEGER,
    payload_sha256 CHAR(64),
    raw_payload BYTEA
);

CREATE TABLE IF NOT EXISTS venue_acquisition_history (
    history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES ingestion_runs(run_id),
    venue_code SMALLINT NOT NULL REFERENCES venue_master(venue_code),
    target_date DATE NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    fetch_status TEXT NOT NULL CHECK (fetch_status IN ('not_attempted', 'success', 'failed')),
    json_presence TEXT NOT NULL CHECK (json_presence IN ('present', 'absent', 'not_observed')),
    data_status TEXT NOT NULL CHECK (data_status IN ('not_attempted', 'fetch_failed', 'json_absent', 'success', 'invalid')),
    validation_status TEXT NOT NULL CHECK (validation_status IN ('valid', 'invalid', 'unconfirmed')),
    calendar_status TEXT NOT NULL CHECK (calendar_status IN ('scheduled', 'no_event', 'unconfirmed')),
    race_count INTEGER CHECK (race_count IS NULL OR race_count >= 0),
    calendar_source TEXT,
    calendar_evidence TEXT,
    UNIQUE (run_id, venue_code)
);

CREATE INDEX IF NOT EXISTS venue_history_by_target
    ON venue_acquisition_history (target_date, venue_code, observed_at DESC);

CREATE TABLE IF NOT EXISTS validation_findings (
    finding_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES ingestion_runs(run_id),
    scope TEXT NOT NULL CHECK (scope IN ('file', 'race', 'field')),
    severity TEXT NOT NULL CHECK (severity IN ('error', 'unconfirmed')),
    code TEXT NOT NULL,
    field_path TEXT NOT NULL,
    message TEXT NOT NULL,
    venue_code SMALLINT REFERENCES venue_master(venue_code),
    race_number SMALLINT,
    expected_type TEXT,
    actual_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE FUNCTION reject_phase1_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Phase 1 history is append-only';
END;
$$;

DROP TRIGGER IF EXISTS ingestion_runs_immutable ON ingestion_runs;
CREATE TRIGGER ingestion_runs_immutable
BEFORE UPDATE OR DELETE ON ingestion_runs
FOR EACH ROW EXECUTE FUNCTION reject_phase1_history_mutation();

DROP TRIGGER IF EXISTS venue_history_immutable ON venue_acquisition_history;
CREATE TRIGGER venue_history_immutable
BEFORE UPDATE OR DELETE ON venue_acquisition_history
FOR EACH ROW EXECUTE FUNCTION reject_phase1_history_mutation();

DROP TRIGGER IF EXISTS validation_findings_immutable ON validation_findings;
CREATE TRIGGER validation_findings_immutable
BEFORE UPDATE OR DELETE ON validation_findings
FOR EACH ROW EXECUTE FUNCTION reject_phase1_history_mutation();
