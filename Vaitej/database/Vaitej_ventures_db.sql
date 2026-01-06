/* ============================================================
   DATABASE
============================================================ */
CREATE DATABASE IF NOT EXISTS vaitej_ventures;
USE vaitej_ventures;

/* ============================================================
   1. USERS
============================================================ */
CREATE TABLE users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    role ENUM('founder','investor','admin') NOT NULL,

    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,

    phone VARCHAR(30),
    country VARCHAR(100),
    profile_photo VARCHAR(255),

    is_verified BOOLEAN DEFAULT FALSE,
    status ENUM('active','suspended','pending') DEFAULT 'active',

    referral_source VARCHAR(255),

    last_login DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

/* ============================================================
   2. FOUNDER PROFILES
============================================================ */
CREATE TABLE founder_profiles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT UNIQUE NOT NULL,

    company_name VARCHAR(150) NOT NULL,
    tagline VARCHAR(255),
    website_url VARCHAR(255),
    linkedin_url VARCHAR(255),
    location VARCHAR(120),

    founding_year YEAR,
    stage ENUM('idea','pre-seed','seed','series-a','series-b+'),
    sector VARCHAR(120),
    business_model VARCHAR(120),

    fundraising_status ENUM('not_started','preparing','raising') DEFAULT 'not_started',
    fundraising_start_date DATE,

    raise_target BIGINT DEFAULT 0,
    raise_raised BIGINT DEFAULT 0,
    min_check_size BIGINT,
    actively_raising BOOLEAN DEFAULT FALSE,

    logo_url VARCHAR(255),
    team_size INT DEFAULT 1,
    product_stage VARCHAR(50),

    key_metrics JSON,
    traction_report TEXT,
    profile_completion INT DEFAULT 0,
    last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

/* ============================================================
   3. INVESTOR PROFILES
============================================================ */
CREATE TABLE investor_profiles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT UNIQUE NOT NULL,

    title VARCHAR(120),
    fund_name VARCHAR(150),
    fund_size DECIMAL(15,2),

    typical_check_min DECIMAL(15,2),
    typical_check_max DECIMAL(15,2),

    investment_stage VARCHAR(255),
    sector_focus VARCHAR(255),
    geography_focus VARCHAR(255),

    accredited BOOLEAN DEFAULT FALSE,
    verification_status ENUM('unverified','pending','verified','rejected') DEFAULT 'unverified',
    activity_status ENUM('active','dormant') DEFAULT 'active',

    investment_thesis TEXT,
    notable_investments TEXT,
    portfolio_url VARCHAR(255),

    profile_completion INT DEFAULT 0,
    privacy_settings JSON,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

/* ============================================================
   4. MATCHES (AI CORE)
============================================================ */
CREATE TABLE matches (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    founder_id BIGINT NOT NULL,
    investor_id BIGINT NOT NULL,

    match_score INT NOT NULL,
    status ENUM(
        'new','interested','saved','declined',
        'connected','due_diligence','invested'
    ) DEFAULT 'new',

    ai_reason TEXT,
    invested_amount BIGINT DEFAULT 0,
    invested_at DATETIME,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uniq_match (founder_id, investor_id),

    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (investor_id) REFERENCES investor_profiles(id) ON DELETE CASCADE
);

/* ============================================================
   5. PROFILE VIEW TRACKING
============================================================ */
CREATE TABLE investor_profile_views (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    founder_id BIGINT NOT NULL,
    investor_id BIGINT NOT NULL,
    viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id),
    FOREIGN KEY (investor_id) REFERENCES investor_profiles(id)
);

/* ============================================================
   6. PITCH DECKS
============================================================ */
CREATE TABLE pitch_decks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    founder_id BIGINT NOT NULL,

    file_url VARCHAR(255) NOT NULL,
    version INT DEFAULT 1,
    deck_score INT DEFAULT 0,

    analysis_json JSON,
    feedback_summary TEXT,

    is_published BOOLEAN DEFAULT FALSE,
    published_at DATETIME,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id) ON DELETE CASCADE
);

/* ============================================================
   7. DECK ACCESS LOGS
============================================================ */
CREATE TABLE deck_access_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    deck_id BIGINT NOT NULL,
    investor_id BIGINT NOT NULL,
    viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (deck_id) REFERENCES pitch_decks(id),
    FOREIGN KEY (investor_id) REFERENCES investor_profiles(id)
);

/* ============================================================
   8. CONVERSATIONS & MESSAGES
============================================================ */
CREATE TABLE conversations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    founder_id BIGINT NOT NULL,
    investor_id BIGINT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_conversation (founder_id, investor_id),
    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id),
    FOREIGN KEY (investor_id) REFERENCES investor_profiles(id)
);

CREATE TABLE messages (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    sender_id BIGINT NOT NULL,
    message TEXT,
    attachment_url VARCHAR(255),
    is_read BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id),
    FOREIGN KEY (sender_id) REFERENCES users(id)
);

/* ============================================================
   9. AI SESSIONS
============================================================ */
CREATE TABLE ai_sessions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    session_type ENUM(
        'deck_analysis','qa_simulator',
        'readiness_report','deal_memo'
    ),
    input_ref_id BIGINT,
    output_summary JSON,
    score INT,
    status ENUM('in_progress','completed','failed') DEFAULT 'in_progress',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

/* ============================================================
   10. QA SIMULATOR
============================================================ */
CREATE TABLE qa_sessions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    founder_id BIGINT NOT NULL,
    deck_id BIGINT NOT NULL,
    transcript_json JSON,
    session_score INT DEFAULT 0,
    session_type VARCHAR(20) DEFAULT 'official',
    status ENUM('in_progress','completed') DEFAULT 'in_progress',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id),
    FOREIGN KEY (deck_id) REFERENCES pitch_decks(id)
);

/* ============================================================
   11. INVESTMENT REPORTS
============================================================ */
CREATE TABLE investment_reports (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    founder_id BIGINT NOT NULL,
    deck_id BIGINT NOT NULL,
    report_content LONGTEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id),
    FOREIGN KEY (deck_id) REFERENCES pitch_decks(id)
);

/* ============================================================
   12. DUE DILIGENCE
============================================================ */
CREATE TABLE due_diligence (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    investor_id BIGINT NOT NULL,
    founder_id BIGINT NOT NULL,
    private_notes TEXT,
    checklist_json JSON,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_dd (investor_id, founder_id),
    FOREIGN KEY (investor_id) REFERENCES investor_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id) ON DELETE CASCADE
);

/* ============================================================
   13. FOUNDER UPDATES & TRACTION
============================================================ */
CREATE TABLE founder_updates (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    founder_id BIGINT NOT NULL,
    month_label VARCHAR(50),
    update_text TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id)
);

CREATE TABLE traction_metrics (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    founder_id BIGINT NOT NULL,
    month_label VARCHAR(50),
    revenue DECIMAL(15,2) DEFAULT 0,
    expenses DECIMAL(15,2) DEFAULT 0,
    active_users INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (founder_id) REFERENCES founder_profiles(id) ON DELETE CASCADE
);

/* ============================================================
   14. ADMIN & AUDIT
============================================================ */
CREATE TABLE admin_users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    role ENUM('super_admin','ops','support','read_only'),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE audit_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    admin_id BIGINT,
    action VARCHAR(255),
    target_type VARCHAR(100),
    target_id BIGINT,
    details JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES users(id)
);

/* ============================================================
   15. INDEXES (PERFORMANCE)
============================================================ */
CREATE INDEX idx_matches_investor_score ON matches (investor_id, match_score);
CREATE INDEX idx_messages_unread ON messages (conversation_id, is_read);
CREATE INDEX idx_pitch_recent ON pitch_decks (founder_id, created_at);
CREATE INDEX idx_traction_recent ON traction_metrics (founder_id, created_at);
