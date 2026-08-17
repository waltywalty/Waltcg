-- waltcg point-in-time store -- DuckDB dialect.
--
-- Every table here is a LOG, not a state. Nothing is updated and nothing is
-- deleted: a correction is a new row with a later observed_at and a
-- `supersedes` pointer at the row it replaces. The current view of anything is
-- a query over the log, never a mutation of it.
--
-- WHAT THE DATABASE ITSELF ENFORCES (not convention):
--   * observed_at >= as_of        CHECK. You cannot observe a value before the
--                                 date it refers to.
--   * observed_at <= now()        CHECK. You cannot observe the future. DuckDB
--                                 permits now() in a CHECK and fires on it;
--                                 verified in tests/test_store.py.
--   * grade is a closed enum      including 'raw'.
--   * currency NOT NULL           everywhere money appears.
--   * amount is DECIMAL           never DOUBLE. Cents do not survive binary
--                                 floats and a fee stack is a chain of adds.
--
-- WHAT IT CANNOT ENFORCE, AND WHAT WE DO INSTEAD:
--   DuckDB has no triggers and no rules, so append-only cannot be *prevented*
--   at the engine level. Three layers stand in:
--     1. store/db.py is the only sanctioned writer and has no UPDATE or DELETE
--        path at all.
--     2. ledger_seal is a hash chain over every row inserted. Mutating history
--        breaks the chain, so tampering is DETECTED even when it cannot be
--        blocked.
--     3. store/schema_postgres.sql carries a BEFORE UPDATE OR DELETE trigger
--        and a REVOKE, which genuinely prevents it. That file is the migration
--        target and the reason this schema stays dialect-portable.
--   Detection is weaker than prevention. It is what an embedded database can
--   offer, and saying so is better than implying a guarantee that is not there.

CREATE TYPE grade_t AS ENUM (
    'raw',
    '1', '1.5', '2', '2.5', '3', '3.5', '4', '4.5', '5', '5.5',
    '6', '6.5', '7', '7.5', '8', '8.5', '9', '9.5', '10'
);

-- Half grades exist because CGC and BGS award them and PSA does not. Storing
-- them in one enum keeps a CGC 9.5 and a PSA 9 in the same column without
-- pretending they are the same grade.

CREATE TYPE condition_t AS ENUM (
    'nm', 'lp', 'mp', 'hp', 'dmg', 'graded', 'unknown'
);

CREATE TYPE grader_t AS ENUM ('PSA', 'CGC', 'BGS', 'SGC', 'TAG');

CREATE TYPE language_t AS ENUM ('EN', 'JP', 'CN-S', 'CN-T');

CREATE TYPE game_t AS ENUM ('optcg', 'pkmn', 'riftbound');

CREATE TYPE resolved_by_t AS ENUM ('exact', 'fuzzy', 'manual');

CREATE TYPE obtainment_t AS ENUM (
    'booster', 'box_topper', 'promo_event', 'promo_retailer',
    'tournament_prize', 'starter_deck', 'online_code', 'region_exclusive',
    'unknown'
);

-- ---------------------------------------------------------------- catalog

CREATE TABLE cards (
    card_uid          VARCHAR PRIMARY KEY,
    game              game_t      NOT NULL,
    set_code          VARCHAR     NOT NULL,
    number            VARCHAR     NOT NULL,
    variant           VARCHAR     NOT NULL,
    language          language_t  NOT NULL,
    name_en           VARCHAR,
    name_jp           VARCHAR,
    rarity            VARCHAR,
    artist            VARCHAR,
    release_date      DATE,
    obtainment_class  obtainment_t NOT NULL DEFAULT 'unknown',
    image_url         VARCHAR,
    -- Simplified Chinese One Piece prints a BOX code (OPC-07) and a card
    -- number from a different set (OP04-092), and the two do not correspond.
    -- PSA slabs the card under the box code, so a comp that names it is the
    -- same asset. Both are stored; only the printed set reaches the uid.
    box_code          VARCHAR,
    -- Serialized parallels are printed AT an ordinary card's number, so the
    -- number cannot distinguish them and the flag has to exist. It is
    -- redundant with the variant on purpose: the engine reads the boolean,
    -- the uid reads the variant, and the CHECK stops them drifting apart.
    serialized        BOOLEAN     NOT NULL DEFAULT FALSE,
    -- NULL means not observed, never "not foil". A missing foil flag scored
    -- as False would make every unobserved card look unlike a Treasure Rare.
    foil              BOOLEAN,
    observed_at       TIMESTAMP   NOT NULL,
    source            VARCHAR     NOT NULL,
    CHECK (observed_at <= now()),
    CHECK (NOT serialized OR variant = 'serialized'),
    CHECK (box_code IS NULL OR box_code <> set_code),
    -- The uid must be exactly its own parts. A card whose uid disagrees with
    -- its columns is two cards wearing one key, and every language-merge bug
    -- this schema exists to prevent starts there.
    CHECK (card_uid = game || ':' || set_code || ':' || number || ':'
                      || variant || ':' || language)
);

CREATE TABLE card_xref (
    row_id       BIGINT      PRIMARY KEY,
    card_uid     VARCHAR     NOT NULL REFERENCES cards(card_uid),
    source       VARCHAR     NOT NULL,
    external_id  VARCHAR     NOT NULL,
    secondary_id VARCHAR,
    confidence   DECIMAL(4,3) NOT NULL,
    resolved_by  resolved_by_t NOT NULL,
    as_of        TIMESTAMP   NOT NULL,
    observed_at  TIMESTAMP   NOT NULL,
    supersedes   BIGINT,
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now()),
    CHECK (confidence >= 0 AND confidence <= 1),
    -- A fuzzy match below 0.9 is excluded from every signal (card_uid.md), but
    -- it is still WRITTEN -- the review queue needs to see it. The exclusion
    -- lives in the query, not in a refusal to record.
    CHECK (resolved_by <> 'exact' OR confidence = 1)
);

-- ------------------------------------------------------------ observations

CREATE TABLE price_snapshot (
    row_id        BIGINT      PRIMARY KEY,
    card_uid      VARCHAR     NOT NULL REFERENCES cards(card_uid),
    grade         grade_t     NOT NULL,
    condition     condition_t NOT NULL,
    grader        grader_t,
    marketplace   VARCHAR     NOT NULL,
    amount        DECIMAL(18,4) NOT NULL,
    currency      VARCHAR(3)  NOT NULL,
    fx_rate_used  DECIMAL(18,8),
    fx_as_of      TIMESTAMP,
    sample_size   INTEGER,
    as_of         TIMESTAMP   NOT NULL,
    observed_at   TIMESTAMP   NOT NULL,
    source        VARCHAR     NOT NULL,
    supersedes    BIGINT,
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now()),
    CHECK (amount >= 0),
    -- fx_rate_used and fx_as_of are null together or set together. Null means
    -- "no conversion happened", never "unknown" (ADR-0003).
    CHECK ((fx_rate_used IS NULL) = (fx_as_of IS NULL)),
    -- A graded price must say who graded it; a raw price must not.
    CHECK ((grade = 'raw') = (grader IS NULL)),
    CHECK ((grade = 'raw') OR condition = 'graded'),
    CHECK (sample_size IS NULL OR sample_size >= 0)
);

CREATE TABLE pop_snapshot (
    row_id       BIGINT     PRIMARY KEY,
    card_uid     VARCHAR    NOT NULL REFERENCES cards(card_uid),
    grader       grader_t   NOT NULL,
    grade        grade_t    NOT NULL,
    count        BIGINT     NOT NULL,
    as_of        TIMESTAMP  NOT NULL,
    observed_at  TIMESTAMP  NOT NULL,
    source       VARCHAR    NOT NULL,
    supersedes   BIGINT,
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now()),
    CHECK (count >= 0),
    -- A population is a count of GRADED cards. There is no population of raw.
    CHECK (grade <> 'raw')
);

CREATE TABLE sentiment (
    row_id       BIGINT    PRIMARY KEY,
    card_uid     VARCHAR   NOT NULL REFERENCES cards(card_uid),
    platform     VARCHAR   NOT NULL,
    mentions     BIGINT    NOT NULL,
    engagement   BIGINT,
    as_of        TIMESTAMP NOT NULL,
    observed_at  TIMESTAMP NOT NULL,
    -- GOAL D4: backfilled history is excluded from every backtest. NOT NULL so
    -- the question is answered on every row and never left to a default.
    backfilled   BOOLEAN   NOT NULL,
    source       VARCHAR   NOT NULL,
    supersedes   BIGINT,
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now()),
    CHECK (mentions >= 0),
    CHECK (engagement IS NULL OR engagement >= 0)
);

CREATE TABLE fx_rate (
    row_id       BIGINT       PRIMARY KEY,
    pair         VARCHAR      NOT NULL,
    rate         DECIMAL(18,8) NOT NULL,
    as_of        TIMESTAMP    NOT NULL,
    observed_at  TIMESTAMP    NOT NULL,
    source       VARCHAR      NOT NULL,
    supersedes   BIGINT,
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now()),
    CHECK (rate > 0),
    CHECK (pair SIMILAR TO '[A-Z]{3}/[A-Z]{3}')
);

-- --------------------------------------------------------- gaps, not silence

-- GOAL D1: gaps are recorded as explicit rows, never interpolated away. An
-- adapter that reaches a source and gets nothing writes here; an adapter that
-- could not reach the source at all writes here too, with a different reason.
-- Silence is the one thing this table exists to make impossible.
CREATE TABLE ingest_gap (
    row_id       BIGINT    PRIMARY KEY,
    source       VARCHAR   NOT NULL,
    card_uid     VARCHAR,
    kind         VARCHAR   NOT NULL,
    reason       VARCHAR   NOT NULL,
    detail       VARCHAR,
    as_of        TIMESTAMP NOT NULL,
    observed_at  TIMESTAMP NOT NULL,
    CHECK (observed_at >= as_of),
    CHECK (observed_at <= now())
);

-- --------------------------------------------------------- run bookkeeping

CREATE TABLE ingest_run (
    run_id        VARCHAR   PRIMARY KEY,
    source        VARCHAR   NOT NULL,
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    status        VARCHAR   NOT NULL,
    rows_written  BIGINT    NOT NULL DEFAULT 0,
    gaps_written  BIGINT    NOT NULL DEFAULT 0,
    quota_remaining INTEGER,
    detail        VARCHAR,
    CHECK (started_at <= now())
);

-- ------------------------------------------------------------ tamper seal

-- A hash chain over every inserted row. DuckDB cannot prevent an UPDATE from a
-- direct connection, so this makes one visible: each seal covers the previous
-- seal plus the row's own content, and re-sealing the table from scratch after
-- a mutation produces a different terminal hash.
--
-- This is DETECTION, not prevention. Postgres gets the trigger.
CREATE TABLE ledger_seal (
    seq         BIGINT    PRIMARY KEY,
    table_name  VARCHAR   NOT NULL,
    -- VARCHAR, not BIGINT: `cards` is keyed by card_uid and the fact tables by
    -- row_id, and one chain has to cover both.
    row_key     VARCHAR   NOT NULL,
    row_hash    VARCHAR   NOT NULL,
    chain_hash  VARCHAR   NOT NULL,
    sealed_at   TIMESTAMP NOT NULL,
    CHECK (sealed_at <= now())
);

CREATE SEQUENCE row_id_seq START 1;
CREATE SEQUENCE seal_seq START 1;
