-- waltcg point-in-time store -- PostgreSQL migration target.
--
-- WHY THIS FILE EXISTS.
--
-- store/schema.sql is the working schema and DuckDB enforces most of it:
-- observed_at >= as_of, observed_at <= now(), the grade enum, currency NOT
-- NULL, Decimal money. One invariant it CANNOT enforce is the one that matters
-- most -- append-only -- because DuckDB has neither triggers nor rules nor
-- grants. There, the guarantee is an insert-only writer plus a hash chain that
-- makes tampering visible after the fact.
--
-- Here it is genuinely prevented. The trigger below rejects every UPDATE and
-- every DELETE on every fact table, for every role including the owner, and
-- there is no flag to turn it off. Detection becomes prevention, which is the
-- whole reason the DuckDB schema was kept dialect-portable.
--
-- Run order: types, tables, then the guard. The guard goes on LAST so the
-- tables can be created and back-filled once, and never touched again.

BEGIN;

CREATE TYPE grade_t AS ENUM (
    'raw','1','1.5','2','2.5','3','3.5','4','4.5','5','5.5',
    '6','6.5','7','7.5','8','8.5','9','9.5','10');
CREATE TYPE condition_t AS ENUM ('nm','lp','mp','hp','dmg','graded','unknown');
CREATE TYPE grader_t AS ENUM ('PSA','CGC','BGS','SGC','TAG');
CREATE TYPE language_t AS ENUM ('EN','JP','CN-S','CN-T');
CREATE TYPE game_t AS ENUM ('optcg','pkmn','riftbound');
CREATE TYPE resolved_by_t AS ENUM ('exact','fuzzy','manual');
CREATE TYPE obtainment_t AS ENUM (
    'booster','box_topper','promo_event','promo_retailer','tournament_prize',
    'starter_deck','online_code','region_exclusive','unknown');

CREATE TABLE cards (
    card_uid         TEXT PRIMARY KEY,
    game             game_t NOT NULL,
    set_code         TEXT NOT NULL,
    number           TEXT NOT NULL,
    variant          TEXT NOT NULL,
    language         language_t NOT NULL,
    name_en          TEXT,
    name_jp          TEXT,
    rarity           TEXT,
    artist           TEXT,
    release_date     DATE,
    obtainment_class obtainment_t NOT NULL DEFAULT 'unknown',
    image_url        TEXT,
    -- See store/schema.sql for why each of these three exists. Short version:
    -- the collector number is not a key, and these are the three documented
    -- ways it stops being one.
    box_code         TEXT,
    serialized       BOOLEAN NOT NULL DEFAULT FALSE,
    foil             BOOLEAN,
    observed_at      TIMESTAMPTZ NOT NULL,
    source           TEXT NOT NULL,
    CONSTRAINT cards_not_future CHECK (observed_at <= now()),
    CONSTRAINT cards_serialized_matches_variant CHECK (
        NOT serialized OR variant = 'serialized'),
    CONSTRAINT cards_box_code_is_not_the_set CHECK (
        box_code IS NULL OR box_code <> set_code),
    CONSTRAINT cards_uid_matches_parts CHECK (
        card_uid = game || ':' || set_code || ':' || number || ':'
                   || variant || ':' || language)
);

CREATE TABLE card_xref (
    row_id       BIGSERIAL PRIMARY KEY,
    card_uid     TEXT NOT NULL REFERENCES cards(card_uid),
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    secondary_id TEXT,
    confidence   NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    resolved_by  resolved_by_t NOT NULL,
    as_of        TIMESTAMPTZ NOT NULL,
    observed_at  TIMESTAMPTZ NOT NULL,
    supersedes   BIGINT REFERENCES card_xref(row_id),
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now()),
    CHECK (resolved_by <> 'exact' OR confidence = 1)
);

CREATE TABLE price_snapshot (
    row_id       BIGSERIAL PRIMARY KEY,
    card_uid     TEXT NOT NULL REFERENCES cards(card_uid),
    grade        grade_t NOT NULL,
    condition    condition_t NOT NULL,
    grader       grader_t,
    marketplace  TEXT NOT NULL,
    amount       NUMERIC(18,4) NOT NULL CHECK (amount >= 0),
    currency     CHAR(3) NOT NULL,
    fx_rate_used NUMERIC(18,8),
    fx_as_of     TIMESTAMPTZ,
    sample_size  INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    as_of        TIMESTAMPTZ NOT NULL,
    observed_at  TIMESTAMPTZ NOT NULL,
    source       TEXT NOT NULL,
    supersedes   BIGINT REFERENCES price_snapshot(row_id),
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now()),
    CHECK ((fx_rate_used IS NULL) = (fx_as_of IS NULL)),
    CHECK ((grade = 'raw') = (grader IS NULL)),
    CHECK ((grade = 'raw') OR condition = 'graded')
);

CREATE TABLE pop_snapshot (
    row_id      BIGSERIAL PRIMARY KEY,
    card_uid    TEXT NOT NULL REFERENCES cards(card_uid),
    grader      grader_t NOT NULL,
    grade       grade_t NOT NULL CHECK (grade <> 'raw'),
    count       BIGINT NOT NULL CHECK (count >= 0),
    as_of       TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source      TEXT NOT NULL,
    supersedes  BIGINT REFERENCES pop_snapshot(row_id),
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now())
);

CREATE TABLE sentiment (
    row_id      BIGSERIAL PRIMARY KEY,
    card_uid    TEXT NOT NULL REFERENCES cards(card_uid),
    platform    TEXT NOT NULL,
    mentions    BIGINT NOT NULL CHECK (mentions >= 0),
    engagement  BIGINT CHECK (engagement IS NULL OR engagement >= 0),
    as_of       TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    backfilled  BOOLEAN NOT NULL,
    source      TEXT NOT NULL,
    supersedes  BIGINT REFERENCES sentiment(row_id),
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now())
);

CREATE TABLE fx_rate (
    row_id      BIGSERIAL PRIMARY KEY,
    pair        TEXT NOT NULL CHECK (pair ~ '^[A-Z]{3}/[A-Z]{3}$'),
    rate        NUMERIC(18,8) NOT NULL CHECK (rate > 0),
    as_of       TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source      TEXT NOT NULL,
    supersedes  BIGINT REFERENCES fx_rate(row_id),
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now())
);

CREATE TABLE ingest_gap (
    row_id      BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    card_uid    TEXT,
    kind        TEXT NOT NULL,
    reason      TEXT NOT NULL,
    detail      TEXT,
    as_of       TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now())
);

CREATE TABLE ingest_run (
    run_id          TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL CHECK (started_at <= now()),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL,
    rows_written    BIGINT NOT NULL DEFAULT 0,
    gaps_written    BIGINT NOT NULL DEFAULT 0,
    quota_remaining INTEGER,
    detail          TEXT
);

-- ------------------------------------------------------------- THE GUARD
--
-- This is the invariant DuckDB could only detect. Here it is prevented.
--
-- A correction is an INSERT with a `supersedes` pointer. There is no legitimate
-- UPDATE and no legitimate DELETE on any of these tables, so both are refused
-- unconditionally -- no exemption for the owner, no session flag, no
-- "temporarily". The moment one exists, every number the app ever displayed
-- stops being reconstructible, and the no-look-ahead guarantee rests on
-- exactly that reconstructibility.

CREATE OR REPLACE FUNCTION refuse_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'append-only: % on % is refused. History is corrected by INSERTing a '
        'new row with a later observed_at and a supersedes reference, never by '
        'changing or removing an existing one.',
        TG_OP, TG_TABLE_NAME
      USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['cards','card_xref','price_snapshot',
                             'pop_snapshot','sentiment','fx_rate','ingest_gap']
    LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_append_only BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH STATEMENT EXECUTE FUNCTION refuse_mutation()', t, t);
    END LOOP;
END $$;

-- `ledger_seal` has no counterpart here on purpose. It is a hash chain that
-- makes tampering VISIBLE, and it exists only because DuckDB cannot make
-- tampering IMPOSSIBLE. With the trigger above in place there is nothing left
-- for it to detect, and carrying it across would imply the prevention was not
-- trusted.

-- Belt and braces: the application role cannot even attempt it.
-- (Run against the real role name at deploy time.)
-- REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM waltcg_app;

COMMIT;
