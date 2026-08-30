-- Backup first! mysqldump automate_assessment_application > backup_before_cleanup.sql

DROP TABLE IF EXISTS `submission_pages`;   -- has the one FK, drop first
DROP TABLE IF EXISTS `answer_keys`;
DROP TABLE IF EXISTS `choices`;
DROP TABLE IF EXISTS `criteria_scores`;
DROP TABLE IF EXISTS `essay_evaluations`;
DROP TABLE IF EXISTS `mcq_evaluations`;
DROP TABLE IF EXISTS `ocr_results`;
DROP TABLE IF EXISTS `question_bank`;
DROP TABLE IF EXISTS `rubric_criteria`;
DROP TABLE IF EXISTS `rubrics`;
DROP TABLE IF EXISTS `student_answers`;