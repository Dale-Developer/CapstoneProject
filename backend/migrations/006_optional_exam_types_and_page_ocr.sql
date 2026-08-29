-- QUICK-E V6.9: optional MCQ/Essay exam types and page-specific OCR audit fields.
-- Run after 005_ocr_omr_results.sql.

ALTER TABLE exam_submissions
    ADD COLUMN IF NOT EXISTS page1_ocr_text LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS page2_ocr_text LONGTEXT NULL;
