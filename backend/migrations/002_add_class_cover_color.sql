-- Adds a nullable cover_color column so the "Create Class" modal's color
-- picker (see CreateClassModal.jsx) has somewhere to persist. Safe to run
-- once against your existing automate_assessment_application database.

ALTER TABLE `classes`
  ADD COLUMN `cover_color` VARCHAR(20) DEFAULT '#462776' AFTER `class_code`;
