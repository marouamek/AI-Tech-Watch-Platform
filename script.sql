CREATE DATABASE veille_ia
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

use veille_ia;

CREATE TABLE articles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    source VARCHAR(100) NOT NULL,
    published VARCHAR(20),
    link TEXT,
    collected_at DATETIME,
    hash CHAR(64) UNIQUE,
    verifie TINYINT(1) DEFAULT 0,
     categorie VARCHAR(100),     
     mots_cles TEXT               
);

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    is_first_login TINYINT(1) NOT NULL DEFAULT 1
);


DROP TABLE IF EXISTS syntheses;

CREATE TABLE syntheses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title TEXT,
    content LONGTEXT,
    class INT,
    date DATETIME DEFAULT CURRENT_TIMESTAMP
);

