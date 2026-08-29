-- QUICK-E V6.6 OMR and OCR audit storage.
-- Run after 004_student_submissions.sql.

ALTER TABLE exam_submissions
    ADD COLUMN IF NOT EXISTS easyocr_text LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS ollama_text LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS combined_ocr_text LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS omr_result_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS processing_metadata_json LONGTEXT NULL;

CREATE TABLE IF NOT EXISTS submission_answers (
    answer_id INT AUTO_INCREMENT PRIMARY KEY,
    submission_id INT NOT NULL,
    question_id INT NOT NULL,
    selected_option CHAR(1) NULL,
    processing_status ENUM('Pending','Detected','Confirmed','Ambiguous','Blank') NOT NULL DEFAULT 'Pending',
    is_blank TINYINT(1) NOT NULL DEFAULT 0,
    is_ambiguous TINYINT(1) NOT NULL DEFAULT 0,
    confidence DECIMAL(6,4) NULL,
    best_fill_ratio DECIMAL(7,4) NULL,
    second_fill_ratio DECIMAL(7,4) NULL,
    option_measurements LONGTEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_submission_question (submission_id, question_id),
    INDEX idx_submission_answers_submission_id (submission_id),
    INDEX idx_submission_answers_question_id (question_id),
    CONSTRAINT fk_submission_answers_submission
        FOREIGN KEY (submission_id) REFERENCES exam_submissions(submission_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_submission_answers_question
        FOREIGN KEY (question_id) REFERENCES exam_questions(question_id)
        ON DELETE CASCADE
);
