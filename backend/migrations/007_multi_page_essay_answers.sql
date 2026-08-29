-- V7.3: essay answers now span an unbounded number of pages (2 essay
-- answers per printed page instead of a single fixed "page 2"). Store the
-- ordered list of essay-page file paths and their OCR text as JSON.
-- Run after 006_optional_exam_types_and_page_ocr.sql.

ALTER TABLE exam_submissions
    ADD COLUMN IF NOT EXISTS essay_pages_json LONGTEXT NULL,
    ADD COLUMN IF NOT EXISTS essay_pages_ocr_json LONGTEXT NULL;
