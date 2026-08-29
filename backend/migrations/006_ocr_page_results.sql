-- QUICK-E V6.8 per-page OCR audit storage.
-- Run after 005_ocr_omr_results.sql.

ALTER TABLE exam_submissions
    ADD COLUMN IF NOT EXISTS page1_ocr_text LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS page2_ocr_text LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS ocr_regions_json LONGTEXT NULL;
