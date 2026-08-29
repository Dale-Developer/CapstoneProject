-- ESSCAN V7.9: essay NLP grading, professor score override, score release,
-- and single-submission locking.
-- Run after 007_multi_page_essay_answers.sql.

-- ---------------------------------------------------------------------------
-- exam_submissions
-- ---------------------------------------------------------------------------
-- mcq_score / essay_score are stored separately from final_score so the
-- professor can see where the total came from, and so releasing a score does
-- not require re-running the pipeline.
ALTER TABLE exam_submissions
    ADD COLUMN IF NOT EXISTS mcq_score DECIMAL(6,2) NULL,
    ADD COLUMN IF NOT EXISTS essay_score DECIMAL(6,2) NULL,
    ADD COLUMN IF NOT EXISTS max_score DECIMAL(6,2) NULL,
    ADD COLUMN IF NOT EXISTS scores_released TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS released_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS released_by INT NULL,
    ADD COLUMN IF NOT EXISTS is_locked TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS uploaded_by INT NULL;

-- 'Released' is a new terminal state after 'Graded'.
ALTER TABLE exam_submissions
    MODIFY COLUMN submission_status
        ENUM('Pending','Uploaded','OCR_Processing','OCR_Completed',
             'NLP_Processing','Graded','Released')
        NOT NULL DEFAULT 'Pending';

-- Students filter their own results constantly; professors filter by exam.
CREATE INDEX IF NOT EXISTS idx_exam_submissions_student_released
    ON exam_submissions (student_id, scores_released);

-- Any submission that already carries OCR output has been through the
-- pipeline, so lock it. Without this, existing rows would let a student
-- silently overwrite a processed sheet the first time they revisit the page.
UPDATE exam_submissions
   SET is_locked = 1,
       processed_at = COALESCE(processed_at, submitted_at)
 WHERE is_locked = 0
   AND (combined_ocr_text IS NOT NULL OR omr_result_json IS NOT NULL);

UPDATE exam_submissions
   SET attempt_count = 1
 WHERE attempt_count = 0
   AND submitted_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- submission_answers
-- ---------------------------------------------------------------------------
-- override_score is separate from auto_score on purpose: the AI's original
-- judgement is preserved for audit, and clearing the override restores it.
ALTER TABLE submission_answers
    ADD COLUMN IF NOT EXISTS answer_text LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS auto_score DECIMAL(6,2) NULL,
    ADD COLUMN IF NOT EXISTS override_score DECIMAL(6,2) NULL,
    ADD COLUMN IF NOT EXISTS override_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS overridden_by INT NULL,
    ADD COLUMN IF NOT EXISTS overridden_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS max_score DECIMAL(6,2) NULL,
    ADD COLUMN IF NOT EXISTS feedback_json LONGTEXT NULL;

ALTER TABLE submission_answers
    MODIFY COLUMN processing_status
        ENUM('Pending','Detected','Confirmed','Ambiguous','Blank',
             'Graded','Overridden')
        NOT NULL DEFAULT 'Pending';
