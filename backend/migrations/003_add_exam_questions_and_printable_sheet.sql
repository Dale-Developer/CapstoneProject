-- ESSCAN exam/question storage and printable answer-sheet support.
-- Run this once in the automate_assessment_application database.

ALTER TABLE exams
    ADD COLUMN IF NOT EXISTS exam_subject VARCHAR(150) NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS exam_questions (
    question_id INT AUTO_INCREMENT PRIMARY KEY,
    exam_id INT NOT NULL,
    question_number INT NOT NULL,
    question_type ENUM('MCQ','Essay') NOT NULL,
    question_text LONGTEXT NOT NULL,
    option_a LONGTEXT NULL,
    option_b LONGTEXT NULL,
    option_c LONGTEXT NULL,
    option_d LONGTEXT NULL,
    option_e LONGTEXT NULL,
    correct_option CHAR(1) NULL,
    answer_key LONGTEXT NULL,
    points DECIMAL(6,2) NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_exam_questions_exam_id (exam_id),
    CONSTRAINT fk_exam_questions_exam
        FOREIGN KEY (exam_id) REFERENCES exams(exam_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exam_rubrics (
    rubric_id INT AUTO_INCREMENT PRIMARY KEY,
    exam_id INT NOT NULL,
    criterion_order INT NOT NULL,
    criterion_name VARCHAR(150) NOT NULL,
    weight DECIMAL(6,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_exam_rubrics_exam_id (exam_id),
    CONSTRAINT fk_exam_rubrics_exam
        FOREIGN KEY (exam_id) REFERENCES exams(exam_id)
        ON DELETE CASCADE
);
