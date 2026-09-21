-- V7.9.7: add the Admin role.
--
-- users.role is a MySQL ENUM, so the column must be widened before the
-- application can store the new value. Run this BEFORE deploying the code:
-- with the old column in place, creating an admin fails with a data
-- truncation error.
--
-- Safe to re-run. Existing rows are untouched -- an ALTER that only ADDS a
-- value to the end of an ENUM does not rewrite or invalidate stored data.

ALTER TABLE users
    MODIFY COLUMN role ENUM('Professor', 'Student', 'Admin') NOT NULL;

-- Verify:
--   SHOW COLUMNS FROM users LIKE 'role';
-- should now read: enum('Professor','Student','Admin')

-- Create the first administrator from the command line, NOT here -- passwords
-- must be bcrypt-hashed by the application, and an INSERT with a plaintext
-- password would create an account nobody can log into:
--
--   cd backend
--   python admin.py create --email you@school.edu --first Your --last Name --role Admin
--
-- Omit --password and it prompts, so it never enters your shell history.
