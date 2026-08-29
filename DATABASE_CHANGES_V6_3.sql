-- QUICK-E V6.3 database changes for paper-based exam creation and future AI grading.
-- Run this directly in MariaDB/MySQL after selecting automate_assessment_application.
-- This is intentionally NOT a FastAPI/SQLAlchemy migration.

USE automate_assessment_application;

-- 1. Per-question AI-ready essay metadata.
ALTER TABLE exam_questions
    ADD COLUMN IF NOT EXISTS key_concepts LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS keywords LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS requirements LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS expected_response_format VARCHAR(50) NOT NULL DEFAULT 'one_paragraph';

-- 2. Make rubric records attachable to an individual essay question.
-- Existing V6.3 exam-level rubric rows remain valid with question_id = NULL.
ALTER TABLE exam_rubrics
    ADD COLUMN IF NOT EXISTS question_id INT NULL;

-- 3. Add an index for question-level rubric lookup.
ALTER TABLE exam_rubrics
    ADD INDEX IF NOT EXISTS idx_exam_rubrics_question_id (question_id);

-- 4. Link question-level rubrics to exam_questions.
-- Existing rows are not deleted or modified; only new question-specific rows
-- will use question_id.
SET @fk_exists := (
    SELECT COUNT(*)
    FROM information_schema.REFERENTIAL_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'exam_rubrics'
      AND CONSTRAINT_NAME = 'fk_exam_rubrics_question'
);

SET @sql := IF(
    @fk_exists = 0,
    'ALTER TABLE exam_rubrics ADD CONSTRAINT fk_exam_rubrics_question FOREIGN KEY (question_id) REFERENCES exam_questions(question_id) ON DELETE CASCADE',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 5. Optional verification.
DESCRIBE exam_questions;
DESCRIBE exam_rubrics;

-- Expected new exam_questions fields:
-- key_concepts, keywords, requirements, expected_response_format
-- Expected new exam_rubrics field:
-- question_id
