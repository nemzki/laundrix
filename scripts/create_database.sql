-- Run once in MySQL Workbench as an admin user (e.g. root).
CREATE DATABASE IF NOT EXISTS laundrix_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- Recommended: a dedicated least-privilege user instead of root.
-- Replace the password, then put these values in your .env file.
CREATE USER IF NOT EXISTS 'laundrix_user'@'localhost' IDENTIFIED BY 'sharkforever17';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON laundrix_db.* TO 'laundrix_user'@'localhost';
FLUSH PRIVILEGES;
