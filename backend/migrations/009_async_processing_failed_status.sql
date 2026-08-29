-- ESSCAN V7.9.4: background/async submission processing.
--
-- Upload endpoints now return as soon as the answer sheet is saved and
-- locked; OMR/OCR/spaCy/SBERT grading runs afterward in a background task
-- instead of blocking the request. This is what lets a professor scan one
-- student and move straight to the next without waiting through OCR and
-- essay grading in between.
--
-- 'Failed' is the one new thing background processing needs: if the
-- pipeline raises (a corrupted image, an OCR crash, etc.) the submission
-- must land somewhere visible and explained rather than sitting forever in
-- 'OCR_Processing' with no way to tell the difference between "still
-- working" and "silently broken". The error itself is recorded in the
-- existing processing_metadata_json column — no new column needed for that.
--
-- Run after 008_essay_grading_override_and_release.sql.

ALTER TABLE exam_submissions
    MODIFY COLUMN submission_status
        ENUM('Pending','Uploaded','OCR_Processing','OCR_Completed',
             'NLP_Processing','Graded','Released','Failed')
        NOT NULL DEFAULT 'Pending';
