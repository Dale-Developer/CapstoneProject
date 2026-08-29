ALTER TABLE exam_submissions
  ADD COLUMN page1_path VARCHAR(500) NULL,
  ADD COLUMN page2_path VARCHAR(500) NULL,
  ADD COLUMN student_filename VARCHAR(255) NULL;
